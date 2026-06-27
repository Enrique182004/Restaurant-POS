def test_get_week_bounds_midweek_date(app_module):
    start, end = app_module.get_week_bounds("2026-06-26")  # Friday
    assert start == "2026-06-22"
    assert end == "2026-06-28"


def test_get_week_bounds_on_monday(app_module):
    start, end = app_module.get_week_bounds("2026-06-22")
    assert start == "2026-06-22"
    assert end == "2026-06-28"


def test_get_week_bounds_on_sunday(app_module):
    start, end = app_module.get_week_bounds("2026-06-28")
    assert start == "2026-06-22"
    assert end == "2026-06-28"
