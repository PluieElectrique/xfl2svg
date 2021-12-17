"""Convert the XFL <DOMShape> element to SVG <path> elements."""

import xml.etree.ElementTree as ET

from xfl2svg.shape.edge import xfl_edge_to_svg_path
from xfl2svg.shape.style import parse_fill_style, parse_stroke_style


def xfl_domshape_to_svg(domshape, mask=False):
    """Convert the XFL <DOMShape> element to SVG <path> elements.

    Args:
        domshape: An XFL <DOMShape> element
        mask: If True, all fill colors will be set to #FFFFFF. This ensures
              that the resulting mask is fully transparent.

    Returns a 3-tuple of:
        SVG <g> element containing filled <path>s
        SVG <g> element containing stroked <path>s
        dict of extra elements to put in <defs> (e.g. filters and gradients)
    """
    extra_defs = {}

    fill_styles = {}
    for style in domshape.iterfind(".//{*}FillStyle"):
        index = style.get("index")
        if mask:
            # Set the fill to white so that the mask is fully transparent.
            fill_styles[index] = {"fill": "#FFFFFF", "stroke": "none"}
        else:
            fill_style, fill_extra = parse_fill_style(style[0])
            fill_styles[index] = fill_style
            extra_defs.update(fill_extra)

    stroke_styles = {}
    for style in domshape.iterfind(".//{*}StrokeStyle"):
        assert not mask, "Don't know how to handle strokes inside masks"
        stroke_styles[style.get("index")] = parse_stroke_style(style[0])

    filled_paths, stroked_paths = xfl_edge_to_svg_path(
        domshape.find("{*}edges"), fill_styles, stroke_styles
    )

    fill_g = None
    if filled_paths:
        fill_g = ET.Element("g")
        fill_g.extend(filled_paths)

    stroke_g = None
    if stroked_paths:
        # Animate directly dumps all stroked <path>s into <defs>, but it's
        # cleaner to wrap them in a <g> like it does for filled paths.
        stroke_g = ET.Element("g")
        stroke_g.extend(stroked_paths)

    return fill_g, stroke_g, extra_defs
