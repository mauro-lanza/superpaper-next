from superpaper.geometry.perspective import Disabled
from superpaper.profiles.form import ProfileForm


def blank(**changes):
    """A profile form for a profile named Work with every other field at its neutral value."""
    values = {
        "name": "Work",
        "span_mode": "single",
        "slideshow": False,
        "delay_minutes": "",
        "sort_label": None,
        "hotkey_enabled": False,
        "hotkey": "",
        "offsets_applied": False,
        "offsets": ("0,0", "0,0"),
        "spangroups_enabled": False,
        "spangroup_choices": (0, 0),
        "perspective": Disabled(),
        "zoom_pct": 100,
        "pan_pct": (0, 0),
        "per_target_sources": False,
        "sources": (("", "/pics"),),
    }
    return ProfileForm(**{**values, **changes})
