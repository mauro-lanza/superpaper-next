from superpaper.desktop.tray_menu import failure_notice


def test_a_long_failure_reason_is_cut_short():
    assert len(failure_notice("y" * 200).label) < 120
