"""Convert the XFL <DOMShape> element to SVG <path> elements."""

import warnings
import xml.etree.ElementTree as ET
from numpy import expand_dims

from xfl2svg.shape.edge import xfl_edge_to_shapes
from xfl2svg.shape.style import parse_fill_style, parse_stroke_style
from xfl2svg.util import merge_bounding_boxes


# This function converts point lists into the SVG path format.
def point_list_to_path_format(point_list: list) -> str:
    """Convert a point list into the SVG path format."""
    point_iter = iter(point_list)
    path = ["M", next(point_iter)]
    points = []
    last_command = "M"

    try:
        while True:
            point = next(point_iter)
            command = "Q" if isinstance(point, tuple) else "L"
            # SVG lets us omit the command letter if we use the same command
            # multiple times in a row.
            if command != last_command:
                path.append(command)
                last_command = command

            if command == "Q":
                # Append control point and destination point
                path.append(point[0])
                path.append(next(point_iter))
            else:
                path.append(point)
    except StopIteration:
        if point_list[0] == point_list[-1]:
            # Animate adds a "closepath" (Z) command to every filled shape and
            # closed stroke. For shapes, it makes no difference, but for closed
            # strokes, it turns two overlapping line caps into a bevel, miter,
            # or round join, which does make a difference.
            # TODO: It is likely that closed strokes can be broken into
            # segments and spread across multiple Edge elements, which would
            # require a function like point_lists_to_shapes(), but for strokes.
            # For now, though, adding "Z" to any stroke that is already closed
            # seems good enough.
            # path.append("Z")
            pass
        return " ".join(path)


def expanding_bounding_box(box, width):
    return (
        box[0] - width / 2,
        box[1] - width / 2,
        box[2] + width / 2,
        box[3] + width / 2,
    )


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
        fill_styles[style.get("index")] = style

    stroke_styles = {}
    for style in domshape.iterfind(".//{*}StrokeStyle"):
        stroke_styles[style.get("index")] = style

    shapes, strokes = xfl_edge_to_shapes(
        domshape.find("{*}edges"), fill_styles, stroke_styles
    )
    bounding_box = None

    filled_paths = []
    for fill_id, fill_data in shapes.items():
        point_lists, curr_bounding_box = fill_data
        style = fill_styles[fill_id]
        if mask:
            # Set the fill to white so that the mask is fully transparent.
            fill_style = {"fill": "#FFFFFF", "stroke": "none"}
        else:
            fill_style, fill_extra = parse_fill_style(style[0], curr_bounding_box)
            extra_defs.update(fill_extra)

        path = ET.Element("path", fill_style)
        path.set("d", " ".join(point_list_to_path_format(pl) for pl in point_lists))
        filled_paths.append(path)
        bounding_box = merge_bounding_boxes(bounding_box, curr_bounding_box)

    stroked_paths = []
    for stroke_id, stroke_data in strokes.items():
        point_lists, curr_bounding_box = stroke_data
        style = stroke_styles[stroke_id]
        # TODO: Figure out how strokes are supposed to behave in masks
        if mask:
            warnings.warn("Strokes in masks are not supported")
        stroke_style, stroke_extra = parse_stroke_style(style[0], curr_bounding_box)
        extra_defs.update(stroke_extra)

        stroke_width = float(stroke_style.get("stroke-width", 1))
        curr_bounding_box = expanding_bounding_box(curr_bounding_box, stroke_width)

        stroke = ET.Element("path", stroke_style)
        stroke.set("d", " ".join(point_list_to_path_format(pl) for pl in point_lists))
        stroked_paths.append(stroke)
        bounding_box = merge_bounding_boxes(bounding_box, curr_bounding_box)

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

    return fill_g, stroke_g, extra_defs, bounding_box
