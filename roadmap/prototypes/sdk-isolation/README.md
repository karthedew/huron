# Isolated SDK packaging experiment — not a delivered SDK

This ignored-only Phase001 probe compares the **actual current server regular
package** with an isolated **native-namespace candidate** while keeping these
accepted public imports:

```python
from huron.client import Client
from huron.catalog import Dataset
```

The experimental distribution name `huron-sdk` is approved only for this probe.
No registry, product naming, production source change or migration is approved.
The SDK wheel version is `0.0.0`. Its fixture HTTP JSON and URL are **not an
authoritative Huron API**. It implements no authentication, search, tus or
publication behavior. See [evidence](evidence.md) for results and limitations.

## Bounded question and hypothesis

Can disjoint distributions supply those imports, a lightweight HTTP seam and safe
independent install/uninstall? Does the current server initializer hide the SDK
when the portions occupy different import paths, and does removing only the
copied initializer remedy that hiding?

Expected observations are deliberately distinct:

- SDK-only resolved installation works without server, storage or array packages.
- Both wheel orders work when files occupy the **same** `site-packages/huron`.
- Current-server split-path and editable cases fail with exactly
  `ModuleNotFoundError.name == 'huron.client'` and `'huron.catalog'` in fresh
  interpreters. These are asserted negative observations, not skips or xfails.
- The copied native-namespace server supports both imports on split paths and in
  editable installs, with no overlapping wheel or installed RECORD paths.
- Uninstall/reinstall preserves every file hash owned by the surviving
  distribution. Removing the current editable server restores a functional SDK.

## Ownership, profile and prerequisites

Writer: `ses_ef14cad03ffeFX66GXaMblUr8z`, attempt 1, implementation role,
`prototype` activity. Dispatch profile **maximum**, configured Astra Max;
provider effort acceptance **not proven**, not measured by this probe.

Claims are cooperative coordination, not a sandbox:

- `source:repo:read`: live source, tests, docs, design, config and lockfiles.
- `plan:raw-phases:read`: product phase plans 001–010.
- `prototype:sdk:write`: this entire directory, including copied inputs, wheels,
  owned environments, caches, TMPDIR, logs and evidence.

The original directory was absent. [OWNER.json](OWNER.json) records provenance.
Every run uses exclusive creation and **refuses an existing run ID**. Unknown or
failed data are never cleared. No delegation, live mutation, shared `.venv` use,
global cache, service startup, Git staging or publication is performed.

Installed prerequisites used here:

- `/usr/local/bin/python3.12`: independent CPython **3.12.4**, base prefix
  `/usr/local`; never the repository `.venv` interpreter.
- `/home/karl/.local/bin/uv`: **0.12.19**. The driver locates `uv` on PATH and checks
  this version. The root `python` driver is CPython 3.14.0; every build and test
  environment uses the explicit independent 3.12.4 interpreter.
- HTTPS access to PyPI release metadata and hash-pinned `files.pythonhosted.org`
  wheels. No Python downloads. Package resolution/build/install is offline after
  those explicit downloads, with only each run's pinned wheelhouse available.
- Existing `/tmp/opencode` is the **read-only execution cwd**, outside the repo.
  No file is created there. HOME, TMPDIR, XDG and uv cache are under the run.

The driver removes inherited environment configuration/credentials before
downloads and commands. `--no-config`, `--no-project` where available, explicit
source/interpreter paths, `--no-sources`, `UV_PYTHON_DOWNLOADS=never`,
`UV_NO_MANAGED_PYTHON=1` and `UV_LINK_MODE=copy` prevent implicit environment reuse.
It never runs root `uv run` or `uv sync`. Each owned subprocess is bounded to
180 seconds and has its own checked process group.

## Reproduce from the repository root

```sh
python -I -B roadmap/prototypes/sdk-isolation/probe.py --repo /home/karl/repo/huron --run-id qualification-02
python -I -B roadmap/prototypes/sdk-isolation/probe.py --repo /home/karl/repo/huron --run-id qualification-03
python -I -B roadmap/prototypes/sdk-isolation/check_artifacts.py --run qualification-02 --run qualification-03 --receipt artifact-gate-01.json
```

These run IDs are retained evidence and cannot be reused. For independent review,
substitute two **new** IDs such as `review-01-a` / `review-01-b`, and a new receipt
name. Do not remove existing directories to obtain a pass. The probe intentionally
fails if Git-visible source or index differs from the recorded initial fingerprints;
reconcile such drift with the parent instead of updating the constants silently.

The first command with `--run-id qualification-01` was also executed and failed;
see [the retained failure](first-run-failure.md). Two later complete fresh runs,
not reuse of that partial run, are the qualification evidence.

All subprocess argv/cwd/exit/output are in each run's `logs/`; the final
`result.json` indexes them. Runs also retain driver copies/hashes, source copies
and hashes, original `uv.lock`, wheel inventories, metadata closure reports,
hashed dependency pins and before/after source/index manifests.

## Inputs and collaboration

[sdk/pyproject.toml](sdk/pyproject.toml) explicitly selects `src/huron` using
Hatchling. There is **no** SDK `src/huron/__init__.py`; only `huron.client` and
`huron.catalog` regular subpackages are included. Public classes live in their
owner's `interface/` with root reexports. No server model or type-only server import
is used. Composition is direct:

```text
Client owns httpx.Client + transport lifetime
  -> Datasets borrows that HTTP client, requests and maps the labelled fixture
  -> immutable SDK Dataset owns its UUID/nonempty-title value invariant
```

For example, only within this packaging fixture:

```python
from uuid import UUID
import httpx
from huron.client import Client
from huron.catalog import Dataset

identity = UUID("00000000-0000-0000-0000-000000000001")
transport = httpx.MockTransport(lambda request: httpx.Response(
    200, json={"id": str(identity), "title": "PACKAGING FIXTURE"}
))
with Client(transport=transport) as client:
    dataset: Dataset = client.datasets.get(identity)
```

The simplest collaboration was chosen instead of an SDK facade over server Core,
an abstract service hierarchy or a mandatory `client.catalog` wrapper. HTTPX's
external transport is the only mock boundary. The synchronous choice is enough
for packaging evidence; it does not decide the production sync/async surface.
`Client()` has no requests or credential acquisition/discovery effects and owns
the injected transport until context exit/close. Domain and server auth guarantees
are not delegated to this fixture.

The existing `tests/ingest_client.py` and `tests/unit/conftest.py` were inspected
before adding the probe cases. They depend on server `ManifestFile`, FastAPI,
dev-header/bootstrap and numbered-part ingest semantics; reusing them would
invalidate SDK isolation. Existing security tests demonstrate HTTPX MockTransport,
but no package ownership/SDK wheel helper was found. No pytest environment or
fixture discovery command was needed; the assumptions were explicit in those files.

## Exact input pins

Runtime wheel versions and SHA-256/URLs are read and verified from the unedited
root `uv.lock`: HTTPX 0.28.1, anyio 4.14.2, certifi 2026.7.22, httpcore 1.0.9,
h11 0.16.0, idna 3.18, typing-extensions 4.16.0. SDK METADATA has one requirement:
`httpx==0.28.1`. The actual active wheel dependency closure and clean installed
inventory must equal those seven dependencies plus `huron-sdk==0.0.0`.

Build inputs use root-locked packaging 26.3, pathspec 1.1.1 and pluggy 1.6.0, plus
[hash-pinned extras](build-extras.json): Hatchling **1.32.4**, tomlkit 0.15.1,
trove-classifiers 2026.9.21.13 and PEP 660's editables 0.5. Build closure is checked
for Hatchling plus its observed dynamic editable requirement, not just METADATA.
Hatchling **1.32.1 was rejected before installation** because official PyPI marks
it yanked, “Broken by change to types.” The root project's unpinned build-system
requirement is constrained externally; its copied `pyproject.toml` is unedited.

For each run the server build inputs are pure copies of root `pyproject.toml`,
`README.md` and `src/huron`; symlinks/special files are rejected and bytecode is
excluded. The native candidate differs solely by removal of **its own copied**
`src/huron/__init__.py`. No configuration adjustment was necessary. All source
payloads must match wheel hashes, and both copies must remain unchanged after
builders/installers finish. `SOURCE_DATE_EPOCH=1700000000` fixes wheel timestamps.

## Applicable gates and evidence limits

The local gate is two complete independent fresh runs, all positive/negative and
install/uninstall cases, authored ignored-text whitespace/syntax/local-path checks,
root `git diff --check`, `git status --short --untracked-files=all`, artifact
`git check-ignore`, empty `git ls-files roadmap`, and exact source/index preservation.
`check_artifacts.py` also requires byte-identical wheels, dependency locks, source
hashes and driver hashes across the two runs. It hashes authored text, not vendored
third-party text or unchanged copies of pre-existing source. Those inputs have
separate content-integrity checks.

**Deferred — do not run concurrently with Starlight's claims:**

```sh
UV_CACHE_DIR=/tmp/opencode/huron-effort-uv-cache make docs
python roadmap/check_docs.py
```

Cwd is repository root. Parent must arrange these after Starlight releases
`build:docs`, `cache:uv`, `env:python`, followed by independent maximum review in
fresh environments after this writer is terminal. This self-check is partial,
not an independent review, full Phase001 PASS or product PASS. No live-code
Python/frontend/agent suites apply to this ignored probe alone.

## Primary references consulted

- [PyPA native namespace guide](https://packaging.python.org/en/latest/guides/packaging-namespace-packages/)
- [Hatch wheel builder and explicit selection](https://hatch.pypa.io/1.16/plugins/builder/wheel/)
- [Hatchling release history](https://hatch.pypa.io/dev/history/hatchling/)
- [Yanked Hatchling 1.32.1 release metadata](https://pypi.org/pypi/hatchling/1.32.1/json)
- [Hatchling 1.32.4 release metadata](https://pypi.org/pypi/hatchling/1.32.4/json)
- [Editables 0.5 release metadata and public usage](https://pypi.org/pypi/editables/0.5/json)
- [HTTPX 0.28.1 MockTransport source](https://raw.githubusercontent.com/encode/httpx/0.28.1/httpx/_transports/mock.py)
- [HTTPX 0.28.1 Client lifecycle and transport source](https://raw.githubusercontent.com/encode/httpx/0.28.1/httpx/_client.py)

The initially attempted Hatch GitHub raw tag URLs for 1.32.1 returned 404;
official PyPI release metadata, release history and installed 1.32.4 APIs were
used instead. No unverified API or yanked-build fallback is part of the probe.
