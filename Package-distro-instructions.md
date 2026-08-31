# Package Distribution Instructions

What's still needed to turn `atlasboxpy_controller` and `atlasboxpy_repository`
from "editable-installable from a local clone" into "`pip install
atlasboxpy_controller` works for anyone, the same way `pip install fastapi`
or `pip install torch` does."

Both packages need every step below — they're independent PyPI projects.
Where a step differs between them, that's called out.

---

## Where things stand today

- Both packages have a real `pyproject.toml`, pass `ruff`/`mypy`/`pytest`,
  and build cleanly (`python -m build`) — see `packages/atlasboxpy_controller/`
  and `packages/atlasboxpy_repository/`.
- `.github/workflows/ci.yml` runs lint/type-check/tests for both packages
  and the `examples/` integration suite, matrixed across Python 3.10–3.12.
- `.github/workflows/publish.yml` exists but currently builds and publishes
  **only `atlasboxpy_controller`**, and only fires on a GitHub Release —
  it has never actually run.
- `git remote -v` is empty — **this repo has no GitHub remote yet.** Nothing
  below can be finished until it does.
- Both `pyproject.toml`s have placeholder URLs
  (`https://github.com/TODO/atlasboxpy_controller`, etc.) that need to
  become real before either package is published — a PyPI project page
  shows these as the Homepage/Repository/Issues links.
- Neither package's name has been checked for availability on PyPI or
  TestPyPI. This should be step one, before anything else below, since a
  name collision would mean revisiting the naming decision.

---

## 1. Reserve the names on PyPI

Check both are actually free before doing anything else:

```bash
pip index versions atlasboxpy_controller   # or just check the URL directly:
# https://pypi.org/project/atlasboxpy_controller/
# https://pypi.org/project/atlasboxpy_repository/
```

If either is taken, decide the fallback name now — every step after this
one assumes the final name.

---

## 2. Create the GitHub repo(s)

Per the earlier "extract now, decide repo split later" decision, this is
still one local repo with two packages under `packages/`. Before
publishing, decide:

- **Push this repo as-is** (one GitHub repo, two packages inside it) — the
  simplest path, and nothing here forces the eventual split to happen
  first.
- **Split now** into `AtlasboxPy/atlasboxpy_controller` and
  `AtlasboxPy/atlasboxpy_repository` as two separate GitHub repos.

Either way, once the remote(s) exist:

- Update `[project.urls]` in both `pyproject.toml`s — replace every
  `https://github.com/TODO/...` with the real URL.
- If you split into two repos, `packages/atlasboxpy_repository/` needs to
  become its own git history (it currently shares this repo's history) —
  `git subtree split` or a fresh `git init` + copy is the usual way to do
  this without losing the file history you care about.

---

## 3. Fill in packaging gaps

- **`atlasboxpy_controller` is missing a `py.typed` marker.**
  `atlasboxpy_repository` already has one
  (`packages/atlasboxpy_repository/src/atlasboxpy_repository/py.typed`).
  Without it, a consumer's own `mypy`/`pyright` run will treat
  `atlasboxpy_controller` as untyped and ignore its type hints entirely —
  exactly the "missing library stubs or py.typed marker" warning this
  project hit on itself earlier. Add an empty
  `packages/atlasboxpy_controller/src/atlasboxpy_controller/py.typed`.
- Double check `requires-python` (`>=3.10` for both) is actually still
  true — run the CI matrix once more after any dependency bumps.
- Confirm `dependencies` in both `pyproject.toml`s are true lower bounds,
  not just "whatever version I happened to test with."

---

## 4. Set up Trusted Publishing (OIDC) on PyPI

`publish.yml` already assumes this (`permissions: id-token: write`,
`environment: pypi`) — it does **not** work until you configure the PyPI
side:

1. Log into pypi.org → your account → "Publishing" → "Add a new pending
   publisher."
2. For each package, register: the GitHub org/user, the repo name, the
   workflow filename (`publish.yml`), and the environment name (`pypi`).
3. On GitHub, create an environment literally named `pypi` in each repo's
   Settings → Environments (add required reviewers here if you want a
   manual approval gate before every publish — recommended for the first
   several releases).
4. `atlasboxpy_repository` needs its **own** publish workflow — copy
   `publish.yml`, point `working-directory`/artifact paths at
   `packages/atlasboxpy_repository`, and register it as a separate
   pending publisher in step 2.

No PyPI API token is stored anywhere in this setup — that's the point of
trusted publishing over the older token-based flow.

---

## 5. Dry-run on TestPyPI first

Don't let the first real publish attempt be against the real index.
Manually, from each package's directory:

```bash
cd packages/atlasboxpy_controller
python -m build
pip install twine
twine check dist/*                 # validates metadata, README rendering
twine upload --repository testpypi dist/*
```

Then, in a throwaway venv:

```bash
python -m venv /tmp/testpypi-check && source /tmp/testpypi-check/bin/activate
pip install --index-url https://test.pypi.org/simple/ atlasboxpy_controller
python -c "import atlasboxpy_controller; print(atlasboxpy_controller.__file__)"
```

Repeat for `atlasboxpy_repository`. This catches metadata/README/classifier
problems for free, before they're permanent on the real index (PyPI does
not allow re-uploading a version number, ever, even to fix a typo).

---

## 6. Decide the versioning and release process

- Both packages are hardcoded at `version = "0.1.0"` right now. Decide:
  bump by hand before each release, or wire up `hatch version` /
  `setuptools_scm` to derive it from git tags. For two independently
  released packages, independent version numbers (not lock-stepped) is
  the norm — this is exactly how `torch`/`torchvision`/`torchaudio` do it.
- Pick a tagging convention if versions come from git tags — e.g.
  `atlasboxpy_controller-v0.1.0` / `atlasboxpy_repository-v0.1.0`, since a
  bare `v0.1.0` tag would be ambiguous with two packages in one repo.
- Update each package's own `CHANGELOG.md` before every release — a
  release without a changelog entry is the #1 thing that makes a package
  feel unmaintained to a new user evaluating it.

---

## 7. Cut the first real release

1. Bump the version in the package's `pyproject.toml`, commit.
2. Tag it and push the tag.
3. Create a GitHub Release from that tag — this is the event
   `publish.yml` actually listens for (`on: release: types: [published]`).
   Publishing a release, not just pushing a tag, is what fires the
   workflow.
4. Watch the Action run. If you added a required-reviewer gate on the
   `pypi` environment (step 4), you'll need to manually approve the
   deployment.
5. Confirm on pypi.org that the project page looks right — README
   rendering, classifiers, license, links.

---

## 8. After the first release

- `pip install atlasboxpy_controller` (no `--index-url` flag) from a
  clean machine/container — the real end-to-end check.
- Add PyPI version + CI status badges to both READMEs (this is purely
  cosmetic but is what makes a project *look* like `fastapi`/`starlette`
  at a glance — a badge row at the top of the README).
- Decide whether either package wants a dedicated docs site
  (ReadTheDocs, MkDocs + GitHub Pages) — not required for `pip install` to
  work, but both `fastapi` and `starlette` have one, and `docs/` already
  exists under `packages/atlasboxpy_controller/docs/` as a starting point.
- If brand protection for "Atlasbox"/"AtlasboxPy" beyond what the Apache
  2.0 license's trademark clause covers matters to you, trademark
  registration is a separate, non-technical track — worth starting in
  parallel, not blocking on anything above.
