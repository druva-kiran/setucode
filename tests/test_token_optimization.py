"""Unit tests for Token & Context Optimization Tricks."""
from __future__ import annotations

from pathlib import Path
import pytest

from app.context.dedup import ContextDeduplicator
from app.tools.read_file import make_read_file
from app.tools.search_files import make_search_files


def test_partial_file_reading(tmp_path: Path):
    """read_file allows reading targeted line ranges instead of entire large files."""
    code_file = tmp_path / "large_file.py"
    lines = [f"line_{i} = {i}" for i in range(1, 101)]
    code_file.write_text("\n".join(lines), encoding="utf-8")

    reader = make_read_file(tmp_path)

    # Read slice from line 10 to line 15
    res = reader({"path": "large_file.py", "start_line": 10, "end_line": 15})
    assert not res.is_error
    output = res.output
    assert "Lines 10-15 of 100" in output
    assert "10: line_10 = 10" in output
    assert "15: line_15 = 15" in output
    assert "line_1 = 1" not in output
    assert "line_50 = 50" not in output


def test_partial_reading_out_of_range(tmp_path: Path):
    """Reading beyond EOF returns a clean descriptive note without raising exceptions."""
    code_file = tmp_path / "short.py"
    code_file.write_text("a = 1\nb = 2\n", encoding="utf-8")

    reader = make_read_file(tmp_path)
    res = reader({"path": "short.py", "start_line": 10, "end_line": 20})
    assert not res.is_error
    assert "out of range" in res.output


def test_search_files_locates_code(tmp_path: Path):
    """search_files finds targeted lines without dumping the entire file tree."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "auth.py").write_text("def authenticate_user(): pass\ndef logout(): pass\n")
    (tmp_path / "src" / "db.py").write_text("def connect_db(): pass\n")

    searcher = make_search_files(tmp_path)
    res = searcher({"query": "authenticate_user"})
    assert not res.is_error
    assert "auth.py:1: def authenticate_user(): pass" in res.output
    assert "db.py" not in res.output


def test_context_deduplicator():
    """Deduplicator detects duplicate file or context blocks."""
    dedup = ContextDeduplicator()
    text = "class UserProfile:\n    name: str\n"

    assert dedup.is_duplicate(text, namespace="file_context") is False
    assert dedup.is_duplicate(text, namespace="file_context") is True
