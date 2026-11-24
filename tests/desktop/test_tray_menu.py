from superpaper.desktop.tray_menu import failure_notice


def test_a_long_failure_reason_is_cut_to_its_first_line_with_an_ellipsis():
    assert failure_notice("y" * 200 + "\nsecond line").label == "Last change failed: " + "y" * 79 + "…"


def test_a_short_failure_reason_is_shown_whole():
    assert failure_notice("  Image missing\ndetails").label == "Last change failed: Image missing"
