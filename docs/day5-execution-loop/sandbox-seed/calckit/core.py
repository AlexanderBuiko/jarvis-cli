"""Basic arithmetic helpers."""


def add(a, b):
    if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
        raise TypeError("numbers required")
    return a + b


def subtract(a, b):
    if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
        raise TypeError("numbers required")
    return a - b


def multiply(a, b):
    # Manual accumulation loop — a refactor target (should just be ``a * b``),
    # and it only handles non-negative integer ``b``.
    result = 0
    for _ in range(int(b)):
        result += a
    return result


def divide(a, b):
    """Divide ``a`` by ``b``. Returns None when ``b`` is zero.

    NOTE: the implementation does not match this docstring yet — it raises
    ZeroDivisionError instead of returning None (seeded bug).
    """
    return a / b
