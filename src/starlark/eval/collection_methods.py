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
    if not hasattr(items, "__iter__"):
        raise EvalError(
            f"parameter 'items' got value of type '{starlark_type(items)}', want 'iterable'"
        )
    self.extend(items)


def l_insert(self: StarlarkList, index: int, value: Any) -> None:
    if not _is_int(index):
        raise EvalError("insert() index must be int")
    self.insert(index, value)


def l_pop(self: StarlarkList, index: Any = -1) -> Any:
    if not _is_int(index):
        raise EvalError("pop() index must be int")
    n = len(self)
    if n == 0:
        raise EvalError("pop from empty list")
    i = index + n if index < 0 else index
    if i < 0 or i >= n:
        raise EvalError(f"index out of range (index is {index}, but sequence has {n} elements)")
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


def _to_set_collection(o: Any):
    """Iterate `o` as a hashable-element collection. Used by set.update etc."""
    if isinstance(o, str) or not hasattr(o, "__iter__"):
        raise EvalError(
            f"got value of type '{starlark_type(o)}', want a collection of hashable elements"
        )
    return iter(o)


def st_update(self: StarlarkSet, *others) -> None:
    """Add every element of `others` to the set in place."""
    for o in others:
        for x in _to_set_collection(o):
            check_hashable(x)
            self.add(x)


def st_pop(self: StarlarkSet) -> Any:
    """Remove and return the first inserted element. Mirrors starlark-go."""
    self.mutability.check("set")
    if len(self) == 0:
        raise EvalError("set is empty")
    first = next(iter(self))
    self.discard(first)
    return first


def st_union(self: StarlarkSet, *others) -> StarlarkSet:
    from .builtins import _mut

    out = StarlarkSet(list(self), _mut())
    for o in others:
        for x in _to_set_collection(o):
            check_hashable(x)
            out._data[x] = None
    return out


def st_intersection(self: StarlarkSet, *others) -> StarlarkSet:
    from .builtins import _mut

    other_sets = [set(_to_set_collection(o)) for o in others]
    keep: list = []
    for x in self:
        if all(x in o for o in other_sets):
            keep.append(x)
    return StarlarkSet(keep, _mut())


def st_difference(self: StarlarkSet, *others) -> StarlarkSet:
    from .builtins import _mut

    other_sets = [set(_to_set_collection(o)) for o in others]
    keep: list = []
    for x in self:
        if not any(x in o for o in other_sets):
            keep.append(x)
    return StarlarkSet(keep, _mut())


def st_symmetric_difference(self: StarlarkSet, *others) -> StarlarkSet:
    if len(others) != 1:
        raise EvalError("set.symmetric_difference() accepts no more than 1 positional argument")
    other = others[0]
    from .builtins import _mut

    other_list = list(_to_set_collection(other))
    other_set = set(other_list)
    keep: list = []
    for x in self:
        if x not in other_set:
            keep.append(x)
    for x in other_list:
        check_hashable(x)
        if x not in self:
            keep.append(x)
    return StarlarkSet(keep, _mut())


def st_intersection_update(self: StarlarkSet, *others) -> None:
    self.mutability.check("set")
    other_sets = [set(_to_set_collection(o)) for o in others]
    keep = [x for x in self if all(x in o for o in other_sets)]
    self._data.clear()
    for x in keep:
        self._data[x] = None


def st_difference_update(self: StarlarkSet, *others) -> None:
    self.mutability.check("set")
    drop = set()
    for o in others:
        drop.update(_to_set_collection(o))
    keep = [x for x in self if x not in drop]
    self._data.clear()
    for x in keep:
        self._data[x] = None


def st_symmetric_difference_update(self: StarlarkSet, *others) -> None:
    if len(others) != 1:
        raise EvalError(
            "set.symmetric_difference_update() accepts no more than 1 positional argument"
        )
    other = others[0]
    self.mutability.check("set")
    other_list = list(_to_set_collection(other))
    for x in other_list:
        check_hashable(x)
    other_set = set(other_list)
    keep = [x for x in self if x not in other_set]
    for x in other_list:
        if x not in self:
            keep.append(x)
    self._data.clear()
    for x in keep:
        self._data[x] = None


def st_isdisjoint(self: StarlarkSet, *others) -> bool:
    if len(others) != 1:
        raise EvalError("set.isdisjoint() accepts no more than 1 positional argument")
    return not any(x in self for x in _to_set_collection(others[0]))


def st_issubset(self: StarlarkSet, *others) -> bool:
    if len(others) != 1:
        raise EvalError("set.issubset() accepts no more than 1 positional argument")
    other_set = set(_to_set_collection(others[0]))
    return all(x in other_set for x in self)


def st_issuperset(self: StarlarkSet, *others) -> bool:
    if len(others) != 1:
        raise EvalError("set.issuperset() accepts no more than 1 positional argument")
    return all(x in self for x in _to_set_collection(others[0]))


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
        ("update", st_update),
        ("pop", st_pop),
        ("union", st_union),
        ("intersection", st_intersection),
        ("intersection_update", st_intersection_update),
        ("difference", st_difference),
        ("difference_update", st_difference_update),
        ("symmetric_difference", st_symmetric_difference),
        ("symmetric_difference_update", st_symmetric_difference_update),
        ("isdisjoint", st_isdisjoint),
        ("issubset", st_issubset),
        ("issuperset", st_issuperset),
    ]
    for name, fn in set_pairs:
        register_set_method(name, fn)


register_all()


__all__ = ["register_all"]
