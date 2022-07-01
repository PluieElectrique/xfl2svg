"""Utility functions."""

import re
import warnings

CHARACTER_ENTITY_REFERENCE = re.compile(r"&#(\d+)")
IDENTITY_MATRIX = ["1", "0", "0", "1", "0", "0"]


def unescape_entities(s):
    """Unescape XML character entity references."""
    return CHARACTER_ENTITY_REFERENCE.sub(lambda m: chr(int(m[1])), s)


def check_known_attrib(element, known):
    """Ensure that an XML element doesn't have unknown attributes."""
    if not set(element.keys()) <= known:
        unknown = set(element.keys()) - known
        # Remove namespace, if present
        tag = re.match(r"(\{[^}]+\})?(.*)", element.tag)[2]
        warnings.warn(
            f"Unknown <{tag}> attributes: {element.attrib}\n"
            f"  Known keys:   {known}\n"
            f"  Unknown keys: {unknown}"
        )


def get_matrix(element):
    """Get a transformation matrix from an XFL element."""
    # If this element has a <matrix>, it will be the first child. This is
    # faster than find() and also prevents us getting the matrix of a different
    # element (e.g. a <LinearGradient> nested inside a <DOMShape>).
    if len(element) and element[0].tag.endswith("matrix"):
        # element -> <matrix> -> <Matrix>
        matrix = element[0][0]
        # Column-major order, the same as in SVG
        #   a c tx
        #   b d ty
        #   0 0  1
        return [
            matrix.get("a") or "1",
            matrix.get("b") or "0",
            matrix.get("c") or "0",
            matrix.get("d") or "1",
            matrix.get("tx") or "0",
            matrix.get("ty") or "0",
        ]

    return IDENTITY_MATRIX
