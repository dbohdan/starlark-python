import pytest

import starlark


def test_import():
    assert starlark.__version__ == "0.0.0"


@pytest.mark.xfail(reason="evaluator not implemented yet", strict=True)
def test_eval_one_plus_one():
    assert starlark.eval("1 + 1") == 2
