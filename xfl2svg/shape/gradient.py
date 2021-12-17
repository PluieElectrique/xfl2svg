"""Convert XFL gradients to SVG."""

# TODO: Support RadialGradient


from dataclasses import dataclass
import xml.etree.ElementTree as ET

from xfl2svg.util import check_known_attrib, get_matrix


@dataclass(frozen=True)
class LinearGradient:
    start: tuple[float, float]
    end: tuple[float, float]
    stops: tuple[tuple[float, str, str], ...]
    spread_method: str

    @classmethod
    def from_xfl(cls, element):
        """Create a LinearGradient from the XFL <LinearGradient> element.

        The start and end points of the gradient are defined by the <Matrix> M:

                   0%             100%
            start >---------o---------> end
           (M @ s)       midpoint     (M @ e)
                         (tx, ty)

        where

              |a c tx|        |-16384/20|        | 16384/20|
          M = |b d ty|    s = |    0    |    e = |    0    |
              |0 0  1|        |    1    |        |    1    |

        The magic constant of 16384/20 is weird, but it's likely related to how
        edge coordinates are precise to the nearest 1/20 (disregarding decimal
        coordinates, which are more precise).
        """

        a, b, _, _, tx, ty = map(float, get_matrix(element))
        start = (a * -16384/20 + tx, b * -16384/20 + ty)  # fmt: skip
        end   = (a *  16384/20 + tx, b *  16384/20 + ty)  # fmt: skip

        stops = []
        for entry in element.iterfind("{*}GradientEntry"):
            check_known_attrib(entry, {"ratio", "color", "alpha"})
            stops.append(
                (
                    float(entry.get("ratio")) * 100,
                    entry.get("color", "#000000"),
                    entry.get("alpha"),
                )
            )

        check_known_attrib(element, {"spreadMethod"})
        spread_method = element.get("spreadMethod", "pad")

        return cls(start, end, tuple(stops), spread_method)

    def to_svg(self):
        """Create an SVG <linearGradient> element from a LinearGradient."""
        element = ET.Element(
            "linearGradient",
            {
                "id": self.id,
                "gradientUnits": "userSpaceOnUse",
                "x1": str(self.start[0]),
                "y1": str(self.start[1]),
                "x2": str(self.end[0]),
                "y2": str(self.end[1]),
                "spreadMethod": self.spread_method,
            },
        )
        for offset, color, alpha in self.stops:
            attrib = {"offset": f"{offset}%", "stop-color": color}
            if alpha is not None:
                attrib["stop-opacity"] = alpha
            ET.SubElement(element, "stop", attrib)
        return element

    @property
    def id(self):
        """Unique ID used to dedup SVG elements in <defs>."""
        return f"Gradient_{hash(self) & 0xFFFF_FFFF:08x}"
