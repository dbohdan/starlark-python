import starlark


def test_eval_one_plus_one():
    assert starlark.eval("1 + 1") == 2
