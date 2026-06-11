"""Tests for FileLoader path-traversal containment (security)."""

from __future__ import annotations

import sys

import pytest

import starlark
from starlark.eval import EvalError
from starlark.eval.loader import FileLoader


def _loader(tmp_path, *search_subdirs):
    bases = [str(tmp_path / s) for s in search_subdirs] if search_subdirs else [str(tmp_path)]
    return FileLoader(exec_file=starlark.exec_file, search_paths=bases)


def test_legitimate_relative_load_succeeds(tmp_path):
    (tmp_path / "lib.star").write_text("VALUE = 42\n", encoding="utf-8")
    loader = _loader(tmp_path)
    module = loader("lib.star")
    assert module.globals["VALUE"] == 42


def test_legitimate_relative_load_in_subdir_succeeds(tmp_path):
    sub = tmp_path / "lib"
    sub.mkdir()
    (sub / "dep.star").write_text("X = 1\n", encoding="utf-8")
    loader = _loader(tmp_path)
    module = loader("lib/dep.star")
    assert module.globals["X"] == 1


def test_parent_traversal_rejected(tmp_path):
    base = tmp_path / "base"
    base.mkdir()
    (tmp_path / "secret.star").write_text("PASSWORD = 'hunter2'\n", encoding="utf-8")
    loader = FileLoader(exec_file=starlark.exec_file, search_paths=[str(base)])
    with pytest.raises(EvalError, match="outside the loader's search paths"):
        loader("../secret.star")


def test_absolute_path_rejected(tmp_path):
    loader = _loader(tmp_path)
    with pytest.raises(EvalError, match="outside the loader's search paths"):
        loader("/etc/hostname")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-absolute form")
def test_windows_absolute_path_rejected(tmp_path):
    loader = _loader(tmp_path)
    with pytest.raises(EvalError, match="outside the loader's search paths"):
        loader(r"C:\Windows\System32\drivers\etc\hosts")


@pytest.mark.skipif(not hasattr(__import__("os"), "symlink"), reason="symlinks unsupported")
def test_symlink_escape_rejected(tmp_path):
    base = tmp_path / "base"
    base.mkdir()
    outside = tmp_path / "outside.star"
    outside.write_text("SECRET = 'leak'\n", encoding="utf-8")
    link = base / "link.star"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not permitted in this environment")
    loader = FileLoader(exec_file=starlark.exec_file, search_paths=[str(base)])
    with pytest.raises(EvalError, match="outside the loader's search paths"):
        loader("link.star")


def test_rejection_message_leaks_no_path_or_content(tmp_path):
    base = tmp_path / "base"
    base.mkdir()
    secret = tmp_path / "secret.star"
    secret.write_text("PASSWORD = 'hunter2'\n", encoding="utf-8")
    loader = FileLoader(exec_file=starlark.exec_file, search_paths=[str(base)])
    with pytest.raises(EvalError) as excinfo:
        loader("../secret.star")
    message = str(excinfo.value)
    assert str(secret.resolve()) not in message
    assert str(tmp_path) not in message
    assert "hunter2" not in message
    assert "PASSWORD" not in message


def test_contained_but_missing_keeps_file_not_found(tmp_path):
    loader = _loader(tmp_path)
    with pytest.raises(EvalError, match="file not found"):
        loader("does_not_exist.star")


def test_load_statement_traversal_rejected(tmp_path):
    base = tmp_path / "base"
    base.mkdir()
    (tmp_path / "secret.star").write_text("password = 'hunter2'\n", encoding="utf-8")
    loader = FileLoader(exec_file=starlark.exec_file, search_paths=[str(base)])
    with pytest.raises(EvalError, match="outside the loader's search paths"):
        starlark.exec_file('load("../secret.star", "password")\n', loader=loader)
