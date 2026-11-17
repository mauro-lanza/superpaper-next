import pytest

from superpaper.perspective import check_new_perspective_name, lengths_to_ppi_norm


@pytest.mark.parametrize("name", ["default", "DEFAULT", "Default", "disabled", "Disabled", "None", "none", "NONE"])
def test_reserved_perspective_names_are_rejected(name):
    with pytest.raises(ValueError, match="reserved"):
        check_new_perspective_name(name)


@pytest.mark.parametrize("name", ["desk", "defaults", "none of them", "My default"])
def test_other_perspective_names_are_accepted(name):
    check_new_perspective_name(name)


def test_lengths_convert_millimetres_to_pixels_and_keep_angles():
    viewer, swivels, tilts = lengths_to_ppi_norm(
        163.0,
        [0.0, -30.5, 500.0],
        [(1, 12.0, 7.25, -3.0)],
        [(-4.5, 12.0, 40.0)],
    )

    assert viewer == [0.0, -195.72834645669292, 3208.6614173228345]
    assert swivels == [(1, 12.0, 46.525590551181104, -19.251968503937007)]
    assert tilts == [(-4.5, 77.00787401574803, 256.6929133858268)]


def test_no_displays_rows_give_empty_lists():
    assert lengths_to_ppi_norm(96.0, [0.0, 0.0, 1.0], [], [])[1:] == ([], [])
