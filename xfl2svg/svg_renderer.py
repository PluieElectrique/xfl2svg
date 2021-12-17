"""Render SVGs from XFL."""

from functools import lru_cache
import re
import warnings
import xml.etree.ElementTree as ET

from xfl2svg.color_effect import ColorEffect
from xfl2svg.shape import xfl_domshape_to_svg
from xfl2svg.util import get_matrix, unescape_entities


# SVG 1.1 requires that we use the `xlink` namespace for `href`. SVG 2 doesn't,
# but it's not well supported yet. See:
# https://nikosandronikos.github.io/svg2-info/svg2-feature-support/
HREF = ET.QName("http://www.w3.org/1999/xlink", "href")
# This ensures that the namespace will be declared as `xmlns:xlink`, rather
# than the unnamed `xmlns:ns0`.
ET.register_namespace("xlink", "http://www.w3.org/1999/xlink")


class SvgRenderer:
    """Render SVGs from XFL."""

    def __init__(self, xfl_reader, DOMSHAPE_CACHE_SIZE=2048):
        self.xfl_reader = xfl_reader
        self.mask_num = 1
        # Ensure that each renderer has its own cache
        self._handle_domshape = lru_cache(maxsize=DOMSHAPE_CACHE_SIZE)(_handle_domshape)

    def render(self, timeline_name, frame_idx, width, height, type="symbol"):
        """Render a timeline to SVG.

        This is the main interface of SvgRenderer.

        Args:
            timeline_name: Timeline name (with entities unescaped)
            frame_idx: Frame to render
            width: Width of resulting SVG
            height: Height of resulting SVG
            type: Whether this timeline is a "symbol" or "scene"

        Returns:
            SVG ElementTree
        """
        defs, body = self._render_timeline(
            timeline_name, frame_idx, ColorEffect(), False, type
        )

        svg = ET.Element(
            "svg",
            {
                # `xmlns:xlink` is automatically added if any element uses
                # `xlink:href`. We don't explicitly use the SVG namespace,
                # though, so we need to add it here.
                "xmlns": "http://www.w3.org/2000/svg",
                "version": "1.1",
                "preserveAspectRatio": "none",
                "x": "0px",
                "y": "0px",
                "width": f"{width}px",
                "height": f"{height}px",
                "viewBox": f"0 0 {width} {height}",
            },
        )

        defs_element = ET.SubElement(svg, "defs")
        defs_element.extend(defs.values())
        svg.extend(body)

        return ET.ElementTree(svg)

    def _render_timeline(
        self, name, frame_idx, color_effect, inside_mask, type="symbol"
    ):
        """Render a timeline.

        Args:
            name: Timeline name (with entities unescaped)
            frame_idx: Frame to render
            color_effect: Color effect to apply to filled shapes. Ignored if
                          `inside_mask` is True
            inside_mask: If True, all filled shapes are set to #FFFFFF so that
                         the resulting mask is fully transparent
            type: Whether this timeline is a "symbol" or "scene"

        Returns a tuple:
            defs: {element id: SVG element that goes in <defs>}
            body: List of SVG elements
        """
        id_name = re.sub(r"[^A-Za-z0-9]", "_", name)

        id = f"{id_name}_{frame_idx}"
        if inside_mask:
            id = "Mask_" + id

        defs = {}
        body = []

        layers = self.xfl_reader.get_timeline(name, type).layers

        mask_is_active = False
        # Process layers from back to front
        for layer_idx, layer in reversed(list(enumerate(layers))):
            layer_type = layer.get("layerType")
            if layer_type == "guide":
                continue
            elif layer_type == "mask":
                # End the mask we started earlier
                mask_is_active = False
                continue
            elif layer_type in ["folder", None]:
                pass
            else:
                warnings.warn(f"Unknown layer type: {layer_type}")

            # Check if we need to start a mask
            if not mask_is_active:
                mask_idx = layer.get(self.xfl_reader.MASK_START)
                if mask_idx is not None:
                    mask_is_active = True
                    # If a masked layer is transformed, then its mask must be
                    # transformed by the same <g>. Otherwise, the mask will not
                    # line up with the masked layer. This means that <mask>s
                    # must be defined in the SVG body, within the same <g>s as
                    # the layers they mask.
                    # Now, suppose we had two instances of the same symbol
                    # under different <g>s. If <mask> IDs were based on `id`,
                    # then these symbols' <mask>s would have the same ID,
                    # despite the masks being transformed by different <g>s.
                    # This might produce an incorrect rendering.
                    # So, <mask> IDs must reflect the current transformation.
                    # We could track this through every method of SvgRenderer,
                    # but it's easier to use a globally unique ID. This does
                    # prevent us from applying lru_cache() to every method of
                    # SvgRenderer, though.
                    mask_id = "Mask_" + str(self.mask_num)
                    self.mask_num += 1

                    d, b = self._render_layer(
                        layers[mask_idx],
                        frame_idx,
                        # Animate appends "_MASK" for direct descendants of the
                        # mask layer.
                        f"Mask_{id}_{layer_idx}_MASK",
                        color_effect,
                        inside_mask=True,
                    )
                    defs.update(d)
                    mask = ET.Element("mask", {"id": mask_id})
                    mask.extend(b)
                    body.append(mask)

                    # Apply mask. We will end it by setting `mask_is_active` to
                    # False when we hit the actual mask layer.
                    g = ET.Element("g", {"mask": f"url(#{mask_id})"})
                    body.append(g)

            d, b = self._render_layer(
                layer, frame_idx, f"{id}_Layer{layer_idx}", color_effect, inside_mask
            )
            defs.update(d)
            if mask_is_active:
                # Add elements into the <mask> element
                body[-1].extend(b)
            else:
                # Add elements into the body list
                body.extend(b)

        return defs, body

    def _render_layer(self, layer, frame_idx, id, color_effect, inside_mask):
        """Render a layer.

        Args:
            layer: <DOMLayer> element
            frame_idx: Frame to render
            id: ID for this layer
            color_effect: Color effect to apply to filled shapes. Ignored if
                          `inside_mask` is True
            inside_mask: If True, all filled shapes are set to #FFFFFF so that
                         the resulting mask is fully transparent

        Returns a tuple:
            defs: {element id: SVG element that goes in <defs>}
            body: List of SVG elements
        """
        # A <DOMLayer> is either empty or has a <frames> child
        if len(layer) == 0:
            return {}, []

        frame = None

        # The <frames> element contains <DOMFrame> children
        for f in layer[0]:
            index = int(f.get("index"))
            duration = int(f.get("duration", 1))
            if index <= frame_idx < index + duration:
                frame = f
                frame_offset = frame_idx - index
                break
        if frame is None:
            return {}, []

        # TODO: Handle tweens here. Requires comparing successive keyframes,
        # calculating the transformation based on the frame offset, and
        # applying it.

        defs = {}
        body = []

        # <elements> is usually the last child of <DOMFrame>, but not always.
        # Using .find() would be cleaner, but it's much slower than this
        elements_idx = -1
        while not frame[elements_idx].tag.endswith("elements"):
            elements_idx -= 1

        for element_idx, element in enumerate(frame[elements_idx]):
            d, b = self._render_element(
                element, f"{id}_{element_idx}", frame_offset, color_effect, inside_mask
            )
            defs.update(d)
            body.extend(b)

        return defs, body

    def _render_element(self, element, id, frame_offset, color_effect, inside_mask):
        """Render an element.

        Args:
            element: A child of the <elements> element
            id: ID for this element
            frame_offset: Frame offset from the start of the current keyframe
            color_effect: Color effect to apply to filled shapes. Ignored if
                          `inside_mask` is True
            inside_mask: If True, all filled shapes are set to #FFFFFF so that
                         the resulting mask is fully transparent

        Returns a tuple:
            defs: {element id: SVG element that goes in <defs>}
            body: List of SVG elements
        """
        if element.tag.endswith("DOMSymbolInstance"):
            if element.get("symbolType") != "graphic":
                # TODO: Some symbols have no symbol type and `blendMode="layer"` instead?
                warnings.warn(f"Unknown symbol type: {element.get('symbolType')}")

            # If present, the <color> element will be the last child
            if not inside_mask and element[-1].tag.endswith("color"):
                # A <color> element contains 1 <Color> child
                color_effect = color_effect @ ColorEffect.from_xfl(element[-1][0])
            defs, body = self._render_timeline(
                unescape_entities(element.get("libraryItemName")),
                self._get_loop_frame(element, frame_offset),
                color_effect,
                inside_mask,
            )

        elif element.tag.endswith("DOMShape"):
            defs, body = self._handle_domshape(element, id, color_effect, inside_mask)
        elif element.tag.endswith("DOMGroup"):
            # The last child of a <DOMGroup> is always <members>
            children = element[-1]
            defs = {}
            body = []
            for child_idx, child in enumerate(children):
                d, b = self._render_element(
                    child,
                    # Only add "MEMBER" to the ID when necessary (i.e. there
                    # are at least two children). Animate usually follows this
                    # rule, but sometimes it doesn't, and I don't know why.
                    f"{id}_MEMBER_{child_idx}" if len(children) > 1 else id,
                    frame_offset,
                    color_effect,
                    inside_mask,
                )
                defs.update(d)
                body.extend(b)
        else:
            tag = element.tag.split("}")[1]
            warnings.warn(f"Unknown element type: {tag}")
            return {}, []

        # For some reason, DOMGroup matrices are redundant and must be ignored.
        if not element.tag.endswith("DOMGroup"):
            matrix = get_matrix(element)
            if matrix is not None:
                matrix = ", ".join(matrix)
                transform = ET.Element("g", {"transform": f"matrix({matrix})"})
                transform.extend(body)
                body = [transform]

        return defs, body

    def _get_loop_frame(self, instance, frame_offset):
        """Calculate the frame to use for a symbol instance given the offset.

        Args:
            instance: <DOMSymbolInstance> element
            frame_offset: Frame offset from the start of the current keyframe

        Returns:
            Frame index
        """
        first_frame = int(instance.get("firstFrame", 0))
        if "lastFrame" in instance:
            last_frame = int(instance.get("lastFrame"))
        else:
            last_frame = self.xfl_reader.get_timeline(
                unescape_entities(instance.get("libraryItemName"))
            ).last_frame

        loop_type = instance.get("loop", "single frame")

        if loop_type == "single frame":
            return first_frame
        elif loop_type == "loop":
            loop_length = last_frame - first_frame + 1
            if loop_length <= 0:
                raise Exception(
                    f"Invalid loop length: {loop_length} "
                    f"(first frame: {first_frame}, last frame: {last_frame})"
                )
            return first_frame + (frame_offset % loop_length)
        elif loop_type == "play once":
            return min(first_frame + frame_offset, last_frame)
        else:
            raise Exception(f"Unknown loop type: {loop_type}")


# For efficiency, SvgRenderer wraps this function in an lru_cache(). I'm not
# sure how XML elements are hashed, but it doesn't matter because `id` ensures
# uniqueness. Also, we use the same XML elements over and over, so their hashes
# do not change.
def _handle_domshape(domshape, id, color_effect, inside_mask):
    """Convert an XFL <DOMShape> to SVG, given a mask status and color effect.

    Args:
        domshape: <DOMShape> element
        id: ID for this element
        color_effect: Color effect to apply to filled shapes. Ignored if
                      `inside_mask` is True
        inside_mask: If True, all filled shapes are set to #FFFFFF so that
                     the resulting mask is fully transparent

    Returns a tuple:
        defs: {element id: SVG element that goes in <defs>}
        body: List of SVG elements
    """
    defs = {}
    body = []

    fill_g, stroke_g, extra_defs = xfl_domshape_to_svg(domshape, inside_mask)
    defs.update(extra_defs)

    if fill_g is not None:
        fill_id = f"{id}_FILL"
        fill_g.set("id", fill_id)
        defs[fill_id] = fill_g

        fill_use = ET.Element("use", {HREF: "#" + fill_id})
        if not inside_mask and not color_effect.is_identity():
            defs[color_effect.id] = color_effect.to_svg()
            fill_use.set("filter", f"url(#{color_effect.id})")
        body.append(fill_use)

    if stroke_g is not None:
        stroke_id = f"{id}_STROKE"
        stroke_g.set("id", stroke_id)
        defs[stroke_id] = stroke_g

        body.append(ET.Element("use", {HREF: "#" + stroke_id}))

    return defs, body
