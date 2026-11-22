"""The ref of each of the six packages for the integration check.

On success one ``<name> <ref>`` line per package is printed on standard output and the exit status is 0; on a refused
input one ``refs: <reason>`` line is printed on standard error, nothing on standard output, and the exit status is 2.
"""
import argparse
import json
import re
import subprocess
import sys

#: the six packages the integration check installs, in the order of the job log
PACKAGES = ("dmipy-analytic", "dmipy-replay", "dmipy-sim", "dmipy-fit", "dmipy-design", "dmipy-tract")
#: the branches `others` may name
BRANCHES = ("main", "dev")
#: the organisation's public repositories
ORIGIN = "https://github.com/dmrai-lab"
#: an exact commit: 40 lowercase hexadecimal digits
COMMIT = re.compile(r"[0-9a-f]{40}")


class RefsError(ValueError):
    """A refused input: a malformed `pins`, an unknown package, an `others` that is not a branch, a failed listing."""


def _object_pairs(pairs):
    seen = set()
    for key, _ in pairs:
        if key in seen:
            raise RefsError(f"the pins name {key} twice")
        seen.add(key)
    return dict(pairs)


def parse_pins(text):
    """The `pins` JSON text as a dict of package name to commit hash; empty or blank text gives an empty dict."""
    if not text.strip():
        return {}
    try:
        pins = json.loads(text, object_pairs_hook=_object_pairs)
    except json.JSONDecodeError as error:
        raise RefsError(f"the pins are not JSON: {error}") from error
    if not isinstance(pins, dict):
        raise RefsError("the pins are not a JSON object")
    for name, ref in pins.items():
        if name not in PACKAGES:
            raise RefsError(f"the pins name a package that is not one of the six: {name}")
        if not isinstance(ref, str) or not COMMIT.fullmatch(ref):
            raise RefsError(f"the pin of {name} is not 40 lowercase hexadecimal digits: {ref!r}")
    return pins


def has_branch(origin, name, branch):
    """Whether the repository `origin`/`name` has a branch `branch` (a `feature/<branch>` does not count)."""
    run = subprocess.run(
        ["git", "ls-remote", "--heads", f"{origin}/{name}", f"refs/heads/{branch}"],
        capture_output=True, text=True,
    )
    if run.returncode != 0:
        raise RefsError(f"cannot list the branches of {name}: {run.stderr.strip()}")
    wanted = f"refs/heads/{branch}"
    for line in run.stdout.splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[1] == wanted:
            return True
    return False


def resolve(others, pins, branch_exists):
    """The list of ``(name, ref)`` for every package in :data:`PACKAGES`, in order.

    A pinned package is at its commit; otherwise `others` is the ref when it is ``main`` or the package has that
    branch, and ``main`` when it does not. `branch_exists(name, branch)` is not called for a pinned package or when
    `others` is ``main``.
    """
    if others not in BRANCHES:
        raise RefsError(f"others is not one of {', '.join(BRANCHES)}: {others!r}")
    resolved = []
    for name in PACKAGES:
        if name in pins:
            resolved.append((name, pins[name]))
        elif others == "main":
            resolved.append((name, "main"))
        elif branch_exists(name, others):
            resolved.append((name, others))
        else:
            resolved.append((name, "main"))
    return resolved


def main(argv=None):
    """Parse the arguments, print the ref of each package, and return the exit status."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--others", default="main", help="the branch of the packages the caller is not (default: main)")
    parser.add_argument("--pins", default="", help='exact commits, as JSON {"<package>": "<40 lowercase hex>"}')
    parser.add_argument("--origin", default=ORIGIN, help="the origin holding the six repositories")
    args = parser.parse_args(argv)
    try:
        pins = parse_pins(args.pins)
        resolved = resolve(args.others, pins, lambda name, branch: has_branch(args.origin, name, branch))
    except RefsError as error:
        print("refs: " + " ".join(str(error).split()), file=sys.stderr)
        return 2
    for name, ref in resolved:
        print(f"{name} {ref}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
