import pytest

from superpaper.unsaved_changes import Answer, may_proceed, unsaved_message


@pytest.mark.parametrize(
    ("profile", "displays", "expected"),
    [
        (False, False, None),
        (True, False, "The profile has unsaved changes."),
        (False, True, "The display layout has unsaved changes."),
        (True, True, "The profile and the display layout have unsaved changes."),
    ],
)
def test_the_question_names_what_is_unsaved(profile, displays, expected):
    assert unsaved_message(profile=profile, displays=displays) == expected


@pytest.mark.parametrize(
    ("answer", "saved", "expected"),
    [
        (Answer.SAVE, True, True),
        (Answer.SAVE, False, False),
        (Answer.DISCARD, False, True),
        (Answer.CANCEL, True, False),
    ],
)
def test_only_a_successful_save_or_a_discard_goes_on(answer, saved, expected):
    calls = []

    def save():
        calls.append("save")
        return saved

    assert may_proceed(answer, save) is expected
    assert calls == (["save"] if answer is Answer.SAVE else [])
