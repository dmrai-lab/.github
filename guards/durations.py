"""Test durations, per invocation: every ``pytest`` and ``python -m unittest`` invocation of the CI workflows prints
its 25 slowest tests, by the configuration that effectively applies to it.

For each invocation (each ``run:`` line of every ``.github/workflows`` file and of the ``workflows`` given) the guard
establishes the options pytest sees: the ini file pytest's own discovery picks from the invocation's paths and
``working-directory`` (``-c`` names one explicitly), its ``addopts`` (a ``-o addopts=`` of the line replaces them),
then the line's own options after them (the last value of an option wins). pytest must end with
``--durations=25`` and ``--durations-min=1.0`` and no ``-p no:terminal``; ``python -m unittest`` needs ``--durations 25``
on its line. A collect-only invocation is exempt. An invocation the guard cannot resolve (``--rootdir``, an option
made of a variable, a configuration file it cannot read, a ``defaults`` working directory) is a finding that names it.
A working directory that is not in the repository (a second checkout) has no configuration: the line's own flags
decide. A script a line runs that starts pytest (``"pytest"`` among string literals, or ``pytest.main(``) must carry the
flags among those literals."""
import configparser
import re
import shlex
import tomllib
from pathlib import Path

from .allow import Finding, line_hash, tracked

CHECK = "test-durations"
PYTEST_DURATIONS, PYTEST_DURATIONS_MIN, UNITTEST_DURATIONS = 25, 1.0, 25
_VALUE_OPTS = {"-m", "-k", "-p", "-c", "-o", "-n", "-W", "--maxfail", "--junitxml", "--durations", "--durations-min",
               "--timeout", "--cov-report", "--cov", "--tb", "--color", "--deselect", "--confcutdir", "--basetemp",
               "--ignore", "--ignore-glob", "--override-ini", "--config-file", "--import-mode", "--log-level"}
_COLLECT_ONLY = {"--collect-only", "--co"}
_ENV = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
_PYTHON = re.compile(r"python[\d.]*$")
_LITERAL = re.compile(r"""f?"((?:[^"\\]|\\.)*)"|f?'((?:[^'\\]|\\.)*)'""")


def _segments(text):
    """``(line number, tokens)`` of every command of the file: continuation lines joined, comments cut, split at
    ``&&``, ``||``, ``;`` and ``|``, a leading ``run:`` / ``- `` / env assignment dropped."""
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        start, line = i + 1, lines[i]
        while line.rstrip().endswith("\\") and i + 1 < len(lines):
            i += 1
            line = line.rstrip()[:-1] + " " + lines[i]
        i += 1
        line = re.sub(r"(^|\s)#.*$", "", line)
        for part in re.split(r"&&|\|\||;|\|", line):
            try:
                tokens = shlex.split(part.replace("$(", "$ (").replace("${{", "$ {{"))
            except ValueError:
                tokens = part.split()
            while tokens and tokens[0] in ("-", "run:"):
                tokens = tokens[1:]
            if tokens and tokens[0].endswith(":"):                      # a key of another kind (name:, uses:, env: ...)
                continue
            while tokens and _ENV.match(tokens[0]):
                tokens = tokens[1:]
            if tokens:
                yield start, tokens


def _steps(text):
    """``(first line, last line, working-directory or None)`` of every step of the file; ``defaults`` raise."""
    lines = text.splitlines()
    out = []
    for n, line in enumerate(lines):
        m = re.match(r"(\s*)- \S", line)
        if not m:
            continue
        indent, end, wd = len(m.group(1)), n, None
        while end + 1 < len(lines) and (not lines[end + 1].strip() or len(lines[end + 1]) - len(lines[end + 1].lstrip()) > indent):
            end += 1
        for k in range(n, end + 1):
            w = re.match(r"\s*(?:- )?working-directory:\s*(\S+)", lines[k])
            if w and len(lines[k]) - len(lines[k].lstrip()) <= indent + 2:
                wd = w.group(1).strip("'\"")
        out.append((n + 1, end + 1, wd))
    return out


def _is_defaults_wd(text):
    """True when a ``defaults:`` block of the file sets a ``working-directory``."""
    lines = text.splitlines()
    return any(re.match(r"\s*defaults:\s*$", ln) and any("working-directory:" in x for x in lines[n + 1:n + 5])
               for n, ln in enumerate(lines))


def _invocation(tokens):
    """``("pytest" | "unittest", index after the command word)`` or None."""
    for k, t in enumerate(tokens):
        prev = tokens[k - 1] if k else ""
        if t in ("pytest", "py.test") and (k == 0 or prev in ("-m", "run", "exec") or _PYTHON.match(prev.rsplit("/", 1)[-1])):
            return "pytest", k + 1
        if t == "unittest" and prev == "-m":
            return "unittest", k + 1
    return None


def _addopts(f):
    """The ``addopts`` list of a pytest configuration file, or None when it has no pytest table."""
    text = f.read_text()
    if f.name.endswith(".toml"):
        table = tomllib.loads(text).get("tool", {}).get("pytest", {}).get("ini_options")
        if table is None:
            return None
        v = table.get("addopts", "")
    else:
        cp = configparser.ConfigParser(interpolation=None)
        cp.read_string(text)
        section = "tool:pytest" if f.name == "setup.cfg" else "pytest"
        if not cp.has_section(section):
            return None
        v = cp.get(section, "addopts", fallback="")
    return list(v) if isinstance(v, list) else shlex.split(v.replace("\n", " "))


def _inifile(root, start):
    """The configuration file pytest's discovery picks from directory ``start`` upwards, or None."""
    d = start
    while True:
        for name in ("pytest.ini", ".pytest.ini", "pyproject.toml", "tox.ini", "setup.cfg"):
            f = root / d / name
            if f.is_file():
                if name in ("pytest.ini", ".pytest.ini") or _addopts(f) is not None:
                    return f
        if d == Path("."):
            return None
        d = d.parent


def _option(tokens, name):
    """The last value of ``name`` among ``tokens`` (``--name=v`` or ``--name v``), or None."""
    val = None
    for i, t in enumerate(tokens):
        if t.startswith(name + "="):
            val = t.split("=", 1)[1]
        elif t == name and i + 1 < len(tokens):
            val = tokens[i + 1]
    return val


def _pytest(root, wd, args):
    """``None`` when the invocation prints 25 slowest at 1.0 s, else the reason."""
    if any(t.startswith("--rootdir") for t in args):
        return "uses --rootdir; the guard cannot resolve the configuration that applies"
    if any("$" in t and t.startswith("-") for t in args):
        return "an option made of a variable; the guard cannot resolve what pytest receives"
    if _COLLECT_ONLY & set(args):
        return None
    paths, i = [], 0
    while i < len(args):
        t = args[i]
        if t.startswith("-"):
            i += 2 if (t in _VALUE_OPTS and "=" not in t) else 1
            continue
        paths.append(t)
        i += 1
    ancestors = []
    for p in paths:
        p = re.split(r"::", p)[0]
        if "$" in p:
            continue
        p = re.split(r"[*?\[]", p)[0].rstrip("/") or "."
        q = (wd / p) if wd else Path(p)
        if (root / q).exists():
            ancestors.append(q if (root / q).is_dir() else q.parent)
    start = wd or Path(".")
    if ancestors:
        parts = [a.parts for a in ancestors]
        common = []
        for group in zip(*parts):
            if len(set(group)) != 1:
                break
            common.append(group[0])
        start = Path(*common) if common else Path(".")
    cfg = _option(args, "-c") or _option(args, "--config-file")
    if wd is not None and not (root / wd).exists():
        base = []                                               # a second checkout: no configuration of this repository
    elif cfg:
        f = root / (wd or ".") / cfg
        if not f.is_file():
            return f"names the configuration file {cfg}, which the guard cannot read"
        base = _addopts(f)
        if base is None:
            base = []
    else:
        f = _inifile(root, start)
        base = _addopts(f) if f else []
    override = [t.split("=", 1)[1] for t in args if t.startswith("addopts=")]
    for i, t in enumerate(args):
        if t in ("-o", "--override-ini") and i + 1 < len(args) and args[i + 1].startswith("addopts="):
            override.append(args[i + 1].split("=", 1)[1])
        if t.startswith("-oaddopts="):
            override.append(t.split("=", 1)[1])
    if override:
        base = shlex.split(override[-1])
    effective = base + args
    if _COLLECT_ONLY & set(effective):
        return None
    for i, t in enumerate(effective):
        if t in ("-p", ) and i + 1 < len(effective) and effective[i + 1] in ("no:terminal", "no:terminalreporter"):
            return "disables the terminal reporter (-p no:terminal), so no durations are printed"
        if t in ("-pno:terminal", "-pno:terminalreporter"):
            return "disables the terminal reporter, so no durations are printed"
    n, m = _option(effective, "--durations"), _option(effective, "--durations-min")
    try:
        ok = n is not None and int(n) == PYTEST_DURATIONS
        ok2 = m is not None and float(m) == PYTEST_DURATIONS_MIN
    except ValueError:
        return f"has --durations={n} --durations-min={m}, which the guard cannot read"
    if ok and ok2:
        return None
    shown = f"--durations={n}" if n is not None else "no --durations"
    shown += f" --durations-min={m}" if m is not None else ", no --durations-min"
    return (f"effective pytest options have {shown}; need --durations={PYTEST_DURATIONS} "
            f"--durations-min={PYTEST_DURATIONS_MIN} (in addopts of the applying configuration or on the line)")


def _unittest(args):
    n = _option(args, "--durations")
    if n is not None and n.isdigit() and int(n) == UNITTEST_DURATIONS:
        return None
    return f"unittest has {'--durations ' + n if n is not None else 'no --durations'}; need --durations {UNITTEST_DURATIONS}"


_STARTS_PYTEST = re.compile(r"""["']-m["']\s*,\s*["']pytest["']|\bpytest\.main\(|["'][^"'\n]*-m pytest\b""")


def _script_of(tokens):
    """The script file a command runs (``python x.py``, ``bash x.sh``, ``./x.sh``), or None."""
    head = tokens[0].rsplit("/", 1)[-1]
    if _PYTHON.match(head) or head in ("bash", "sh"):
        rest = [t for t in tokens[1:] if not t.startswith("-")]
        if tokens[1:2] == ["-m"] or not rest:
            return None
        return rest[0] if rest[0].endswith((".py", ".sh")) else None
    return tokens[0] if tokens[0].startswith("./") and tokens[0].endswith((".py", ".sh")) else None


def _script_findings(root, wd, tokens):
    """``(script, line, reason)`` for each place a script of the command starts pytest without the flags among its
    string literals."""
    script = _script_of(tokens)
    if script is None:
        return []
    f = root / (wd or ".") / script
    if not f.is_file():
        f = root / script
    if not f.is_file():
        return []
    text, out = f.read_text(), []
    for m in _STARTS_PYTEST.finditer(text):
        close = text.find("]", m.start())
        window = text[m.start(): close if 0 <= close - m.start() < 800 else text.find("\n", m.start())]
        lits = [x for a, b in _LITERAL.findall(window) for x in (a or b).split()]
        if _COLLECT_ONLY & set(lits):
            continue
        reason = _pytest_literals(lits)
        if reason:
            out.append((script, text.count("\n", 0, m.start()) + 1, reason))
    return out


def _pytest_literals(lits):
    n, m = _option(lits, "--durations"), _option(lits, "--durations-min")
    try:
        ok = n is not None and int(n) == PYTEST_DURATIONS and m is not None and float(m) == PYTEST_DURATIONS_MIN
    except ValueError:
        ok = False
    return None if ok else (f"starts pytest with {n and '--durations=' + n or 'no --durations'}"
                            f"{m and ' --durations-min=' + m or ', no --durations-min'}; the script must carry "
                            f"--durations={PYTEST_DURATIONS} --durations-min={PYTEST_DURATIONS_MIN} itself")


def check(root, workflows=(), **_):
    root = Path(root)
    names = {p for p in tracked(root) if re.fullmatch(r"\.github/workflows/[^/]+\.ya?ml", p)}
    names |= {w for w in workflows if (root / w).is_file()}
    found = []
    for name in sorted(names):
        text = (root / name).read_text()
        steps = _steps(text)
        defaults = _is_defaults_wd(text)
        for line, tokens in _segments(text):
            wd = next((Path(s[2]) for s in steps if s[0] <= line <= s[1] and s[2]), None)
            inv = _invocation(tokens)
            reasons = []
            if inv:
                kind, k = inv
                if defaults:
                    reasons.append("a job `defaults` working-directory applies; the guard cannot resolve it")
                else:
                    r = _pytest(root, wd, tokens[k:]) if kind == "pytest" else _unittest(tokens[k:])
                    if r:
                        reasons.append(r)
            if not defaults:
                reasons += [f"runs {s}:{n}, which {r}" for s, n, r in _script_findings(root, wd, tokens)]
            text_line = " ".join(tokens)
            found += [Finding(CHECK, name, line, f"`{text_line[:110]}`: {r}", line_hash(CHECK, text_line)) for r in reasons]
    return found
