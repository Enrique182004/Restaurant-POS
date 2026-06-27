from werkzeug.datastructures import MultiDict


def test_parse_scheduled_days_dedupes_and_sorts(app_module):
    form = MultiDict([("days", "3"), ("days", "1"), ("days", "1")])
    assert app_module.parse_scheduled_days(form) == "1,3"


def test_parse_scheduled_days_ignores_invalid_values(app_module):
    form = MultiDict([("days", "7"), ("days", "-1"), ("days", "abc"), ("days", "2")])
    assert app_module.parse_scheduled_days(form) == "2"


def test_parse_scheduled_days_empty_when_nothing_selected(app_module):
    form = MultiDict([])
    assert app_module.parse_scheduled_days(form) == ""


def test_parse_scheduled_days_ignores_non_ascii_digit_characters(app_module):
    form = MultiDict([("days", "²"), ("days", "1")])  # superscript two: isdigit()==True but int() raises ValueError
    assert app_module.parse_scheduled_days(form) == "1"
