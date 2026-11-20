"""What to ask the user when leaving the editor with unsaved changes, and what their answer means."""

from collections.abc import Callable
from enum import Enum


class Answer(Enum):
    SAVE = "Save"
    DISCARD = "Discard"
    CANCEL = "Cancel"


def unsaved_message(*, profile: bool, displays: bool) -> str | None:
    """The question to ask for what has unsaved changes; None if nothing has."""
    if profile and displays:
        what = "The profile and the display layout have"
    elif profile:
        what = "The profile has"
    elif displays:
        what = "The display layout has"
    else:
        return None
    return f"{what} unsaved changes."


def may_proceed(answer: Answer, save: Callable[[], bool]) -> bool:
    """Whether to go on with what the user was doing: after saving, which must succeed,
    or after discarding, but not after cancelling."""
    match answer:
        case Answer.SAVE:
            return save()
        case Answer.DISCARD:
            return True
        case Answer.CANCEL:
            return False
