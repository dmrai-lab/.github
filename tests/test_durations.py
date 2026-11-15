"""The test-durations guard on fixture repositories: what it fails (with the invocation named) and what it passes."""
import textwrap

from guards import __main__ as cli
from guards import durations

FLAGS = "--durations=25 --durations-min=1.0"


def _write(root, files):
    for name, text in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(text))


def _wf(run, extra=""):
    return {".github/workflows/tests.yml": f"jobs:\n  t:\n    steps:\n{extra}      - run: {run}\n"}


def _reasons(root):
    return [f.reason for f in durations.check(root)]


def test_pytest_without_the_option_fails_and_names_the_invocation(tmp_path):
    _write(tmp_path, {"pyproject.toml": '[tool.pytest.ini_options]\naddopts = "-v"\n', **_wf("pytest -q tests")})
    msg = _reasons(tmp_path)
    assert len(msg) == 1 and msg[0].startswith("`pytest -q tests`: effective pytest options have no --durations")
    print(msg[0])


def test_pytest_with_the_option_in_the_central_addopts_passes(tmp_path):
    _write(tmp_path, {"pyproject.toml": f'[tool.pytest.ini_options]\naddopts = "-v {FLAGS}"\n', **_wf("pytest -q tests")})
    assert _reasons(tmp_path) == []


def test_pytest_with_the_option_on_the_line_passes_and_a_wrong_value_fails(tmp_path):
    _write(tmp_path, _wf(f"python -m pytest -q {FLAGS}"))
    assert _reasons(tmp_path) == []
    _write(tmp_path, _wf("pytest -q --durations=10 --durations-min=1.0"))
    msg = _reasons(tmp_path)
    assert len(msg) == 1 and "--durations=10" in msg[0]
    print(msg[0])
    _write(tmp_path, _wf("pytest -q --durations=25 --durations-min=5"))
    assert "--durations-min=5" in _reasons(tmp_path)[0]


def test_the_lines_later_value_wins_over_the_addopts(tmp_path):
    _write(tmp_path, {"pytest.ini": f"[pytest]\naddopts = {FLAGS}\n", **_wf("pytest --durations=0")})
    assert "--durations=0" in _reasons(tmp_path)[0]


def test_an_addopts_override_on_the_line_removes_the_central_option(tmp_path):
    _write(tmp_path, {"pyproject.toml": f'[tool.pytest.ini_options]\naddopts = "{FLAGS}"\n',
                      **_wf('pytest -o addopts="-q" tests')})
    msg = _reasons(tmp_path)
    assert len(msg) == 1 and "no --durations" in msg[0]
    print(msg[0])
    _write(tmp_path, _wf(f'pytest -o addopts="{FLAGS}" tests'))
    assert _reasons(tmp_path) == []


def test_another_configuration_file_or_a_disabled_reporter_or_rootdir_fails(tmp_path):
    _write(tmp_path, {"pyproject.toml": f'[tool.pytest.ini_options]\naddopts = "{FLAGS}"\n', "other.ini": "[pytest]\naddopts = -q\n",
                      **_wf("pytest -c other.ini tests")})
    assert "no --durations" in _reasons(tmp_path)[0]
    _write(tmp_path, _wf(f"pytest -p no:terminal {FLAGS}"))
    assert "terminal reporter" in _reasons(tmp_path)[0]
    _write(tmp_path, _wf(f"pytest --rootdir=sub {FLAGS}"))
    assert "--rootdir" in _reasons(tmp_path)[0]


def test_the_configuration_is_the_one_pytest_discovers_from_the_paths_and_working_directory(tmp_path):
    _write(tmp_path, {"pyproject.toml": f'[tool.pytest.ini_options]\naddopts = "{FLAGS}"\n',
                      "sub/pytest.ini": "[pytest]\naddopts = -q\n", "sub/test_a.py": "",
                      **_wf("pytest -q sub/test_a.py")})
    assert "no --durations" in _reasons(tmp_path)[0]              # sub/pytest.ini is found first
    _write(tmp_path, _wf("pytest -q", "      - working-directory: sub\n        run: pytest -q\n"))
    assert len(_reasons(tmp_path)) == 1                           # the line in sub/, not the one at the root
    _write(tmp_path, {".github/workflows/tests.yml": "jobs:\n  t:\n    steps:\n      - name: x\n        working-directory: second-checkout\n        run: pytest -q\n"})
    assert "no --durations" in _reasons(tmp_path)[0]              # a second checkout: the line's own flags decide
    _write(tmp_path, {".github/workflows/tests.yml": f"jobs:\n  t:\n    steps:\n      - working-directory: second-checkout\n        run: pytest -q {FLAGS}\n"})
    assert _reasons(tmp_path) == []


def test_collect_only_and_non_test_commands_are_exempt(tmp_path):
    _write(tmp_path, _wf("pytest tests --collect-only -q | tail -1"))
    assert _reasons(tmp_path) == []
    _write(tmp_path, _wf("pip install pytest pytest-cov && echo pytest done"))
    assert _reasons(tmp_path) == []


def test_unittest_without_durations_fails_and_with_it_passes(tmp_path):
    _write(tmp_path, _wf("python3 -m unittest discover -s tools/q -v"))
    msg = _reasons(tmp_path)
    assert msg == ["`python3 -m unittest discover -s tools/q -v`: unittest has no --durations; need --durations 25"]
    print(msg[0])
    _write(tmp_path, _wf("python3 -m unittest discover -s tools/q --durations 25 -v"))
    assert _reasons(tmp_path) == []
    _write(tmp_path, _wf("python3 -m unittest discover -s tools/q --durations 10 -v"))
    assert "--durations 10" in _reasons(tmp_path)[0]


def test_a_script_that_starts_pytest_must_carry_the_flags(tmp_path):
    _write(tmp_path, {"tools/run.py": 'import subprocess\nsubprocess.run(["python", "-m", "pytest", "-q", "--durations=0"])\n'
                                      'image.pip_install("pytest")\n', **_wf("python tools/run.py go")})
    msg = _reasons(tmp_path)
    assert len(msg) == 1 and "tools/run.py:2" in msg[0] and "--durations=0" in msg[0]
    print(msg[0])
    (tmp_path / "tools/run.py").write_text(f'subprocess.run(["python", "-m", "pytest", "-q", "--durations=25", "--durations-min=1.0"])\n')
    assert _reasons(tmp_path) == []


def test_the_guard_is_a_sub_command_and_part_of_all(tmp_path, capsys):
    _write(tmp_path, _wf("pytest -q"))
    assert cli.main(["test-durations", str(tmp_path)]) == 1
    assert ".github/workflows/tests.yml:4: test-durations:" in capsys.readouterr().out
    _write(tmp_path, _wf(f"pytest -q {FLAGS}"))
    assert cli.main(["test-durations", str(tmp_path)]) == 0
