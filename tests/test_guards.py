"""Each guard on small fixtures: what it flags, what it passes, and what it prints."""
import hashlib
import re
import textwrap

from guards import __main__ as cli
from guards import allow, ci_coverage, hidden_defaults, history_words, private_ids


def _write(root, files):
    for name, text in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(text))


def test_private_ids_flag_a_hashed_token_and_a_joined_fragment_without_printing_them(tmp_path):
    word = "zzsecretzz"
    digests = {hashlib.sha256(word.encode()).hexdigest()}
    patterns = [re.compile("".join(("quux", "-", r"\d+")))]
    _write(tmp_path, {"a.txt": f"fine\nsee {word.upper()}-thing here\n", "b.txt": "ok\nquux-12\n", "c.txt": "quux\n"})
    found = private_ids.check(tmp_path, digests=digests, patterns=patterns)
    assert [(f.path, f.line, f.reason) for f in sorted(found)] == [("a.txt", 2, "forbidden token"),
                                                                    ("b.txt", 2, "forbidden pattern 0")]
    assert not any(word in str(f).lower() or "quux" in str(f) for f in found)


def test_ci_coverage_is_per_file(tmp_path):
    _write(tmp_path, {"tests/test_a.py": "", "tests/test_b.py": "", "tests/sub/test_c.py": "", "tests/sub/test_d.py": "",
                      ".github/workflows/tests.yml": "run: pytest tests/test_a.py tests/sub -q\n"})
    assert [f.path for f in ci_coverage.check(tmp_path)] == ["tests/test_b.py"]


def test_ci_coverage_testpaths_bare_pytest_globs_and_ignores(tmp_path):
    _write(tmp_path, {"pyproject.toml": '[tool.pytest.ini_options]\ntestpaths = ["tests"]\n',
                      "tests/test_a.py": "", "tests/test_b.py": "", "other/test_c.py": "",
                      ".github/workflows/tests.yml": 'run: pytest -q -m "not slow" --ignore=tests/test_b.py\n'})
    assert [f.path for f in ci_coverage.check(tmp_path)] == ["other/test_c.py", "tests/test_b.py"]
    (tmp_path / ".github/workflows/tests.yml").write_text(
        "run: pytest -q --ignore=tests/test_b.py \\\n  other tests/test_a.py\nrun: python -m pytest tests/test_[b]*.py\n")
    assert ci_coverage.check(tmp_path) == []
    (tmp_path / ".github/workflows/tests.yml").write_text('P=$(ls tests/test_[a-b].py)\nrun: pytest $P -q\n')
    assert [f.path for f in ci_coverage.check(tmp_path)] == ["other/test_c.py"]


def test_home_paths_are_forbidden_by_user_not_by_prefix(tmp_path):
    user = hashlib.sha256(b"zzperson").hexdigest()
    _write(tmp_path, {"a.txt": "ENV PATH=/home/runner/bin\nx = '/Users/ZZPerson/work'\n"})
    found = private_ids.check(tmp_path, users={user})
    assert [(f.line, f.reason) for f in found] == [(2, "forbidden home path")]
    assert "zzperson" not in str(found[0]).lower()


def test_hidden_defaults_flags_numbers_standing_in_for_missing_inputs():
    src = textwrap.dedent("""
        a = x or 0.5
        b = cfg.get("T2", 1e-3)
        c = getattr(o, "d", 2)
        d = x or -3
        e = cfg.get("name", "s")
        f = x or y
        g = cfg.get("k")
        h = x or None
        i = x or True
        j = x or [0.5]
        """)
    assert [f.line for f in hidden_defaults.scan_source(src, "m.py")] == [2, 3, 4, 5]


def test_history_wording_flags_history_not_ordinary_prose():
    src = textwrap.dedent('''
        """Module doc."""
        def f():
            """It used to return a tuple.

            Now it returns a dict. The old path is gone. This is used to compute x (no history).
            """
        def g():
            """Call it twice; a was replaced value, previously cached, no longer holds."""
        ''')
    lines = [f.line for f in history_words.scan_source(src, "m.py")]
    assert sorted(set(lines)) == [4, 6, 9]


def test_allow_list_accepts_stated_cases_only_and_new_ones_fail(tmp_path):
    _write(tmp_path, {"pkg/__init__.py": "", "pkg/m.py": "a = x or 0.5\n"})
    assert [f.path for f in cli.run("hidden-defaults", tmp_path)] == ["pkg/m.py"]
    assert cli.main(["hidden-defaults", str(tmp_path), "--record", "pre-existing"]) == 0
    assert cli.run("hidden-defaults", tmp_path) == []
    (tmp_path / "pkg/m.py").write_text("\n\na = x or 0.5\nb = y or 7\n")
    assert [f.line for f in cli.run("hidden-defaults", tmp_path)] == [4]


def test_allow_list_line_without_a_reason_is_an_error(tmp_path):
    (tmp_path / ".guards-allow").write_text("pkg/m.py:0123456789\n")
    try:
        allow.load(tmp_path)
    except ValueError as e:
        assert ".guards-allow:1" in str(e)
    else:
        raise AssertionError("an entry without a reason must be refused")


def test_exit_status_is_nonzero_with_file_line_and_reason(tmp_path, capsys):
    _write(tmp_path, {"pkg/__init__.py": "", "pkg/m.py": "a = x or 0.5\n"})
    assert cli.main(["hidden-defaults", str(tmp_path)]) == 1
    assert capsys.readouterr().out.startswith("pkg/m.py:1: hidden-defaults:")
