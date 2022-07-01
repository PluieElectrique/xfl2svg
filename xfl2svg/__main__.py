"""Command-line interface for xfl2svg."""


def main_imports():
    # For responsiveness, we import after parsing arguments. It's messy, but
    # allows us to still declare imports at the start of the module.
    global os, re, sys, ET, trange, XflReader, SvgRenderer

    import os
    import re
    import sys
    import xml.etree.ElementTree as ET

    try:
        from tqdm import trange
    except ImportError:
        trange = range

    from xfl2svg.xfl_reader import XflReader
    from xfl2svg.svg_renderer import SvgRenderer


def parse_args():
    import argparse

    parser = argparse.ArgumentParser(description="Convert Adobe Animate XFL to SVG.")

    main_args = parser.add_argument_group(title="Main arguments")
    main_args.add_argument(
        "xfl", help=".fla file or the directory of a decompressed .fla"
    )
    main_args.add_argument("timeline", help="Timeline to render (scene or symbol)")
    main_args.add_argument("output_dir", help="Output directory")
    main_args.add_argument(
        "--timeline-type",
        choices=["scene", "symbol"],
        help="Specify timeline type (default: try to guess)",
    )

    other_args = parser.add_argument_group(title="Other arguments")
    other_args.add_argument(
        "--first-frame",
        type=int,
        default=1,
        metavar="FRAME",
        help="First frame to render (default: 1)",
    )
    other_args.add_argument(
        "--last-frame",
        type=int,
        metavar="FRAME",
        help="Last frame to render (default: last frame of timeline)",
    )
    other_args.add_argument(
        "--width", type=float, help="SVG width (default: stage width)"
    )
    other_args.add_argument(
        "--height", type=float, help="SVG height (default: stage height)"
    )
    other_args.add_argument(
        "--background", metavar="COLOR", help="Background color (default: stage color)"
    )
    other_args.add_argument(
        "--no-background", action="store_true", help="Disable background"
    )
    other_args.add_argument(
        "--center", action="store_true", help="Center output in viewport"
    )
    other_args.add_argument(
        "--indent", action="store_true", help="Indent SVG (Python 3.9+)"
    )

    debug_args = parser.add_argument_group(title="Debug arguments")
    debug_args.add_argument(
        "--print-scenes", action="store_true", help="Print scene names"
    )
    debug_args.add_argument(
        "--print-symbols", action="store_true", help="Print symbol names"
    )

    return parser.parse_args()


def die(err):
    print("Error:", err, file=sys.stderr)
    sys.exit(1)


def sanitize_filename(filename, extension="", MAX_BYTES=255):
    # Remove ASCII control characters
    filename = re.sub(r"[\x00-\x1f\x7f]", "", filename)
    # The Windows forbidden characters are common enough that we replace them
    # with an underscore to show that a character was replaced.
    filename = re.sub(r'[\\/:*?"<>|]', "_", filename)
    # Prepend an underscore to files starting with a dot or dash--this prevents
    # the file from being hidden or being interpreted as a flag on Unix-likes.
    # We need _* to ensure that prepending an underscore doesn't conflict with
    # any existing files.
    if re.match(r"_*[-.]", filename):
        filename = "_" + filename
    # Limit the filename length. We assume UTF-8.
    max_bytes = MAX_BYTES - len(extension)
    encoded = filename.encode()
    if len(encoded) > max_bytes:
        filename = encoded[:max_bytes].decode(errors="ignore")
    return filename + extension


def main():
    args = parse_args()
    main_imports()

    # Check if ET.indent is available
    if args.indent and not hasattr(ET, "indent"):
        die("--indent requires Python 3.9+")

    # Create XFL reader and SVG renderer
    xfl_reader = XflReader(args.xfl)
    svg_renderer = SvgRenderer(xfl_reader)

    scene_names = xfl_reader.get_scene_names()
    symbol_names = xfl_reader.get_symbol_names()

    # Print names
    if args.print_scenes:
        print("Scenes:")
        for name in scene_names:
            print(" ", name)
    if args.print_symbols:
        print("Symbols:")
        for name in symbol_names:
            print(" ", name)
    if args.print_scenes or args.print_symbols:
        return

    # Get SVG dimensions
    width = args.width or xfl_reader.stage_width
    height = args.height or xfl_reader.stage_height

    # Determine timeline type
    is_scene = args.timeline in scene_names
    is_symbol = args.timeline in symbol_names
    if not is_scene and not is_symbol:
        die(f"Timeline does not exist: {args.timeline}")
    elif args.timeline_type is None:
        timeline_type = "scene" if is_scene else "symbol"
    else:
        timeline_type = args.timeline_type

    # Determine frame range
    first_frame = args.first_frame
    # Internally, frames start at 0
    last_frame = xfl_reader.get_timeline(args.timeline, timeline_type).last_frame + 1

    if first_frame < 1:
        die("First frame can't be less than 1")
    if args.last_frame is not None:
        if last_frame < args.last_frame:
            die(f"Last frame of {args.timeline} is {last_frame}")
        last_frame = args.last_frame
    if first_frame > last_frame:
        die("First frame can't be greater than last frame")

    # If the minimum padding for frame indexes is always used, then changing
    # the last frame can easily create a completely different set of files. For
    # example, changing the last frame from 10 to 9 would create 9 new files
    # (1, 2, ...) instead of overwriting the old ones (01, 02, ...). Three
    # digits seems like a reasonable default.
    filename_frame_digits = max(3, len(str(last_frame)))

    # Create output directory
    if args.output_dir != "":
        os.makedirs(args.output_dir, exist_ok=True)

    for frame_idx in trange(first_frame, last_frame + 1):
        svg = svg_renderer.render(
            args.timeline,
            frame_idx - 1,
            width,
            height,
            timeline_type,
            # We don't modify the SVG, so use `copy=False` to improve performance
            copy=False,
        )

        if args.center:
            # To center the body, we move <defs> to a new <svg>, change the old
            # <svg> to a centering <g>, and then append it in the new <svg>.
            # NOTE: We're modifying the SVG after we passed `copy=False`, but
            # we're only touching the <svg> element, which is actually not
            # cached. Hacky, but it works.
            old_svg = svg.getroot()
            new_svg = ET.Element("svg", old_svg.attrib)
            new_svg.append(old_svg[0])
            del old_svg[0]
            old_svg.tag = "g"
            old_svg.attrib = {"transform": f"matrix(1, 0, 0, 1, {width/2}, {height/2})"}
            new_svg.append(old_svg)
            svg._setroot(new_svg)

        if not args.no_background:
            background = args.background or xfl_reader.stage_color
            svg.getroot().insert(
                1,
                ET.Element(
                    "rect",
                    {"fill": background, "width": str(width), "height": str(height)},
                ),
            )

        if args.indent:
            ET.indent(svg)

        filename_frame = str(frame_idx).zfill(filename_frame_digits)
        filename = os.path.join(
            args.output_dir,
            sanitize_filename(args.timeline, f"_{filename_frame}.svg"),
        )
        with open(filename, "w") as f:
            svg.write(f, encoding="unicode")

    xfl_reader.close()


if __name__ == "__main__":
    main()
