"""Convert XFL color effects to SVG."""

from dataclasses import dataclass
import re
from typing import Optional
import xml.etree.ElementTree as ET
import warnings


HEX_COLOR = re.compile(r"#[A-Za-z0-9]{6}")


@dataclass(frozen=True)
class ColorEffect:
    # `None` is an identity effect
    effect: Optional[tuple[tuple, tuple]] = None

    @classmethod
    def from_xfl(cls, element):
        """Create a ColorEffect from an XFL <Color> element."""
        attrib = element.attrib

        # Alpha: multiply alpha by a constant
        if "alphaMultiplier" in attrib:
            multiplier = (1, 1, 1, float(attrib["alphaMultiplier"]))
            offset = (0, 0, 0, 0)

        # Brightness: linearly interpolate towards black or white
        elif "brightness" in attrib:
            brightness = float(attrib["brightness"])
            if brightness < 0:
                # Linearly interpolate towards black
                multiplier = (1 + brightness, 1 + brightness, 1 + brightness, 1)
                offset = (0, 0, 0, 0)
            else:
                # Linearly interpolate towards white
                multiplier = (1 - brightness, 1 - brightness, 1 - brightness, 1)
                offset = (brightness, brightness, brightness, 0)

        # Tint: linearly interpolate between the original color and a tint color
        elif "tintMultiplier" in attrib or "tintColor" in attrib:
            # color * (1 - tint_multiplier) + tint_color * tint_multiplier
            tint_multiplier = float(attrib.get("tintMultiplier", 0))
            multiplier = (
                1 - tint_multiplier,
                1 - tint_multiplier,
                1 - tint_multiplier,
                1,
            )

            tint_color = attrib.get("tintColor", "#000000")
            if not HEX_COLOR.fullmatch(tint_color):
                warnings.warn(f"Color isn't in hex format: {tint_color}")
                return cls()

            offset = (
                tint_multiplier * int(tint_color[1:3], 16) / 255,
                tint_multiplier * int(tint_color[3:5], 16) / 255,
                tint_multiplier * int(tint_color[5:7], 16) / 255,
                0,
            )

        # Advanced: multiply and offset each channel
        elif set(attrib.keys()) & {
            "redMultiplier",
            "greenMultiplier",
            "blueMultiplier",
            "alphaMultiplier",
            "redOffset",
            "greenOffset",
            "blueOffset",
            "alphaOffset",
        }:
            # Multipliers are in [-1, 1]
            multiplier = (
                float(attrib.get("redMultiplier", 1)),
                float(attrib.get("greenMultiplier", 1)),
                float(attrib.get("blueMultiplier", 1)),
                float(attrib.get("alphaMultiplier", 1)),
            )
            # Offsets are in [-255, 255]
            offset = (
                float(attrib.get("redOffset", 0)) / 255,
                float(attrib.get("greenOffset", 0)) / 255,
                float(attrib.get("blueOffset", 0)) / 255,
                float(attrib.get("alphaOffset", 0)) / 255,
            )

        else:
            warnings.warn(f"Unknown color effect: {attrib}")
            return cls()

        return cls((multiplier, offset))

    def to_svg(self):
        """Create an SVG <filter> element from a ColorEffect."""
        # This assert ensures that we avoid creating unnecessary <filter>s.
        # Callers should ensure that is_identity() == False before converting.
        assert self.effect is not None

        multiplier, offset = self.effect
        # fmt: off
        matrix = (
            "{0} 0 0 0 {4} "
            "0 {1} 0 0 {5} "
            "0 0 {2} 0 {6} "
            "0 0 0 {3} {7}"
        ).format(*multiplier, *offset)
        # fmt: on

        element = ET.Element(
            "filter",
            {
                "id": self.id,
                "x": "-20%",
                "y": "-20%",
                "width": "140%",
                "height": "140%",
                "color-interpolation-filters": "sRGB",
            },
        )
        ET.SubElement(
            element,
            "feColorMatrix",
            {
                "in": "SourceGraphic",
                "type": "matrix",
                "values": matrix,
                # This is useless since we don't chain together filter
                # primitives, but Animate adds it, so we might as well.
                "result": "result1",
            },
        )
        return element

    def __matmul__(self, other):
        if type(other) is not ColorEffect:
            raise TypeError(
                f"expected type ColorEffect, but operand has type {type(other)}"
            )

        # ColorEffects are immutable, so it's fine to return an existing instance.
        if self.effect is None:
            return other
        elif other.effect is None:
            return self
        else:
            # other is applied first, then self:
            #     self @ (other @ X)
            #   = self_m * (other_m * X + other_o) + self_o
            #   = (self_m * other_m) * X + (self_m * other_o + self_o)
            self_m, self_o = self.effect
            other_m, other_o = other.effect
            return ColorEffect(
                (
                    (
                        self_m[0] * other_m[0],
                        self_m[1] * other_m[1],
                        self_m[2] * other_m[2],
                        self_m[3] * other_m[3],
                    ),
                    (
                        self_m[0] * other_o[0] + self_o[0],
                        self_m[1] * other_o[1] + self_o[1],
                        self_m[2] * other_o[2] + self_o[2],
                        self_m[3] * other_o[3] + self_o[3],
                    ),
                )
            )

    def is_identity(self):
        """Returns True if this effect does nothing."""
        return self.effect is None or self.effect == ((1, 1, 1, 1), (0, 0, 0, 0))

    @property
    def id(self):
        """Unique ID used to dedup SVG elements in <defs>."""
        return f"Filter_{hash(self) & 0xFFFF_FFFF:08x}"
