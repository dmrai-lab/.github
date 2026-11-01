"""CI coverage, per file: every tracked ``test_*.py`` is collected by some ``pytest`` invocation of a CI workflow.
An invocation collects a file when it names the file, a directory holding it or a glob matching it, or runs
without paths (then the ``testpaths`` of the repository's pytest configuration, else the whole repository). A
``--ignore`` / ``--ignore-glob`` of the same invocation removes the file again. An invocation whose path is a shell
variable (``pytest $PATHS``) is read as naming every path-like token of its workflow file."""
import fnmatch
import re
import shlex
import tomllib
from pathlib import Path

from .allow import Finding, line_hash, tracked

CHECK = "ci-coverage"
DEFAULT_WORKFLOWS = (".github/workflows/tests.yml",)
_VALUE_OPTS = {"-m", "-k", "-p", "-c", "-o", "-n", "-W", "--maxfail", "--rootdir", "--junitxml", "--durations",
               "--timeout", "--cov-report", "--tb", "--color", "--deselect", "--confcutdir", "--basetemp",
               "--ignore", "--ignore-glob"}
_PATHISH = re.compile(r"[\w.\[\]*?-]+/[\w./\[\]*?-]*|[\w.\[\]*?/-]+\.py")


def _matches(f, root):
    root = root.strip("'\"").removeprefix("./")
    return root in ("", ".") or f == root.rstrip("/") or f.startswith(root.rstrip("/") + "/") or fnmatch.fnmatch(f, root)


def _invocations(text):
    """``(paths, ignores)`` of each pytest command line of ``text``."""
    for line in text.replace("\\\n", " ").splitlines():
        for m in re.finditer(r"\bpytest\b", line):
            rest = re.split(r"&&|\|\||;|\||#", line[m.end():])[0]
            try:
                tokens = shlex.split(rest.replace("$(", "$ (")) if "$(" in rest else shlex.split(rest)
            except ValueError:
                tokens = rest.split()
            paths, ignores, i = [], [], 0
            while i < len(tokens):
                t = tokens[i]
                opt, eq, val = t.partition("=")
                if opt in ("--ignore", "--ignore-glob"):
                    val = val if eq else (tokens[i + 1] if i + 1 < len(tokens) else "")
                    ignores.append(val)
                    i += 1 if eq else 2
                elif t.startswith("-"):
                    i += 2 if (opt in _VALUE_OPTS and not eq) else 1
                else:
                    paths.append(t)
                    i += 1
            yield paths, ignores


def _testpaths(root):
    f = Path(root) / "pyproject.toml"
    if not f.exists():
        return []
    return list(tomllib.loads(f.read_text()).get("tool", {}).get("pytest", {}).get("ini_options", {}).get("testpaths", []))


def check(root, workflows=DEFAULT_WORKFLOWS, **_):
    texts = [(Path(root) / w).read_text() for w in workflows if (Path(root) / w).exists()]
    if not texts:
        return []                                             # an installed copy of the tests has no workflow
    files = [p for p in tracked(root) if p.endswith(".py") and p.rsplit("/", 1)[-1].startswith("test_")]
    testpaths = _testpaths(root) or ["."]
    covered = set()
    for text in texts:
        pool = [p for p in _PATHISH.findall(text)]
        for paths, ignores in _invocations(text):
            roots = list(paths) or testpaths
            if any(r.startswith("$") for r in roots):
                roots += pool
            covered |= {f for f in files if any(_matches(f, r) for r in roots)
                        and not any(_matches(f, ig) for ig in ignores)}
    return [Finding(CHECK, f, 1, "no CI pytest invocation collects this test file", line_hash(CHECK, f))
            for f in files if f not in covered]
