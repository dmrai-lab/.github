"""The third-party requirements of the dmrai-lab package checkouts.

``python integration/requirements.py <checkout> ...`` prints, one per line, every ``[project].dependencies`` entry of the
checkouts that is not a ``dmipy-*`` distribution. The mains name releases of each other that PyPI does not hold yet
(``dmipy-sim>=3`` beside a main at 2.x), so the integration workflow installs the checkouts without resolving each
other and installs what this prints for the rest.
"""
import re
import sys
import tomllib
from pathlib import Path

OWN = re.compile(r"\s*dmipy[-_.]", re.IGNORECASE)


def third_party(checkout):
    """The ``[project].dependencies`` of ``checkout/pyproject.toml`` that are not ``dmipy-*`` distributions."""
    project = tomllib.loads((Path(checkout) / "pyproject.toml").read_text())["project"]
    return [d for d in project.get("dependencies", []) if not OWN.match(d)]


if __name__ == "__main__":
    print("\n".join(sorted({d for checkout in sys.argv[1:] for d in third_party(checkout)})))
