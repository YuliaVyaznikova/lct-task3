import pytest

from planner.core.text import plural


@pytest.mark.parametrize(
    ("count", "word"),
    [(1, "заявка"), (2, "заявки"), (4, "заявки"), (5, "заявок"), (11, "заявок"),
     (12, "заявок"), (14, "заявок"), (21, "заявка"), (22, "заявки"), (111, "заявок")],
)
def test_plural_agrees_with_the_number(count, word):
    assert plural(count, "заявка", "заявки", "заявок") == word
