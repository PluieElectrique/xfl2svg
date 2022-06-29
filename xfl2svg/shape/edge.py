"""Convert XFL edges to SVG paths.

If you just want to convert, use `xfl_edge_to_svg_path()`. If you're interested
in how everything works, read on.
"""

# Read these links first, as there is no official documentation for the XFL
# edge format:
#
#   * https://github.com/SasQ/SavageFlask/blob/master/doc/FLA.txt
#   * https://stackoverflow.com/a/4077709
#
# Overview:
#
#    In Animate, graphic symbols are made of filled shapes and stroked paths.
#    Both are defined by their outline, which Animate breaks into pieces. We'll
#    call such a piece a "segment", rather than an "edge", to avoid confusion
#    with the edge format.
#
#    A segment may be part of up to two shapes: one on its left and one on its
#    right. This is determined by the presence of the "fillStyle0" (left) and
#    "fillStyle1" (right) attributes, which specify the style for the shape on
#    that side.
#
#    A segment may be part of up to one stroked path. This is determined by the
#    presence of the "strokeStyle" attribute.
#
#    So, to extract graphic symbols from XFL, we first convert the edge format
#    into segments (represented as point lists, see below). Each <Edge> element
#    produces one or more segments, each of which inherits the <Edge>'s
#    "fillStyle0", "fillStyle1", and "strokeStyle" attributes.
#
#    Then, for filled shapes, we join segments of the same fill style by
#    matching their start/end points. The fill styles must be for the same
#    side. For stroked paths, we just collect all segments of the same style.
#
#    Finally, we convert segments to the SVG path format, put them in an SVG
#    <path> element, and assign fill/stroke style attributes to the <path>.


from collections import defaultdict
import re
from typing import Dict, Iterator, List, Tuple
import xml.etree.ElementTree as ET


# The XFL edge format can be described as follows:
#
#   start  : moveto (moveto | lineto | quadto)*
#   moveto : "!" NUMBER ~ 2 select?             // Move to this point
#   lineto : ("|" | "/") NUMBER ~ 2             // Line from current point to here
#   quadto : ("[" | "]") NUMBER ~ 4             // Quad Bézier (control point, dest)
#   select : /S[1-7]/                           // Only used by Animate
#   NUMBER : /-?\d+(\.\d+)?/                    // Decimal number
#          | /#[A-Z0-9]{1,6}\.[A-Z0-9]{1,2}/    // Signed, 32-bit number in hex
#   %import common.WS                           // Ignore whitespace
#   %ignore WS
#
# Notes:
#  * This grammar is written for use with Lark, a Python parsing toolkit. See:
#      * Project page:  https://github.com/lark-parser/lark
#      * Try it online: https://www.lark-parser.org/ide/
#  * The cubic commands are omitted:
#      * They only appear in the "cubics" attribute and not in "edges"
#      * They're just hints for Animate and aren't needed for conversion to SVG
#  * "select" is also just a hint for Animate, but it appears in "edges", so we
#    include it for completeness.
#
# Anyhow, this language can actually be tokenized with a single regex, which is
# faster than using Lark:

EDGE_TOKENIZER = re.compile(
    r"""
[!|/[\]]                |   # Move to, line to, quad to
(?<!S)-?\d+(?:\.\d+)?   |   # Decimal number
\#[A-Z0-9]+\.[A-Z0-9]+      # Hex number
""",
    re.VERBOSE,
)

# Notes:
#   * Whitespace is automatically ignored, as we only match what we want.
#   * The negative lookbehind assertion (?<!S) is needed to avoid matching the
#     digit in select commands as a number.


# After tokenizing, we need to parse numbers:


def parse_number(num: str) -> float:
    """Parse an XFL edge format number."""
    if num[0] == "#":
        # Signed, 32-bit fixed-point number in hex
        parts = num[1:].split(".")
        # Pad to 8 digits
        hex_num = "{:>06}{:<02}".format(*parts)
        num = int.from_bytes(bytes.fromhex(hex_num), "big", signed=True)
        # Account for hex scaling and Animate's 20x scaling (twips)
        return (num / 256) / 20
    else:
        # Decimal number. Account for Animate's 20x scaling (twips)
        return float(num) / 20


# Notes:
#   * The <path>s produced by Animate's SVG export sometimes have slightly
#     different numbers (e.g. flooring or subtracting 1 from decimals before
#     dividing by 20). It's not clear how this works or if it's even intended,
#     so I gave up trying to replicate it.
#   * Animate prints round numbers as integers (e.g. "1" instead of "1.0"), but
#     it makes no difference for SVG.


# Now, we can parse the edge format. To join segments into shapes, though, we
# will need a way to reverse segments (for normalizing them so that the filled
# shape is always on the left). That is, if we have a segment like:
#
#                C
#              /   \
#             |     |
#    A ----- B       D ----- E
#
# which is represented by:
#
#    moveto A, lineto B, quadto C D, lineto E
#
# We should be able to reverse it and get:
#
#    moveto E, lineto D, quadto C B, lineto A
#
# The "point list" format (couldn't think of a better name) meets this
# requirement. The segment above would be represented as:
#
#    [A, B, (C,), D, E]
#
# The first point is always the destination of a "move to" command. Subsequent
# points are the destinations of "line to" commands. If a point is in a tuple
# like `(C,)`, then it's the control point of a quadratic Bézier curve, and the
# following point is the destination of the curve. (Tuples are just an easy way
# to mark points--there's nothing particular about the choice.)
#
# With this format, we can see that reversing the list gives us the same
# segment, but in reverse:
#
#    [E, D, (C,), B, A]
#
# In practice, each point is represented as a coordinate string, so the actual
# point list might look like:
#
#   ["0 0", "10 0", ("20 10",), "30 0", "40 0"]
#
# This next function converts the XFL edge format into point lists. Since each
# "edges" attribute can contain multiple segments, but each point list only
# represents one segment, this function can yield multiple point lists.


def edge_format_to_point_lists(edges: str) -> Iterator[list]:
    """Convert the XFL edge format to point lists.

    Args:
        edges: The "edges" attribute of an XFL <Edge> element

    Yields:
        One point list for each segment parsed out of `edges`
    """
    tokens = iter(EDGE_TOKENIZER.findall(edges))

    def next_point():
        return f"{parse_number(next(tokens))} {parse_number(next(tokens))}"

    assert next(tokens) == "!", "Edge format must start with moveto (!) command"

    prev_point = next_point()
    point_list = [prev_point]

    try:
        while True:
            command = next(tokens)
            curr_point = next_point()

            if command == "!":
                # Move to
                if curr_point != prev_point:
                    # If a move command doesn't change the current point, we
                    # ignore it. Otherwise, a new segment is starting, so we
                    # must yield the current point list and begin a new one.
                    yield point_list
                    point_list = [curr_point]
                    prev_point = curr_point
            elif command in "|/":
                # Line to
                point_list.append(curr_point)
                prev_point = curr_point
            else:
                # Quad to. The control point (curr_point) is marked by putting
                # it in a tuple.
                point_list.append((curr_point,))
                prev_point = next_point()
                point_list.append(prev_point)
    except StopIteration:
        yield point_list


# The next function converts point lists into the SVG path format.


def point_list_to_path_format(point_list: list) -> str:
    """Convert a point list into the SVG path format."""
    point_iter = iter(point_list)
    path = ["M", next(point_iter)]
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
            path.append("Z")
        return " ".join(path)


# Finally, we can convert XFL <Edge> elements into SVG <path> elements. The
# algorithm works as follows:

#   First, convert the "edges" attributes into segments. Then:
#
#   For filled shapes:
#     * For a given <Edge>, process each of its segments:
#         * If the <Edge> has "fillStyle0", associate the fill style ID
#           ("index" in XFL) with the segment.
#         * If the <Edge> has "fillStyle1", associate the ID with the segment,
#           reversed. This way, the fill of the shape is always to the left of
#           the segment (arbitrary choice--the opposite works too).
#     * For each fill style ID, consider its segments:
#         * Pick an unused segment. If it's already closed (start point equals
#           end point), convert it to the SVG path format.
#         * Otherwise, if it's open, randomly append segments (making sure to
#           match start and end points) until:
#             1. The segment is closed. Convert and start over with a new,
#                unused segment.
#             2. The segment intersects with itself (i.e. the current end point
#                equals the end point of a previous segment). Backtrack.
#             3. There are no more valid segments. Backtrack.
#         * When all segments have been joined into shapes and converted,
#           concatenate the path strings and put them in *one* SVG <path>
#           element. (This ensures that holes work correctly.) Finally, look up
#           the fill attributes from the ID and assign them to the <path>.
#
#   For stroked paths:
#     * Pair up segments with their stroke style IDs. There is only one
#       "strokeStyle" attribute, so we don't need to reverse any segments.
#     * For each stroke style ID, convert its segments into the SVG path
#       format. Concatenate all path strings and put them in an SVG <path>
#       element. Look up the stroke attributes and assign them to the <path>.
#
#
# This algorithm is split across the next two functions:
#   * `point_lists_to_shapes()` joins point lists into filled shapes.
#   * `xfl_edge_to_svg_path()` does everything else.
#
#
# Assumptions:
#   * Segments never cross. So, we only need to join them at their ends.
#   * For filled shapes, there's only one way to join segments such that no
#     segment is left out. So, we don't need to worry about making the wrong
#     decision when there are multiple segments to pick from.
#
# Notes:
#   * For stroked paths, Animate joins together segments by their start/end
#     points. But, this isn't necessary: when converting to the SVG path
#     format, each segment starts with a "move to" command, so they can be
#     concatenated in any order.
#   * For filled shapes, there is usually only one choice for the next point
#     list. The only time there are multiple choices is when multiple shapes
#     share a point:
#
#               +<-----+
#      Shape 1  |      ^
#               v      |
#               +----->o<-----+
#                      |      ^  Shape 2
#                      v      |
#                      +----->+


def point_lists_to_shapes(point_lists: List[Tuple[list, str]]) -> Dict[str, List[list]]:
    """Join point lists and fill style IDs into shapes.

    Args:
        point_lists: [(point_list, fill style ID), ...]

    Returns:
        {fill style ID: [shape point list, ...], ...}
    """
    # {fill style ID: {origin point: [point list, ...], ...}, ...}
    graph = defaultdict(lambda: defaultdict(list))

    # {fill style ID: [shape point list, ...], ...}
    shapes = defaultdict(list)

    # Add open point lists into `graph`
    for point_list, fill_id in point_lists:
        if point_list[0] == point_list[-1]:
            # This point list is already a closed shape
            shapes[fill_id].append(point_list)
        else:
            graph[fill_id][point_list[0]].append(point_list)

    def walk(curr_point, used_points, origin, fill_graph):
        """Recursively join point lists into shapes."""
        for i in range(len(fill_graph[curr_point])):
            next_point_list = fill_graph[curr_point][i]
            next_point = next_point_list[-1]

            if next_point == origin:
                # Found a cycle. This shape is now closed
                del fill_graph[curr_point][i]
                return next_point_list
            elif next_point not in used_points:
                # Try this point list
                used_points.add(next_point)
                shape = walk(next_point, used_points, origin, fill_graph)
                if shape is None:
                    # Backtrack
                    used_points.remove(next_point)
                else:
                    del fill_graph[curr_point][i]
                    # Concat this point list, removing the redundant start move
                    return next_point_list + shape[1:]

    # For each fill style ID, pick a random origin and join point lists into
    # shapes with walk() until we're done.
    for fill_id, fill_graph in graph.items():
        for origin in fill_graph.keys():
            while fill_graph[origin]:
                point_list = fill_graph[origin].pop()
                curr_point = point_list[-1]

                shape = walk(curr_point, {origin, curr_point}, origin, fill_graph)
                assert shape is not None, "Failed to build shape"

                shapes[fill_id].append(point_list + shape[1:])

    return shapes


def xfl_edge_to_svg_path(
    edges_element: ET.Element,
    fill_styles: Dict[str, dict],
    stroke_styles: Dict[str, dict],
) -> Tuple[List[ET.Element], List[ET.Element]]:
    """Convert the XFL <edges> element into SVG <path> elements.

    Args:
        edges_element: The <edges> element of a <DOMShape>
        fill_styles: {fill style ID: style attribute dict, ...}
        stroke_styles: {stroke style ID: style attribute dict, ...}

    Returns a tuple of lists, each containing <path> elements:
        ([filled path, ...], [stroked path, ...])
    """
    fill_edges = []
    stroke_paths = defaultdict(list)

    # Ignore the "cubics" attribute, as it's only used by Animate
    for edge in edges_element.iterfind(".//{*}Edge[@edges]"):
        edge_format = edge.get("edges")
        fill_id_left = edge.get("fillStyle0")
        fill_id_right = edge.get("fillStyle1")
        stroke_id = edge.get("strokeStyle")

        for point_list in edge_format_to_point_lists(edge_format):
            # Reverse point lists so that the fill is always to the left
            if fill_id_left is not None:
                fill_edges.append((point_list, fill_id_left))
            if fill_id_right is not None:
                fill_edges.append((list(reversed(point_list)), fill_id_right))

            # Convert right away since we don't need to join anything into shapes
            if stroke_id is not None:
                stroke_paths[stroke_id].append(point_list_to_path_format(point_list))

    filled_paths = []
    shapes = point_lists_to_shapes(fill_edges)
    for fill_id, point_lists in shapes.items():
        path = ET.Element("path", fill_styles[fill_id])
        path.set("d", " ".join(point_list_to_path_format(pl) for pl in point_lists))
        filled_paths.append(path)

    stroked_paths = []
    for stroke_id, path_data in stroke_paths.items():
        stroke = ET.Element("path", stroke_styles[stroke_id])
        stroke.set("d", " ".join(path_data))
        stroked_paths.append(stroke)

    return filled_paths, stroked_paths
