"""Simple descriptive statistics."""


def mean(values):
    # Seeded bug: no guard for an empty sequence -> ZeroDivisionError.
    return sum(values) / len(values)


def median(values):
    s = sorted(values)
    n = len(s)
    # Seeded bug: wrong for even-length inputs (should average the two middle values).
    _c = s[n // 2]
    return _c
