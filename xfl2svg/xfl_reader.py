"""Read and preprocess an XFL project."""

from dataclasses import dataclass
import io
import os
import struct
import xml.etree.ElementTree as ET
import zipfile

from xfl2svg.util import unescape_entities


@dataclass
class Timeline:
    layers: ET.Element
    last_frame: int


class CloseOnExit:
    """Helper class for creating context managers."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class XflReader(CloseOnExit):
    """Read and preprocess an XFL project."""

    # Marks the bottommost (or backmost) layer of a mask's children. Value is
    # the index of the mask layer in question.
    MASK_START = ET.QName("xfl2svg", "maskStart")

    def __init__(self, path):
        """Create an XflReader.

        `.close()` should be called when the caller is done with this object.

        Args:
            path: ".fla" file or the directory of a decompressed ".fla"
        """
        if os.path.isfile(path):
            if os.path.splitext(path)[1] != ".fla":
                raise Exception(f'File is not a ".fla": {path}')
            self.xfl = _ZippedXflReader(path)
        elif os.path.isdir(path):
            self.xfl = _UnzippedXflReader(path)
        else:
            raise Exception(f"Path does not exist: {path}")

        self.document = self.xfl.get_dom_document()
        self.stage_width = int(self.document.get("width"))
        self.stage_height = int(self.document.get("height"))
        self.stage_color = self.document.get("backgroundColor", "#FFFFFF")

        self.scenes = {}
        self.symbols = {}
        self.symbol_paths = {}

        for scene in self.document.iterfind(".//{*}DOMTimeline"):
            name = unescape_entities(scene.get("name"))
            assert name not in self.scenes, f"Duplicate scene name: {name}"
            # Store layers for lazy processing
            self.scenes[name] = scene.find(".//{*}layers")

        for include in self.document.iterfind(".//{*}symbols/{*}Include"):
            path = include.get("href")
            # Remove the ".xml" extension
            name = unescape_entities(os.path.splitext(path)[0])
            assert name not in self.symbol_paths, f"Duplicate symbol name: {name}"
            self.symbol_paths[name] = path

    def get_scene_names(self):
        return list(self.scenes.keys())

    def get_symbol_names(self):
        # `symbol_paths` has the name of every symbol, whether it's been
        # setup already or not
        return list(self.symbol_paths.keys())

    def get_timeline(self, name, type="symbol"):
        """Return the timeline with the given name.

        Args:
            name: *Entity unescaped* timeline name. This lets users give the
                  name they see in the Animate, not the escaped name.
            type: Timeline type ("symbol" or "scene")

        Returns:
            `Timeline` object
        """
        if type == "scene":
            if name not in self.scenes:
                raise Exception(f"Scene does not exist: {name}")
            elif not isinstance(self.scenes[name], Timeline):
                self.scenes[name] = setup_timeline(self.scenes[name])

            return self.scenes[name]
        elif type == "symbol":
            if name not in self.symbols:
                if name not in self.symbol_paths:
                    raise Exception(f"Symbol does not exist: {name}")

                # Symbol files might not exist. Or, &'s might have been
                # replaced with _'s
                path = self.symbol_paths[name]
                if not self.xfl.symbol_path_exists(path):
                    path = path.replace("&", "_")
                    if not self.xfl.symbol_path_exists(path):
                        raise Exception(f"Couldn't find XML file for {name}")

                symbol = self.xfl.get_symbol(path)
                self.symbols[name] = setup_timeline(symbol.find(".//{*}layers"))

            return self.symbols[name]
        else:
            raise Exception('Timeline type must be "scene" or "symbol"')

    def close(self):
        self.xfl.close()


def setup_timeline(layers):
    # We mark the last layer of each mask's children with MASK_START. Since
    # SvgRenderer iterates from bottom to top (back to front), this lets it
    # know when it should begin a mask.
    mask_idx = None
    for i, layer in enumerate(layers):
        if mask_idx is None:
            if layer.get("layerType") == "mask":
                mask_idx = i
        elif (
            i + 1 == len(layers)
            or int(layers[i + 1].get("parentLayerIndex", -1)) < mask_idx
        ):
            # Either this is the last layer or the next layer doesn't belong to
            # the mask. So, this is the last layer of the current mask.
            layer.set(XflReader.MASK_START, mask_idx)
            mask_idx = None

    return Timeline(layers, get_timeline_length(layers) - 1)


def get_timeline_length(layers):
    length = None
    # Only check <DOMLayer>s with a non-empty <frames> element
    for layer in filter(lambda l: len(l) and len(l[0]), layers):
        i = int(layer[0][-1].get("index")) + int(layer[0][-1].get("duration", 1))
        length = i if length is None else max(length, i)

    return length


class _UnzippedXflReader(CloseOnExit):
    """Read from an unzipped XFL project."""

    def __init__(self, root_path):
        self.root_path = root_path
        self.library_path = os.path.join(root_path, "LIBRARY")

    def get_dom_document(self):
        return ET.parse(os.path.join(self.root_path, "DOMDocument.xml")).getroot()

    def symbol_path_exists(self, symbol_path):
        return os.path.exists(os.path.join(self.library_path, symbol_path))

    def get_symbol(self, symbol_path):
        return ET.parse(os.path.join(self.library_path, symbol_path)).getroot()

    def close(self):
        pass


class _ZippedXflReader(CloseOnExit):
    """Read from a zipped XFL project (.fla)."""

    def __init__(self, filename):
        self.zip, self.fla = open_fla(filename)
        self.name_list = set(self.zip.namelist())

    def get_dom_document(self):
        with self.zip.open("DOMDocument.xml") as f:
            return ET.parse(f).getroot()

    def symbol_path_exists(self, symbol_path):
        return os.path.join("LIBRARY", symbol_path) in self.name_list

    def get_symbol(self, symbol_path):
        with self.zip.open(os.path.join("LIBRARY", symbol_path)) as f:
            return ET.parse(f).getroot()

    def close(self):
        self.zip.close()
        self.fla.close()


def open_fla(filename):
    """Open a `.fla` file.

    For some reason, Animate produces zip files with an invalid end of central
    directory (EOCD) record. Specifically, the "size of central directory"
    field is always 54 bytes too high. (Even weirder: if you create a new
    project and save it without changing anything, the zip file will be valid.)

    `zipfile` chokes on these files, so we need to intercept the EOCD record
    read and fix the field if it's wrong. This is hacky, but it works on Python
    3.9. It may not work on older or newer versions if `zipfile` changes how it
    reads the EOCD record.

    Returns a tuple: (objects should be closed by the caller in this order)
        ZipFile object
        .fla file object
    """
    fla_file = open(filename, "rb")
    try:
        # Try opening it normally first
        return zipfile.ZipFile(fla_file), fla_file
    except zipfile.BadZipFile as exc:
        # If it's not the error we expect, this file is invalid in some other way
        if exc.args[0] != "Bad magic number for central directory":
            raise exc

    # Animate's zip files don't have an archive comment, making the EOCD 22
    # bytes long. To read the EOCD, `zipfile` will call:
    #
    #  fla_file.seek(-22, io.SEEK_END)
    #  fla_file.read()
    #
    # We override seek() and read() to intercept these calls and fix the EOCD
    # if necessary. Afterwards, we put back the original methods.

    EOCD_FORMAT = "<4s4H2LH"
    EOCD_SIZE = 22
    CDIR_SIZE_CORRECTION = 54

    real_seek = fla_file.seek
    real_read = fla_file.read

    def fake_seek(self, offset, whence=io.SEEK_SET):
        if offset == -EOCD_SIZE and whence == io.SEEK_END:
            # Perform the seek and get the zip's total size
            zip_size = EOCD_SIZE + real_seek(offset, whence)
            eocd_data = self.read()
            eocd = list(struct.unpack(EOCD_FORMAT, eocd_data))
            cdir_size = eocd[5]
            cdir_offset = eocd[6]

            # Assuming the central dir offset is right, is the size wrong?
            actual_cdir_size = zip_size - cdir_offset - EOCD_SIZE
            delta = cdir_size - actual_cdir_size
            if delta == CDIR_SIZE_CORRECTION:
                eocd[5] -= CDIR_SIZE_CORRECTION
                eocd_data = struct.pack(EOCD_FORMAT, *eocd)
            elif delta != 0:
                raise Exception(
                    f"Central directory size is off by an unexpected amount: {delta}"
                )

            self.seek = real_seek

            # Fake the next read() to return `eocd_data`
            def fake_read(self, size=-1):
                if size != -1:
                    # We expect read() to be called with no arguments
                    raise Exception(f"Expected size of -1, not {size}")
                self.read = real_read
                return eocd_data

            self.read = fake_read.__get__(self)
        else:
            return real_seek(offset, whence)

    # __get__ turns a function into a method: https://stackoverflow.com/a/46757134
    fla_file.seek = fake_seek.__get__(fla_file)

    return zipfile.ZipFile(fla_file, mode="r"), fla_file
