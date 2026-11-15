"""Unit conversion. The single internal length unit is the METRE."""
from typing import Literal

LengthUnit = Literal["m", "cm", "ft", "in"]

TO_METRES: dict[str, float] = {"m": 1.0, "cm": 0.01, "ft": 0.3048, "in": 0.0254}


def to_m(value: float, unit: str) -> float:
    if unit not in TO_METRES:
        raise ValueError(f"Unsupported length unit '{unit}'. Use one of {sorted(TO_METRES)}.")
    if value is None:
        raise ValueError("Length value is required")
    return float(value) * TO_METRES[unit]


def from_m(value_m: float, unit: str) -> float:
    if unit not in TO_METRES:
        raise ValueError(f"Unsupported length unit '{unit}'.")
    return float(value_m) / TO_METRES[unit]


def area_from_m2(value_m2: float, unit: str) -> float:
    return value_m2 / (TO_METRES[unit] ** 2)
