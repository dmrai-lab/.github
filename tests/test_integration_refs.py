"""``integration/refs.py`` and the clone step of ``integration.yml``: refs of the six packages, branch or commit."""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from integration import refs

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "integration" / "refs.py"
WORKFLOW = ROOT / ".github" / "workflows" / "integration.yml"

NAMES = ("dmipy-analytic", "dmipy-replay", "dmipy-sim", "dmipy-fit", "dmipy-design", "dmipy-tract")
A = "a" * 40
B = "0123456789abcdef0123456789abcdef01234567"

GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_COMMITTER_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
}


def _git(cwd, *args):
    run = subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True,
                         env={**os.environ, **GIT_ENV})
    return run.stdout.strip()


def _no_lookup(name, branch):
    raise AssertionError(f"looked up the branches of {name}")


def _cli(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)


@pytest.fixture
def origin(tmp_path):
    base = tmp_path / "origin"
    base.mkdir()
    hashes = {}
    for name in NAMES:
        repo = base / name
        repo.mkdir()
        _git(repo, "init", "--quiet", "-b", "main")
        _git(repo, "commit", "--quiet", "--allow-empty", "-m", "first")
        hashes[name, "first"] = _git(repo, "rev-parse", "HEAD")
        _git(repo, "commit", "--quiet", "--allow-empty", "-m", "main")
        hashes[name, "main"] = _git(repo, "rev-parse", "HEAD")
        if name in ("dmipy-replay", "dmipy-sim"):
            _git(repo, "checkout", "--quiet", "-b", "dev")
            _git(repo, "commit", "--quiet", "--allow-empty", "-m", "dev")
            hashes[name, "dev"] = _git(repo, "rev-parse", "HEAD")
            _git(repo, "checkout", "--quiet", "main")
        if name == "dmipy-fit":
            _git(repo, "checkout", "--quiet", "-b", "feature/dev")
            _git(repo, "commit", "--quiet", "--allow-empty", "-m", "dev")
            _git(repo, "checkout", "--quiet", "main")
    return base.as_uri(), hashes


def _step():
    lines = WORKFLOW.read_text(encoding="utf-8").splitlines()
    named = next(i for i, line in enumerate(lines) if line.strip().startswith("- name: The other packages"))
    run = next(i for i in range(named + 1, len(lines)) if lines[i].strip() == "run: |")
    indent = len(lines[run]) - len(lines[run].lstrip())
    body = []
    for line in lines[run + 1:]:
        if line.strip() and len(line) - len(line.lstrip()) <= indent:
            break
        body.append(line[indent + 2:])
    return "\n".join(body) + "\n"


def _run_step(base, url, others, pins, caller=None, with_script=True):
    work = base / "work"
    smoke = work / "integration-src"
    smoke.mkdir(parents=True)
    if with_script:
        (smoke / "integration").symlink_to(ROOT / "integration")
    else:
        (smoke / "integration").mkdir()
    bin_dir = work / "bin"
    bin_dir.mkdir()
    (bin_dir / "python").symlink_to(sys.executable)
    (work / "step.sh").write_text(_step())
    if caller is not None:
        name, commit = caller
        packages = work / "packages"
        packages.mkdir()
        subprocess.run(["git", "clone", "--quiet", f"{url}/{name}", str(packages / name)], check=True,
                       capture_output=True, text=True, env={**os.environ, **GIT_ENV})
        _git(packages / name, "checkout", "--quiet", "--detach", commit)
    env = {**os.environ, **GIT_ENV,
           "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
           "OTHERS": others, "PINS": pins, "ORIGIN": url}
    done = subprocess.run(["bash", "-e", "step.sh"], cwd=work, capture_output=True, text=True, env=env)
    heads = {}
    packages = work / "packages"
    if packages.is_dir():
        for directory in sorted(packages.iterdir()):
            if directory.is_dir():
                heads[directory.name] = _git(directory, "rev-parse", "HEAD")
    return done, heads


def _smoke_steps():
    lines = WORKFLOW.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line == "  smoke:")
    steps = []
    current = {}
    for line in lines[start + 1:]:
        if re.match(r"^  \S", line):
            break
        if line.startswith("      - "):
            current = {}
            steps.append(current)
            key, _, value = line[8:].partition(":")
            current[key] = value.strip()
        elif re.match(r"^        [A-Za-z-]+:", line) and current:
            key, _, value = line[8:].partition(":")
            current[key] = value.strip()
    return [step.get("name") or step.get("uses") for step in steps]


def test_without_inputs_every_package_is_at_main_and_nothing_is_looked_up(tmp_path):
    assert refs.resolve("main", {}, _no_lookup) == [(name, "main") for name in NAMES]
    done = _cli("--origin", str(tmp_path / "missing"))
    assert done.returncode == 0
    assert done.stdout == "".join(f"{name} main\n" for name in NAMES)
    assert done.stderr == ""


def test_dev_is_main_for_a_package_without_a_dev_branch():
    calls = []

    def exists(name, branch):
        calls.append((name, branch))
        return name in ("dmipy-replay", "dmipy-sim")

    assert refs.resolve("dev", {}, exists) == [
        (name, "dev" if name in ("dmipy-replay", "dmipy-sim") else "main") for name in NAMES
    ]
    assert calls == [(name, "dev") for name in NAMES]


@pytest.mark.parametrize("others", ["main", "dev"])
def test_a_pin_wins_over_others_and_is_not_looked_up(others):
    pins = {"dmipy-replay": A, "dmipy-tract": B}

    def exists(name, branch):
        if name in pins:
            raise AssertionError(f"looked up the pinned package {name}")
        return True

    assert refs.resolve(others, pins, exists) == [(name, pins.get(name, others)) for name in NAMES]


@pytest.mark.parametrize("text", ["", "  \n", "{}"])
def test_blank_pins_and_the_empty_object_pin_nothing(text):
    assert refs.parse_pins(text) == {}


BAD_PINS = [
    json.dumps({"dmipy-sim": "a" * 39}),
    json.dumps({"dmipy-sim": "a" * 41}),
    json.dumps({"dmipy-sim": "A" * 40}),
    json.dumps({"dmipy-sim": "g" * 40}),
    json.dumps({"dmipy-sim": "a" * 40 + "\n"}),
    json.dumps({"dmipy-sim": "main"}),
    json.dumps({"dmipy-sim": 7}),
    json.dumps({"dmipy-other": A}),
    json.dumps({"dmipy_sim": A}),
    '{"dmipy-sim": "%s", "dmipy-sim": "%s"}' % (A, B),
    '["dmipy-sim"]',
    '"dmipy-sim"',
    "{dmipy-sim: " + "a" * 40 + "}",
]


@pytest.mark.parametrize("text", BAD_PINS)
def test_pins_that_are_refused(text):
    with pytest.raises(refs.RefsError):
        refs.parse_pins(text)
    done = _cli("--pins", text)
    assert done.returncode == 2
    assert done.stdout == ""
    assert done.stderr.startswith("refs: ")
    assert done.stderr.count("\n") == 1
    assert done.stderr.endswith("\n")


@pytest.mark.parametrize("others", ["", "Main", "release", "refs/heads/dev", "main dev"])
def test_others_that_are_refused(others):
    with pytest.raises(refs.RefsError):
        refs.resolve(others, {}, _no_lookup)
    done = _cli("--others", others)
    assert done.returncode == 2
    assert done.stdout == ""
    assert done.stderr.startswith("refs: ")
    assert done.stderr.count("\n") == 1


def test_the_script_reads_the_branches_of_real_repositories(origin):
    url, hashes = origin
    pin = hashes["dmipy-sim", "first"]
    done = _cli("--others", "dev", "--pins", json.dumps({"dmipy-sim": pin}), "--origin", url)
    assert done.returncode == 0
    assert done.stderr == ""
    expected = [("dmipy-analytic", "main"), ("dmipy-replay", "dev"), ("dmipy-sim", pin),
                ("dmipy-fit", "main"), ("dmipy-design", "main"), ("dmipy-tract", "main")]
    assert done.stdout == "".join(f"{name} {ref}\n" for name, ref in expected)
    assert refs.has_branch(url, "dmipy-replay", "dev") is True
    assert refs.has_branch(url, "dmipy-fit", "dev") is False


def test_a_branch_listing_that_fails_is_an_error_not_a_fallback(tmp_path):
    url = (tmp_path / "missing").as_uri()
    with pytest.raises(refs.RefsError):
        refs.has_branch(url, "dmipy-analytic", "dev")
    done = _cli("--others", "dev", "--origin", url)
    assert done.returncode == 2
    assert done.stdout == ""
    assert done.stderr.startswith("refs: cannot list the branches of dmipy-analytic")
    assert done.stderr.count("\n") == 1


def test_the_step_without_inputs_clones_every_package_at_main(tmp_path, origin):
    url, hashes = origin
    done, heads = _run_step(tmp_path, url, "main", "")
    assert done.returncode == 0
    assert heads == {name: hashes[name, "main"] for name in NAMES}
    assert done.stdout == "".join(f"integration: {name} main {hashes[name, 'main']}\n" for name in NAMES)
    for name in NAMES:                                    # one commit deep, as the clone command states
        assert _git(tmp_path / "work" / "packages" / name, "rev-list", "--count", "HEAD") == "1"


def test_the_step_checks_out_the_branch_the_pin_and_leaves_the_caller(tmp_path, origin):
    url, hashes = origin
    pin = hashes["dmipy-tract", "first"]
    done, heads = _run_step(tmp_path, url, "dev", json.dumps({"dmipy-tract": pin}),
                            caller=("dmipy-sim", hashes["dmipy-sim", "first"]))
    assert done.returncode == 0
    assert heads == {
        "dmipy-analytic": hashes["dmipy-analytic", "main"],
        "dmipy-replay": hashes["dmipy-replay", "dev"],
        "dmipy-sim": hashes["dmipy-sim", "first"],
        "dmipy-fit": hashes["dmipy-fit", "main"],
        "dmipy-design": hashes["dmipy-design", "main"],
        "dmipy-tract": pin,
    }
    lines = [
        f"integration: dmipy-analytic main {hashes['dmipy-analytic', 'main']}",
        f"integration: dmipy-replay dev {hashes['dmipy-replay', 'dev']}",
        f"integration: dmipy-sim caller {hashes['dmipy-sim', 'first']}",
        f"integration: dmipy-fit main {hashes['dmipy-fit', 'main']}",
        f"integration: dmipy-design main {hashes['dmipy-design', 'main']}",
        f"integration: dmipy-tract {pin} {pin}",
    ]
    assert done.stdout == "".join(line + "\n" for line in lines)


def test_the_step_fails_when_the_caller_is_pinned_at_another_commit(tmp_path, origin):
    url, hashes = origin
    first = hashes["dmipy-sim", "first"]
    pin = hashes["dmipy-sim", "main"]
    done, _ = _run_step(tmp_path, url, "main", json.dumps({"dmipy-sim": pin}), caller=("dmipy-sim", first))
    assert done.returncode == 1
    assert f"::error title=Integration::dmipy-sim is pinned at {pin} and its checkout is at {first}" in done.stdout
    done, _ = _run_step(tmp_path / "again", url, "main", json.dumps({"dmipy-sim": first}),
                        caller=("dmipy-sim", first))
    assert done.returncode == 0


def test_the_step_fails_on_refused_pins_before_any_clone(tmp_path, origin):
    url, _ = origin
    done, heads = _run_step(tmp_path, url, "dev", json.dumps({"dmipy-sim": "a" * 39}))
    assert done.returncode == 2
    assert done.stdout == ""
    assert heads == {}


def test_the_step_with_a_smoke_set_that_has_no_script(tmp_path, origin):
    url, hashes = origin
    done, heads = _run_step(tmp_path, url, "main", "", with_script=False)
    assert done.returncode == 0
    assert heads == {name: hashes[name, "main"] for name in NAMES}
    assert done.stdout == "".join(f"integration: {name} main {hashes[name, 'main']}\n" for name in NAMES)
    done, heads = _run_step(tmp_path / "again", url, "dev", "", with_script=False)
    assert done.returncode == 1
    assert ("::error title=Integration::the smoke set at this ref has no integration/refs.py: "
            "others and pins need a newer ref") in done.stdout
    assert heads == {}


def test_the_steps_of_the_smoke_job_are_in_this_order():
    assert _smoke_steps() == [
        "The calling repository, at its own commit",
        "The smoke set",
        "actions/setup-python@v5",
        "The other packages, at the chosen branch or at exact commits",
        "Install",
        "Smoke",
    ]
