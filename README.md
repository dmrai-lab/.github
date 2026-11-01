# .github

Shared CI for the public dmrai-lab repositories, written once and called by each of them: the static guards, and the integration check of the five packages. Both run on free GitHub runners; there is no schedule and no paid compute.

The static guards are the package `guards/` (stdlib-only Python, nothing to install) and run in seconds. The integration check is described [below](#the-integration-check).

This repository holds no organisation-wide community files (profile, CONTRIBUTING, SECURITY): they would apply to every repository.

## Calling it

```yaml
# .github/workflows/guards.yml of a repository
name: Guards
on: [push, pull_request]
jobs:
  guards:
    uses: dmrai-lab/.github/.github/workflows/guards.yml@main
    with:
      src: dmipy_fit                                   # package paths for the two AST guards (default: detected)
      workflows: .github/workflows/tests.yml           # files that collect the tests (default shown)
```

The guards run at the commit of the workflow file the caller pins (`@main`, a tag or a SHA). Locally: `python -m guards <check> <repo-root>` from the directory that holds `guards/`, with `<check>` one of the four names below or `all`. Exit status 1, one `file:line: check: reason` line per finding.

## The guards

| check | flags |
|---|---|
| `private-ids` | a tracked file naming a project, service, machine or local path outside the public project. Words are stored as sha256 hashes and runtime-joined fragments; a finding names file:line and the pattern index, never the text. No allow-list. |
| `ci-coverage` | a tracked `test_*.py` that no `pytest` invocation in the `workflows` files collects. An invocation collects a file when it names the file, a directory holding it or a glob matching it, or runs without paths (the repository's `testpaths`, else everything); `--ignore` removes it again; `pytest $VAR` counts every path-like token of its workflow file. |
| `hidden-defaults` | in package code (not tests): `<expr> or <number>`, `<mapping>.get(<key>, <number>)`, `getattr(x, k, <number>)`. A number standing in for a missing input is how a certified quantity ends up resting on a value nobody stated. |
| `history-wording` | docstrings containing "previously", "no longer", "was replaced", "the old", a sentence-initial "Now", or "used to" with a pronoun subject. A docstring says what a thing is; history belongs in the pull request or issue. |

## Accepting a case

Each repository states its accepted cases in `.guards-allow` at its root, one per line:

```
path/to/module.py:3fa91c07d2 pre-existing, tracked in dmrai-lab/<repo>#<issue>
```

The token after the colon is printed with every finding (`[allow: path:hash]`); it hashes the guard name and the line's text with whitespace collapsed, so an entry survives the line moving and lapses when the line changes. The reason is required. `python -m guards <check> <root> --record "<reason>"` appends every current finding (the one-time baseline of a repository). Lines starting with `#` are comments.

## The integration check

`integration.yml` installs the mains of dmipy-replay, dmipy-sim, dmipy-fit, dmipy-design and dmipy-tract together (editable, from git: the calling repository at its own commit, the other four at main) and runs the smoke set `integration/test_smoke.py` on them. A package's own CI installs its dependencies from PyPI or from a pinned commit; this is where a change in one package meets the current main of the others. The smoke set:

| check | breaks when |
|---|---|
| every module of the five imports, every name of an `__all__` exists, every `dmipy_*` import statement in the shipped code (function bodies included) names a module and names that exist | one package moves a module or a name another still imports |
| dmipy-sim walks a cylinder (400 walkers), builds a replay pack and writes it; dmipy-replay's reader reads the file and replays it, along the axis within the standard error of the closed form | the reader refuses what the producer writes, or the two disagree on the signal |
| dmipy-fit's `MonteCarloReplay` equals the pack's own replay at a pose | the fit's replay model and the reader part |
| dmipy-design's `certify` certifies the pack against a scanner class | the certificate and the pack's fidelity terms part |
| dmipy-tract tracks a constructed FOD field and writes the `.tck` through dmipy-sim | tract and the SH basis or the file writer part |

CPU only: about 40 s of runner time in all, of which the installs are about 20 s and the tests about 10 s. The mains name releases of each other that PyPI does not hold yet, so the five are installed with `--no-deps` and `integration/requirements.py` prints the third-party requirements of the checkouts for the rest.

```yaml
# .github/workflows/integration.yml of a package repository
name: Integration
on:
  push:
    branches: [ main ]
  pull_request:
  repository_dispatch:
    types: [ dmrai-main-changed ]            # a dependency's main changed
jobs:
  integration:
    uses: dmrai-lab/.github/.github/workflows/integration.yml@main
    with:
      notify: dmipy-fit dmipy-design         # told on a push to main
    secrets:
      DMRAI_DISPATCH_TOKEN: ${{ secrets.DMRAI_DISPATCH_TOKEN }}
```

A push to main sends each repository of `notify` a `repository_dispatch` event `dmrai-main-changed`, and that repository runs the check at its main. The default `GITHUB_TOKEN` cannot dispatch to another repository: the secret `DMRAI_DISPATCH_TOKEN` is a fine-grained token (resource owner dmrai-lab, the notified repositories, permission Contents: read and write). Without it the notice is skipped and the run says so; the caller's own push and pull-request runs need no secret.

The smoke set is read from the `ref` input (default `main`) of this repository; a workflow called from here passes its own commit.

The smoke set is the contract between the packages: a deliberate change to an API it uses changes `integration/test_smoke.py` here in the same sitting, and the pull request that makes the change shows the check red until it does.

## Tests

`python -m pytest tests` (fixtures for each guard).

## Licence

Dual-licensed as the other code repositories: see `LICENSING.md`.
