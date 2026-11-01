"""``integration/requirements.py``: the third-party requirements of package checkouts, without the dmipy-* ones."""
import subprocess
import sys
import textwrap
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "integration" / "requirements.py"


def _checkout(root, name, dependencies):
    (root / name).mkdir()
    lines = "".join(f'    "{d}",\n' for d in dependencies)
    (root / name / "pyproject.toml").write_text(f'[project]\nname = "{name}"\nversion = "1"\ndependencies = [\n{lines}]\n')
    return str(root / name)


def test_the_requirements_are_the_third_party_ones_of_every_checkout_once_each(tmp_path):
    sim = _checkout(tmp_path, "dmipy-sim", ["jax>=0.6.2", "numpy>=2.0", "dmipy-replay>=0.1,<0.3"])
    fit = _checkout(tmp_path, "dmipy-fit", ["dmipy_sim>=3,<4", "Dmipy-Replay >= 0.2", "numpy>=2.0", "scipy>=1.10"])
    bare = _checkout(tmp_path, "dmipy-design", [])
    out = subprocess.run([sys.executable, str(SCRIPT), sim, fit, bare], check=True, capture_output=True, text=True).stdout
    assert out.split() == ["jax>=0.6.2", "numpy>=2.0", "scipy>=1.10"]
