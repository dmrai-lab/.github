# .github

Static guards for the public dmrai-lab repositories, written once and called by each of them. The package `guards/` is stdlib-only Python (nothing to install); the reusable workflow runs in seconds on a free GitHub runner. There is no schedule and no paid compute.

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
      strict-test-dirs: false                          # true: each test directory must itself be named
```

The guards run at the commit of the workflow file the caller pins (`@main`, a tag or a SHA). Locally: `python -m guards <check> <repo-root>` from the directory that holds `guards/`, with `<check>` one of the four names below or `all`. Exit status 1, one `file:line: check: reason` line per finding.

## The guards

| check | flags |
|---|---|
| `private-ids` | a tracked file naming a project, service, machine or local path outside the public project. Words are stored as sha256 hashes and runtime-joined fragments; a finding names file:line and the pattern index, never the text. No allow-list. |
| `ci-coverage` | a directory holding `test_*.py` (including `pkg/**/tests`) that no workflow file in `workflows` names. Without `strict-test-dirs`, a whole-root `pytest tests/` covers what lies below it. |
| `hidden-defaults` | in package code (not tests): `<expr> or <number>`, `<mapping>.get(<key>, <number>)`, `getattr(x, k, <number>)`. A number standing in for a missing input is how a certified quantity ends up resting on a value nobody stated. |
| `history-wording` | docstrings containing "previously", "no longer", "was replaced", "the old", a sentence-initial "Now", or "used to" with a pronoun subject. A docstring says what a thing is; history belongs in the pull request or issue. |

## Accepting a case

Each repository states its accepted cases in `.guards-allow` at its root, one per line:

```
path/to/module.py:3fa91c07d2 pre-existing, tracked in dmrai-lab/<repo>#<issue>
```

The token after the colon is printed with every finding (`[allow: path:hash]`); it hashes the guard name and the line's text with whitespace collapsed, so an entry survives the line moving and lapses when the line changes. The reason is required. `python -m guards <check> <root> --record "<reason>"` appends every current finding (the one-time baseline of a repository). Lines starting with `#` are comments.

## Tests

`python -m pytest tests` (fixtures for each guard).

## Licence

Dual-licensed as the other code repositories: see `LICENSING.md`.
