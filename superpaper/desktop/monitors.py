"""A monitor as the desktop reports it, and the screeninfo query that Linux, Windows and unknown platforms share."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Monitor:
    """One monitor in pixels, with its position from the desktop's top-left corner; sizes in mm are None when unknown."""

    name: str | None
    x: int
    y: int
    width: int
    height: int
    width_mm: int | None
    height_mm: int | None


def detect_monitors() -> list[Monitor]:
    """The monitors screeninfo finds; imported only here, as it loads display libraries."""
    # https://github.com/rr-/screeninfo
    from screeninfo import get_monitors

    return [Monitor(m.name, m.x, m.y, m.width, m.height, m.width_mm, m.height_mm) for m in get_monitors()]
