"""What to ask the user when leaving the editor with unsaved changes, and what their answer means."""

from collections.abc import Callable
from enum import Enum
from typing import assert_never


class Answer(Enum):
    SAVE = "Save"
    DISCARD = "Discard"
    CANCEL = "Cancel"


class ApplyAnswer(Enum):
    SAVE_DISPLAYS = "Save displays and apply"
    USE_SAVED_DISPLAYS = "Apply with saved displays"
    CANCEL = "Cancel"


def unsaved_message(*, profile: bool, displays: bool) -> str | None:
    """The question to ask for what has unsaved changes; None if nothing has."""
    if profile and displays:
        return "The profile and the display layout have unsaved changes."
    if profile:
        return "The profile has unsaved changes."
    if displays:
        return "The display layout has unsaved changes."
    return None


def apply_answer(answer: Answer, *, can_save: bool) -> ApplyAnswer:
    """What Apply's question about unsaved displays was answered, from the button pressed:
    Save, Discard and Cancel, or, without ``can_save``, only a first button (use the saved
    displays) and a second one (cancel)."""
    match answer:
        case Answer.SAVE:
            return ApplyAnswer.SAVE_DISPLAYS if can_save else ApplyAnswer.USE_SAVED_DISPLAYS
        case Answer.DISCARD if can_save:
            return ApplyAnswer.USE_SAVED_DISPLAYS
        case _:
            return ApplyAnswer.CANCEL


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
        case _:
            assert_never(answer)
