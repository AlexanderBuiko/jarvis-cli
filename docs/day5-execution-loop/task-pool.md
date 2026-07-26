# Day-5 task pool — calckit sandbox

18 tasks for the execution loop. One task per list item; the `[tag]` picks the
kind. Each has a clear done/not-done criterion so success is objective.

The loop runs these top-to-bottom against the `calckit` sandbox. Ordered roughly
easy → harder so the "how many in a row" streak is meaningful.

- [bug] In `calckit/core.py`, `divide(a, b)` must return `None` when `b` is 0 (its docstring already promises this) instead of raising `ZeroDivisionError`. Done = `divide(1, 0)` returns `None` and `divide(6, 2)` still returns `3.0`.
- [bug] In `calckit/stats.py`, `mean([])` must return `0.0` instead of raising `ZeroDivisionError`. Done = `mean([])` is `0.0` and `mean([2, 4])` is `3.0`.
- [bug] In `calckit/textutils.py`, `slugify` must lowercase its output. Done = `slugify("Hello World")` returns `"hello-world"`.
- [bug] In `calckit/stats.py`, `median` returns the wrong value for even-length inputs; it must average the two middle values. Done = `median([1, 2, 3, 4])` returns `2.5` and `median([1, 2, 3])` still returns `2`.
- [feature] Add `power(base, exp)` to `calckit/core.py` returning `base ** exp`. Done = `power(2, 10)` returns `1024`.
- [feature] Add `clamp(value, low, high)` to `calckit/core.py` that returns `value` bounded to the `[low, high]` range. Done = `clamp(5, 0, 3)` returns `3` and `clamp(-1, 0, 3)` returns `0`.
- [feature] Add `mode(values)` to `calckit/stats.py` returning the most common value. Done = `mode([1, 1, 2])` returns `1`.
- [feature] Add `truncate(text, n)` to `calckit/textutils.py` that shortens `text` to at most `n` characters, appending `"…"` when it was cut. Done = `truncate("abcdef", 4)` returns `"abc…"` and `truncate("ab", 4)` returns `"ab"`.
- [refactor] In `calckit/core.py`, replace the manual accumulation loop in `multiply` with the `*` operator, keeping the same signature. Done = `multiply(3, 4)` returns `12` and the loop is gone.
- [refactor] In `calckit/stats.py`, rename the unclear `_c` local in `median` to a meaningful name. Done = `_c` no longer appears and `median` still works.
- [refactor] In `calckit/core.py`, extract the repeated `isinstance` number check from `add` and `subtract` into one private helper `_require_numbers` and call it from both. Done = both functions still raise `TypeError` on non-numbers and the check exists in one place.
- [test] Add tests for `calckit/core.py` `add` and `subtract` covering a negative-number case. Done = new tests exist and pass.
- [test] Add a test asserting `calckit/core.py` `divide` returns `None` for a zero denominator. Done = the test exists and passes.
- [test] Add a test for `calckit/stats.py` `mean` covering the empty-list case. Done = the test exists and passes.
- [docs] Add a one-line module docstring to `calckit/textutils.py` describing its purpose. Done = the file starts with a docstring.
- [docs] Add a `## Usage` section to the sandbox `README.md` showing `add` and `mean` in a code block. Done = the section exists with a runnable example.
- [docs] Declare the public API by adding an `__all__` list to `calckit/__init__.py` naming the exported functions. Done = `__all__` exists and lists at least `add`, `subtract`, `mean`.
- [research] Report which `calckit` functions currently have no test coverage. This is analysis only — produce a written list, do not change any code. Done = a list naming the untested functions.
