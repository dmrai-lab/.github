"""No tracked file names a project, service, machine or local path outside the public project.

The forbidden words are never spelled in clear, in a comment, in a commit message or in output. Two encodings are
resolved at runtime:

* single words (a repository, a rented-compute vendor, a lab machine) are stored as sha256 hashes of the
  lowercase token; a line is tokenised on ``[A-Za-z0-9_-]+`` (and on ``-`` / ``_`` inside a token) and each token
  is hashed the same way;
* multi-token patterns (a package with an issue number, a workspace path, ownership phrasing) are stored as
  split fragments that are joined into a regular expression when the guard runs.

A finding names file:line and the pattern's index, never the matched text. Hardware classes (GPU model names)
may be named; which machine ran a measurement may not. This file holds the encoded tables, so it is not scanned.

A repository's own CI tooling may have to name the rented-compute vendor it launches on (:data:`VENDOR_PATTERN`):
that finding alone carries a line hash and is accepted by a stated ``.guards-allow`` entry like the other guards'.
Every other finding (a private repository, a package, a machine, a person's home path) has no key and can never be
allowed."""
import hashlib
import re
from pathlib import Path

from .allow import Finding, line_hash, tracked

CHECK = "private-ids"
SELF = "guards/private_ids.py"

#: sha256 of the lowercase token (single words)
FORBIDDEN_TOKEN_DIGESTS = frozenset((
    "2f1e83d30fff12f10f4a956d08bd6b200ae89e24621c2066c1a902aab2da7acb",
    "01db71ab8048f74a4b92c26ba77285ade0687ac192758e8185ad52701f649ef2",
    "e839e162d8106fe35160d44676559cc5b7cd62284058792011d52976e8a2a0e1",
    "b95ee4efc49878ebc6e8f93c29d7f692742dad7330574634428c8d6355794d88",
    "294aa8d75483b8331e3ba6a7f24aea15202747f36de65197e7bc6194880b2558",
    "be2abdeb021a79176e2dbf116831429aee5d4bd795b9d659f5ce5bf666492889",
    "eb782b881d4729e55686ccf5debe37f3708bdab49152e1b4b1599a906a563f70",
    "75481d9af31632532bc70496d9416e28a2a6e3948ed7944a100de667c214885c",
    "c040c5a65fdb91143944def084d1a1d1dd16973552fecf60ad94b70e2e11de91",
    "16f1496bf9d0e3d13476dff58afe84023ab9db78d596a440bb2bd27d1dcc086e",
))

#: sha256 of the lowercase user name in ``/home/<user>`` and ``/Users/<user>``: a container's own user is public,
#: a person's home directory is not
FORBIDDEN_USER_DIGESTS = frozenset((
    "2f55e450c3db288295509c0eb0c6cc1ad3adb13c5dbe18b745a1aaa24dc02613",
    "6761ce5fb48a17cf55c2164409d09652dc6f64fa07c93924d62df09c32c25e8f",
))
HOME_RE = re.compile(r"/(?:home|Users)/([A-Za-z0-9_.-]+)")

#: split fragments, joined into case-insensitive regular expressions at run time
FORBIDDEN_FRAGMENTS = (
    ("dmipy", "[-_]sim", "[-_]cu", "da"),                   # the non-public backend package
    ("cu", "da#", r"\d"),                                    # its issue references
    ("dmrai", "-w", "s"),                                    # a lab workspace path
    ("/m", "nt/"),
    (r"\bmo", "dal (run|t4|container)", "|import mo", "dal|mo", r"dal\.(app|image)"),   # a rented-compute vendor
    ("shared ", "box"),                                      # ownership phrasing
    ("vast", r"\.ai"),
    ("dmrai", "-pa", "pers"),                                # a private repository, by prefix
)

VENDOR_PATTERN = 4
"""The index of the rented-compute vendor's pattern in :data:`FORBIDDEN_FRAGMENTS`: the one allow-listable finding."""

TOKEN_RE = re.compile(r"[A-Za-z0-9_-]+")
PATTERNS = [re.compile("".join(f), re.IGNORECASE) for f in FORBIDDEN_FRAGMENTS]


def _digest(token):
    return hashlib.sha256(token.lower().encode()).hexdigest()


def _tokens(text):
    for tok in TOKEN_RE.findall(text):
        yield tok
        parts = re.split(r"[-_]", tok)
        if len(parts) > 1:
            yield from parts


def check(root, digests=None, patterns=None, users=None, **_):
    user_digests = FORBIDDEN_USER_DIGESTS if users is None else users
    digests = FORBIDDEN_TOKEN_DIGESTS if digests is None else digests
    patterns = PATTERNS if patterns is None else patterns
    found = []
    for p in tracked(root):
        if p == SELF:
            continue
        try:
            text = (Path(root) / p).read_text(encoding="utf-8")
        except (UnicodeDecodeError, IsADirectoryError, FileNotFoundError):
            continue                                          # a binary asset, a submodule
        for n, line in enumerate(text.splitlines(), 1):
            if any(_digest(t) in digests for t in _tokens(line)):
                found.append(Finding(CHECK, p, n, "forbidden token"))
            if any(_digest(m.group(1)) in user_digests for m in HOME_RE.finditer(line)):
                found.append(Finding(CHECK, p, n, "forbidden home path"))
            for i, pat in enumerate(patterns):
                if pat.search(line):
                    key = line_hash(CHECK, line) if i == VENDOR_PATTERN else ""
                    found.append(Finding(CHECK, p, n, f"forbidden pattern {i}", key))
    return found
