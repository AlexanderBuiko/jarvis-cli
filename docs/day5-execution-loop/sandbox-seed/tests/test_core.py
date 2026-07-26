"""Starter tests. Most of calckit is deliberately untested — that is the point."""

from calckit.core import add, subtract


def test_add():
    assert add(2, 3) == 5


def test_subtract():
    assert subtract(5, 2) == 3
