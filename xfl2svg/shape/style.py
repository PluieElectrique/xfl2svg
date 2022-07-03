"""Convert XFL fill and stroke styles to SVG attributes."""

import xml.etree.ElementTree as ET
import warnings

from xfl2svg.shape.gradient import LinearGradient, RadialGradient
from xfl2svg.util import check_known_attrib


def xml_str(element):
    return ET.tostring(element, encoding="unicode")


def update(d, keys, values):
    """Update the dict `d` with non-None values."""
    for k, v in zip(keys, values):
        if v is not None:
            d[k] = v


def parse_solid_color(style):
    """Parse an XFL <SolidColor> element.

    Returns a tuple:
        color: Hex color code
        alpha: Optional alpha value
    """
    check_known_attrib(style, {"color", "alpha"})
    return style.get("color", "#000000"), style.get("alpha")


def parse_fill_style(style):
    """Parse an XFL <FillStyle> element.

    Returns a tuple:
        attrib: Dict of SVG style attributes
        extra_defs: Dict of {element_id: SVG element to put in <defs>}
    """
    attrib = {"stroke": "none"}
    extra_defs = {}

    if style.tag.endswith("SolidColor"):
        update(attrib, ("fill", "fill-opacity"), parse_solid_color(style))
    elif style.tag.endswith("LinearGradient"):
        gradient = LinearGradient.from_xfl(style)
        attrib["fill"] = f"url(#{gradient.id})"
        extra_defs[gradient.id] = gradient.to_svg()
    elif style.tag.endswith("RadialGradient"):
        # TODO: Support RadialGradient
        gradient = RadialGradient.from_xfl(style)
        attrib["fill"] = f"url(#{gradient.id})"
        extra_defs[gradient.id] = gradient.to_svg()
    else:
        warnings.warn(f"Unknown fill style: {xml_str(style)}")

    return attrib, extra_defs


def parse_stroke_style(style):
    """Parse an XFL <StrokeStyle> element.

    Returns a dict of SVG style attributes.
    """
    if not style.tag.endswith("SolidStroke"):
        warnings.warn(f"Unknown stroke style: {xml_str(style)}")
        return {"fill": "none"}

    check_known_attrib(style, {"scaleMode", "weight", "joints", "miterLimit", "caps"})
    if style.get("scaleMode") != "normal":
        warnings.warn(f"Unknown `scaleMode` value: {style.get('scaleMode')}")
        return {"fill": "none"}

    cap = style.get("caps", "round")
    if cap == "none":
        cap = "butt"

    attrib = {
        "stroke-linecap": cap,
        "stroke-width": style.get("weight", "1"),
        "stroke-linejoin": style.get("joints", "round"),
        "fill": "none",
    }

    fill = style[0][0]
    if fill.tag.endswith("RadialGradient"):
        # TODO: Support RadialGradient
        warnings.warn("RadialGradient is not supported yet")
        return attrib
    elif not fill.tag.endswith("SolidColor"):
        warnings.warn(f"Unknown stroke fill: {xml_str(fill)}")
        return attrib

    update(attrib, ("stroke", "stroke-opacity"), parse_solid_color(fill))
    if attrib["stroke-linejoin"] == "miter":
        # If the XFL does not specify a miterLimit, Animate's SVG exporter will
        # set stroke-miterlimit to 3. This seems to match what Flash does [*].
        # But, in some cases, a limit of 5 better matches Animate's PNG render.
        # So, that's what we use.
        #
        # [*]: https://github.com/ruffle-rs/ruffle/blob/d3becd9/core/src/avm1/globals/movie_clip.rs#L283-L290
        attrib["stroke-miterlimit"] = style.get("miterLimit", "5")

    return attrib
