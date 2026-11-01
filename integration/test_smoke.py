"""The smoke set of the integration check: the mains of dmipy-replay, dmipy-sim, dmipy-fit, dmipy-design and dmipy-tract
installed together, each package doing its one job on what another produced.

1. Imports. Every package imports with every module of it, exports every name its ``__all__`` lists, and every
   ``dmipy_*`` import statement in the shipped code of the five (function bodies included) names a module and the
   names that exist: a module or name one package moved and another still imports fails here.
2. The pack. dmipy-sim walks a cylinder along z and builds a replay pack, dmipy-replay's reader reads the file and replays
   it: along the axis the signal is the free closed form, within the standard error of the walk's own sample.
3. dmipy-fit's ``MonteCarloReplay`` is that pack's replay at a pose.
4. dmipy-design's ``certify`` certifies that pack against a scanner class.
5. dmipy-tract tracks a constructed FOD field and writes the tractogram through dmipy-sim.

CPU only, a few hundred walkers, seconds. A third-party module the environment lacks is a warning, never a pass or a
failure of its own: the check is about the five packages and one another.
"""
import ast
import importlib
import importlib.util
import pkgutil
import warnings
from pathlib import Path

import numpy as np
import pytest

PACKAGES = ("dmipy_replay", "dmipy_sim", "dmipy_fit", "dmipy_design", "dmipy_tract")

D = 2e-9                    # m^2/s, the diffusivity the walk steps with
N_WALKERS = 400
T_WALK = 0.04               # s, the one storage window of the pack
RADIUS = 5e-6               # m
B = 1e9                     # s/m^2
DELTA, BIG_DELTA = 0.006, 0.02          # s, the pulsed-gradient timing of the replayed acquisition
Z_SE = 5.0                  # a sample mean is held to this many of its standard errors


def _own(name):
    return name.split(".")[0] in PACKAGES


def _import(name):
    """The module ``name``; ``None`` (with a warning) when a third-party module it needs is not installed. A missing
    dmipy module, and any other failure of the import, raises."""
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError as exc:
        if _own(exc.name or ""):
            raise
        warnings.warn(f"{name} not imported: {exc.name} is not installed")
        return None


def _modules(package):
    """Every module of ``package`` outside its tests, found by importing the packages on the way down."""
    pkg = importlib.import_module(package)
    failed = []
    found = [i.name for i in pkgutil.walk_packages(pkg.__path__, package + ".", onerror=failed.append)]
    return [n for n in dict.fromkeys(found + failed) if "tests" not in n.split(".") and n.split(".")[-1] != "__main__"]


def _shipped_files(package):
    root = Path(importlib.util.find_spec(package).submodule_search_locations[0])
    return [p for p in sorted(root.rglob("*.py")) if "tests" not in p.relative_to(root).parts]


def _installed(name):
    try:
        return importlib.util.find_spec(name) is not None
    except ModuleNotFoundError:
        return False


def _unresolved(node):
    """What the ``dmipy_*`` import statement ``node`` names that does not exist: a module, or a name of a module."""
    if isinstance(node, ast.Import):
        asked = [(a.name, []) for a in node.names if _own(a.name)]
    elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module and _own(node.module):
        asked = [(node.module, [a.name for a in node.names if a.name != "*"])]
    else:
        return []
    missing = []
    for name, wanted in asked:
        try:
            module = _import(name)
        except ImportError as exc:                       # the module is gone, or an import of its own is
            missing.append(f"{name} ({exc})")
            continue
        if module is not None:
            missing += [f"{name}.{w}" for w in wanted if not hasattr(module, w) and not _installed(f"{name}.{w}")]
    return missing


@pytest.mark.parametrize("package", PACKAGES)
def test_a_package_imports_with_every_module_and_exports_its_api(package):
    pkg = importlib.import_module(package)
    missing = [n for n in getattr(pkg, "__all__", ()) if not hasattr(pkg, n)]
    assert not missing, f"{package}.__all__ lists {missing}, which the package does not define"
    for name in _modules(package):
        _import(name)


def test_every_dmipy_import_in_the_shipped_code_resolves():
    unresolved = []
    for package in PACKAGES:
        for path in _shipped_files(package):
            for node in ast.walk(ast.parse(path.read_text())):
                unresolved += [f"{path.parent.name}/{path.name}:{node.lineno} imports {name}" for name in _unresolved(node)]
    assert not unresolved, "imports of a module or name that does not exist:\n" + "\n".join(dict.fromkeys(unresolved))


def _envelope():
    """The envelope the pack is walked for and states: the Connectom class's preset (its band and per-axis amplitude),
    the contact tier up to 100 um/s."""
    from dmipy_replay import envelope_of
    return envelope_of("connectom", rho2_max=1e-4)


def _free_se(b, n):
    """The standard error of the mean of ``cos(phase)`` over ``n`` free walkers, the phase variance being ``2 b D``."""
    return np.sqrt(((1 + np.exp(-4 * b * D)) / 2 - np.exp(-2 * b * D)) / n)


@pytest.fixture(scope="module")
def pack(tmp_path_factory):
    """dmipy-sim walks, builds and writes the pack; dmipy-replay's reader reads the file."""
    import dmipy_replay as dr
    from dmipy_sim import Cylinder, build_replay_pack, walk
    w = walk(Cylinder(radius=RADIUS, orientation=(0, 0, 1)), N_WALKERS, T_WALK, diffusivity=D, seed=11, require_gpu=False,
             envelope=_envelope())
    path = tmp_path_factory.mktemp("rpk") / "cylinder.rpk"
    build_replay_pack(w, id="integration/cylinder", license="CC0-1.0", citation="integration smoke", out_path=str(path))
    return dr.read_rpk(str(path))


def test_the_reader_replays_the_pack_to_the_closed_form_along_its_axis(pack):
    import dmipy_replay as dr
    assert pack.n_walkers == N_WALKERS
    along, across = pack.replay(dr.pgse([[0, 0, 1], [1, 0, 0]], DELTA, BIG_DELTA, bvalues=[B, B]))
    se = _free_se(B, N_WALKERS)
    assert along == pytest.approx(np.exp(-B * D), abs=Z_SE * se)           # free along the axis
    assert across - along > Z_SE * se                                      # restricted across it


def test_the_fit_replay_model_is_the_packs_replay_at_a_pose(pack):
    from dmipy_fit.core.acquisition_scheme import AcquisitionScheme
    from dmipy_fit.signal_models.replay_models import MonteCarloReplay
    directions = np.array([[0.0, 0.0, 1.0], [0.0, 0.0, 1.0], [1.0, 0.0, 0.0]])
    scheme = AcquisitionScheme.from_pgse(np.array([0.0, B, B]), directions, DELTA, BIG_DELTA)
    signal = MonteCarloReplay(pack)(scheme, mu=[0.0, 0.0])                 # the pack's axis along z
    np.testing.assert_allclose(signal, pack.replay(scheme.sequence, tissue=None, tol=None), atol=2e-6)
    assert signal[2] > signal[1]


@pytest.mark.filterwarnings("ignore:certifying from")
def test_the_design_certificate_certifies_the_pack_against_a_scanner_class(pack):
    from dmipy_design.certify import certify, replay_envelope
    scanner = replay_envelope(G_max=0.1, slew_rate_max=100.0, raster=1e-4, name="integration")
    certificate = certify(pack, scanner, eps=5e-2, K_grid=(4, 8), steps=30, restarts=2)
    assert certificate.n_walkers == N_WALKERS and certificate.T == pytest.approx(T_WALK)
    assert certificate.K <= certificate.K_stored
    assert certificate.f_c == pytest.approx(certificate.K / (2 * certificate.T))
    assert certificate.truncation == pytest.approx(pack.fidelity["terms"]["truncation"])


def test_tract_tracks_a_constructed_fod_field_and_writes_it_through_dmipy_sim(tmp_path):
    from dmipy_tract import FODField, sh_matrix, track
    n, step = 10, 0.5
    along_x = np.array([[1.0, 0.0, 0.0]])
    field = FODField(np.tile(sh_matrix(8, along_x)[0], (n, n, n, 1)), np.eye(4), np.ones((n, n, n), bool))
    streamlines = track(field, [[4.3, 4.3, 4.3]], rule="deterministic", step_mm=step, sphere=along_x,
                        initial_directions=along_x, key=0)
    points = streamlines[0]
    np.testing.assert_allclose(np.diff(points, axis=0), np.tile([step, 0.0, 0.0], (len(points) - 1, 1)), atol=1e-5)
    assert points[:, 0].min() < 0.0 < 9.0 < points[:, 0].max()             # to both faces of the grid
    streamlines.to_tck(str(tmp_path / "streamline.tck"))
    assert (tmp_path / "streamline.tck").stat().st_size > 0
