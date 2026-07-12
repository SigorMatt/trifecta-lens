# RELEASE.md — publishing trifecta-lens

**Status: not published.** `trifecta-lens` is not on PyPI. The README says so, and
`tests/test_readme.py` fails the build if any code block carries an install command
that does not resolve today — so the repo cannot start claiming otherwise by
accident.

This file is the handoff: everything that is already done, everything that is left,
and the order.

---

## The one-way door

**A PyPI version number can never be reused.** If `0.1.0` goes up with a broken
README render, a wrong summary line, or a wheel missing its catalog, the only
remedy is `0.1.1` — the bad artifact stays visible forever. So the release workflow
runs the full gates *and* `make install-check` (which installs the built wheel into
a clean venv and demands a real finding out of it) **before** it uploads anything,
and the `pypi` environment is there so a human can require an approval on the run.

## Done (on `main`)

- Package builds; `trifecta-lens` **and** `trifecta-capture` console scripts install
  and run from a clean venv — proven by `make install-check`, which is in CI.
- Metadata: `authors`, `keywords`, `classifiers`, `[project.urls]`, and a summary
  line that no longer says "MCP manifest" (it says *inventory*, per D2/F1).
- `.github/workflows/release.yml` — publishes on a `v*` tag via **Trusted
  Publishing** (OIDC). There is no API token in this repo and there must never be.
- The install claim is gated: README says "Not on PyPI yet" and installs from git.

## Left to do — in this order

### 1. Create the PyPI project (you; needs your account)

The name `trifecta-lens` is unclaimed. On <https://pypi.org>:

- Account → **Publishing** → **Add a pending publisher** (this reserves the name and
  authorizes the workflow in one step, with no upload and no token):

  | field | value |
  |---|---|
  | PyPI project name | `trifecta-lens` |
  | Owner | `SigorMatt` |
  | Repository name | `trifecta-lens` |
  | Workflow name | `release.yml` |
  | Environment name | `pypi` |

- In the GitHub repo: **Settings → Environments → New environment → `pypi`**. Add
  yourself as a required reviewer if you want the upload to pause for approval.

### 2. Merge the flip PR (`release/pypi-flip`)

The README/test flip is **staged on its own branch, deliberately unmerged**, because
it is the one change that is *false until step 1 and step 3 have happened*. It flips
the README install line from the git URL to `pipx install "trifecta-lens[capture]"`
and flips the test that guards it, together, in one commit — the claim cannot become
true quietly, and it cannot rot back into a lie quietly either.

**Do not merge it before the first upload succeeds.** Between merging it and the
package existing, the README describes an install that 404s.

Recommended order: tag → workflow publishes → confirm `pipx install
"trifecta-lens[capture]"` works from a machine that has never seen this repo → merge
the flip.

### 3. Tag and release

```
git tag v0.1.0
git push origin v0.1.0
```

The workflow refuses to publish if the tag does not match `project.version` in
`pyproject.toml` — a tag is a version *claim*, and releasing 0.1.0's code under a
v0.2.0 name is not fixable after the fact.

### 4. Verify from outside

From a machine (or container) with no clone:

```
pipx install "trifecta-lens[capture]"
trifecta-capture --config .mcp.json --out inventory.json
trifecta-lens --inventory inventory.json
```

That is the Phase 3 exit claim, executed by a stranger. It has been verified against
the **local** wheel and the **git** install; the PyPI path is the one thing that
cannot be tested before publication.

## Bumping a version later

`pyproject.toml` `project.version` and the tag move together. The findings NDJSON
carries its **own** `schema_version` (`schema/findings.schema.json`) and does not
track the package version: consumers parse lines, not releases. Adding a field is a
minor schema bump; removing, renaming or retyping one is a major bump, and a test
fails the build if a field moves without it.
