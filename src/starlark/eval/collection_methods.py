"""Methods on lists, dicts, sets, and tuples."""

from __future__ import annotations

from typing import Any

from .errors import EvalError
from .methods import register_dict_method, register_list_method, register_set_method
from .values import (
    Dict,
    StarlarkList,
    StarlarkSet,
    check_hashable,
    starlark_type,
)


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


# ---------------------------------------------------------------- list


def l_append(self: StarlarkList, value: Any) -> None:
    self.append(value)


def l_extend(self: StarlarkList, items: Any) -> None:
    if isinstance(items, str) or not hasattr(items, "__iter__"):
        raise EvalError(f"extend() requires an iterable, not {starlark_type(items)}")
    self.extend(items)


def l_insert(self: StarlarkList, index: int, value: Any) -> None:
    if not _is_int(index):
        raise EvalError("insert() index must be int")
    self.insert(index, value)


def l_pop(self: StarlarkList, index: Any = -1) -> Any:
    if not _is_int(index):
        raise EvalError("pop() index must be int")
    if len(self) == 0:
        raise EvalError("pop from empty list")
    return self.pop(index)


def l_remove(self: StarlarkList, value: Any) -> None:
    self.remove_value(value)


def l_clear(self: StarlarkList) -> None:
    self.clear()


def l_index(self: StarlarkList, value: Any, start: Any = 0, end: Any = None) -> int:
    if not _is_int(start):
        raise EvalError("index() start must be int")
    if end is not None and not _is_int(end):
        raise EvalError("index() end must be int")
    return self.index_of(value, start, end)


def l_count(self: StarlarkList, value: Any) -> int:
    return self.count_of(value)


# ---------------------------------------------------------------- dict


def d_get(self: Dict, key: Any, default: Any = None) -> Any:
    return self.get(key, default)


def d_keys(self: Dict) -> StarlarkList:
    from .builtins import _mut
    return StarlarkList(self.keys(), _mut())


def d_values(self: Dict) -> StarlarkList:
    from .builtins import _mut
    return StarlarkList(self.values(), _mut())


def d_items(self: Dict) -> StarlarkList:
    from .builtins import _mut
    return StarlarkList(self.items(), _mut())


def d_setdefault(self: Dict, key: Any, default: Any = None) -> Any:
    return self.setdefault(key, default)


def d_update(self: Dict, *args, **kwargs) -> None:
    if len(args) > 1:
        raise EvalError("update() takes at most 1 positional argument")
    if args:
        a = args[0]
        if isinstance(a, Dict) or isinstance(a, dict):
            self.update(a)
        else:
            for pair in a:
                items = list(pair)
                if len(items) != 2:
                    raise EvalError("update() pair must have 2 elements")
                check_hashable(items[0])
                self[items[0]] = items[1]
    for k, v in kwargs.items():
        self[k] = v


def d_pop(self: Dict, key: Any, *default) -> Any:
    return self.pop(key, *default)


def d_popitem(self: Dict) -> tuple:
    return self.popitem()


def d_clear(self: Dict) -> None:
    self.clear()


# ---------------------------------------------------------------- set


def st_add(self: StarlarkSet, value: Any) -> None:
    self.add(value)


def st_discard(self: StarlarkSet, value: Any) -> None:
    self.discard(value)


def st_remove(self: StarlarkSet, value: Any) -> None:
    self.remove_value(value)


def st_clear(self: StarlarkSet) -> None:
    self.clear()


def st_union(self: StarlarkSet, *others) -> StarlarkSet:
    from .builtins import _mut
    out = StarlarkSet(list(self), _mut())
    for o in others:
        for x in o:
            out._data[x] = None
    return out


def st_intersection(self: StarlarkSet, *others) -> StarlarkSet:
    from .builtins import _mut
    keep: list = []
    for x in self:
        if all(x in o for o in others):
            keep.append(x)
    return StarlarkSet(keep, _mut())


def st_difference(self: StarlarkSet, *others) -> StarlarkSet:
    from .builtins import _mut
    keep: list = []
    for x in self:
        if not any(x in o for o in others):
            keep.append(x)
    return StarlarkSet(keep, _mut())


def st_issubset(self: StarlarkSet, other: Any) -> bool:
    return all(x in other for x in self)


def st_issuperset(self: StarlarkSet, other: Any) -> bool:
    return all(x in self for x in other)


# ---------------------------------------------------------------- registration


def register_all() -> None:
    list_pairs = [
        ("append", l_append),
        ("extend", l_extend),
        ("insert", l_insert),
        ("pop", l_pop),
        ("remove", l_remove),
        ("clear", l_clear),
        ("index", l_index),
        ("count", l_count),
    ]
    for name, fn in list_pairs:
        register_list_method(name, fn)

    dict_pairs = [
        ("get", d_get),
        ("keys", d_keys),
        ("values", d_values),
        ("items", d_items),
        ("setdefault", d_setdefault),
        ("update", d_update),
        ("pop", d_pop),
        ("popitem", d_popitem),
        ("clear", d_clear),
    ]
    for name, fn in dict_pairs:
        register_dict_method(name, fn)

    set_pairs = [
        ("add", st_add),
        ("discard", st_discard),
        ("remove", st_remove),
        ("clear", st_clear),
        ("union", st_union),
        ("intersection", st_intersection),
        ("difference", st_difference),
        ("issubset", st_issubset),
        ("issuperset", st_issuperset),
    ]
    for name, fn in set_pairs:
        register_set_method(name, fn)


register_all()


__all__ = ["register_all"]
