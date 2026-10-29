# Prototype evidence: independent SDK distribution and namespace coexistence

**Scope result:** the bounded packaging assertions were satisfied in two clean,
independent runs. **Qualification status: self-check partial**, pending the shared
documentation gates and independent maximum review. No product PASS, released SDK,
live namespace migration or Phase001 completion is claimed.

## Authority and question

- Design sources read: Phase001 decisions/prototypes and Phase008 production SDK
  plans, `design/raw-first.md`, `CONTEXT.md`, actual root packaging/lock/source and
  relevant existing test helpers. Lifecycle and OOP canonical skills were read.
- Writer `ses_ef14cad03ffeFX66GXaMblUr8z`, implementation role, prototype activity,
  attempt 1. Dispatch `649dbd85-0646-4194-87f1-7851dd97e72e` records **maximum**.
  Configured selection is Astra Max; provider effort acceptance remains **not
  proven**. No provider-effort telemetry was inferred from model identity.
- Exact claims: `source:repo:read`, `plan:raw-phases:read`, `prototype:sdk:write`.
  Only the previously absent `roadmap/prototypes/sdk-isolation/` was written.
  Claims are cooperative, not a sandbox. No nested worker, restart, replay,
  classification escalation, root environment use or service mutation occurred.
- Falsifiable question: accepted imports plus a lightweight HTTP collaboration,
  disjoint distribution ownership, independent uninstalls, and explicit current
  namespace-hiding counterexamples versus a native-namespace remedy.
- Hypothesis and exact reproduction prerequisites are in [README](README.md).

## Commands, environment and retained results

All entry commands ran from `/home/karl/repo/huron`:

```sh
python -I -B roadmap/prototypes/sdk-isolation/probe.py --repo /home/karl/repo/huron --run-id qualification-01
python -I -B roadmap/prototypes/sdk-isolation/probe.py --repo /home/karl/repo/huron --run-id qualification-02
python -I -B roadmap/prototypes/sdk-isolation/probe.py --repo /home/karl/repo/huron --run-id qualification-03
python -I -B roadmap/prototypes/sdk-isolation/check_artifacts.py --run qualification-02 --run qualification-03 --receipt artifact-gate-01.json
```

| Run | Exit and outcome | Completed observations | SDK behavior outcomes | Subcommands |
| --- | --- | ---: | ---: | ---: |
| `qualification-01` | 1; retained incomplete editable-build closure failure | 34 | 391 | 190; 189 exit 0, 1 exit 1 |
| `qualification-02` | 0; bounded assertions satisfied | 59 | 595 | 340, all exit 0 |
| `qualification-03` | 0; bounded assertions satisfied | 59 | 595 | 340, all exit 0 |

The first failure is explained in [first-run-failure.md](first-run-failure.md).
Its missing `editables` build requirement was corrected with an official,
non-yanked SHA-256 pin, not a forced install or fallback. No failed artifact was
overwritten. The two complete runs each fetched their own inputs and used their
own caches, TMPDIR, wheels and 13 fresh unseeded virtual environments.

Detailed receipts:

- [Run 02 result and complete command/log index](runs/qualification-02/result.json)
- [Run 03 result and complete command/log index](runs/qualification-03/result.json)
- [Run 02 original lockfile copy](runs/qualification-02/input-uv.lock)
- [Run 02 complete dependency lock](runs/qualification-02/dependency-lock.json)
- [Run 02 exact build/source hashes](runs/qualification-02/source-inputs.json)
- [Run 02 exact driver hashes](runs/qualification-02/driver-hashes.json)
- [Run 02 SDK wheel metadata closure](runs/qualification-02/huron-sdk-closure.json)
- [Run 02 wheel inventories](runs/qualification-02/wheel-inventories.json)

Build/test runtime was independent CPython **3.12.4**
(`/usr/local/bin/python3.12`, not root `.venv`) with **uv 0.12.19**. The driver
command `python` itself is CPython 3.14.0. All installed-artifact checks use
`-I -B`, in `/tmp/opencode` outside the repository cwd, with only owned installed
paths explicitly added for the split-path experiment. No output is written there.
Each run's environment is recorded in `isolation.json`; no inherited credentials
or configuration are passed to installers.

Runtime pins are HTTPX 0.28.1, anyio 4.14.2, certifi 2026.7.22, httpcore 1.0.9,
h11 0.16.0, idna 3.18 and typing-extensions 4.16.0. Build pins are Hatchling
1.32.4, packaging 26.3, pathspec 1.1.1, pluggy 1.6.0, tomlkit 0.15.1,
trove-classifiers 2026.9.21.13 and editables 0.5. Every wheel is hash-checked before
use; build and runtime resolution sees only each run's pinned wheelhouse. The
SDK-only install performs normal dependency resolution, **without `--no-deps`**.

The suggested Hatchling 1.32.1 was verified as yanked (“Broken by change to types”)
and never installed. The official release history and non-yanked 1.32.4 metadata
were checked; installed hook signatures and dynamic PEP 660 requirements are
recorded in the logs. Root build configuration was not changed.

## Observations answering the question

### Lightweight SDK and real HTTP seam

- `from huron.client import Client` and `from huron.catalog import Dataset` resolve
  to the SDK wheel, with public definitions in `interface/` and root reexports.
- The **4,761-byte SDK wheel** contains eight Python source files, three metadata
  files and **no** `huron/__init__.py` or server files. Static AST inspection covers
  all **14 import statements**, including any type-only branches.
- SDK METADATA requires only `httpx==0.28.1`; the actual active transitive closure
  and fresh installed inventory have exactly eight distributions including the
  SDK. Server/Core, FastAPI, SQLAlchemy, asyncpg, storage and array packages are
  absent. `uv pip check` succeeds for the SDK-only environment.
- A live meta-path guard actively rejects **22 forbidden import prefixes**, then
  records **zero** attempted forbidden imports during SDK behavior checks, even
  where real server files are installed. An audit guard records zero socket,
  subprocess or home/credential-file effects in those checks.
- There are **17 distinct SDK behavior cases**, repeated in **35 fresh processes**
  per complete run = **595 outcomes**: effect-free default construction; successful
  HTTP request and SDK-owned immutable value; 404; 500; ten malformed JSON/value
  responses; transport exception; caller exception; invalid input before HTTP.
  Successful/error responses and client transports close; close is idempotent and
  a closed client rejects requests. Only external HTTP I/O is mocked.

### Namespace behavior matrix

Every row is tested in both `server → SDK` and `SDK → server` orders (for split
paths, both path orders). Server installations intentionally use `--no-deps` only
for file ownership and package-resolution evidence, not health claims.

| Installation layout | Current regular server | Native copied-server candidate |
| --- | --- | --- |
| Wheels in one site-packages directory | Accepted imports and SDK behavior succeed | Accepted imports and SDK behavior succeed |
| Separate installed import paths | Both accepted imports fail with exact `ModuleNotFoundError.name` | Both imports and SDK behavior succeed |
| Real `uv pip install --editable` copied server plus SDK wheel | Both accepted imports fail with exact `ModuleNotFoundError.name` | Both imports and SDK behavior succeed |
| Remove server, retain SDK | SDK becomes/remains fully functional | SDK remains fully functional |
| Remove SDK, retain server | Representative server packages resolve; every owned file hash preserved | Same resolution/hash preservation |

Current-server hiding was required and observed at **10 fresh-process checkpoints**
per full run: two split-path checks and eight editable install/restore/reinstall
checks. Each asserts **both** missing modules, for **20 exact expected import
failures**. A generic failed subprocess, changed exception type/name, or accidental
successful import would fail the probe. No xfail or skip is involved.

The regular server initializer fixes `huron.__path__` to its own directory even
when the SDK namespace portion appears earlier on `sys.path`. Combining both
distributions into one physical directory conceals this limitation; a same-site
wheel smoke test alone is not sufficient qualification.

### Ownership, uninstalls and reproducibility

- All wheel paths and every RECORD row are inspected, not only initializers.
  Both SDK/server wheel RECORD intersections are empty. All installed paired
  RECORD intersections are empty, including metadata, `.pth`, and generated
  executable paths outside `site-packages`.
- There are eight install-order scenarios per run: two layouts (wheel/editable),
  two server variants and two install orders. Each independently uninstalls both
  distributions, checks every surviving file hash/import behavior, restores both,
  and explicitly reinstalls both in the original order.
- Preserved installed path counts are **15 SDK paths**, **185 current server wheel
  paths**, **184 native server wheel paths**, and **11 server editable paths**.
  Editable source copies are separately hash-checked after all installer actions.
  All paths owned by the removed distribution disappear; none owned by its
  survivor disappear or change bytes.
- The current server build copied **176 source files** plus root README and
  pyproject. The native source copy differs only by removal of its own
  `src/huron/__init__.py`; configuration is byte-identical. Native/current wheel
  common contents differ only in the required RECORD update.
- The two complete runs have byte-identical SDK/current/native wheels, identical
  dependency pins, source input hashes and driver hashes. No cache or environment
  was reused between the runs. This is established by the artifact gate, not
  assumed from matching summaries.

| Wheel | Bytes | SHA-256 |
| --- | ---: | --- |
| SDK `huron_sdk-0.0.0-py3-none-any.whl` | 4,761 | `e51ba6ec7368bdb497e1b96bdc64cd2850f944b4cdde59eb43337386f47d3080` |
| Current `huron-0.1.0-py3-none-any.whl` | 350,042 | `64bb5568e909003507991ba1a2d725b042ffc71b66e6f80c8af9f3bc90a49fe0` |
| Native candidate `huron-0.1.0-py3-none-any.whl` | 349,642 | `de21d4b37d4f89467c8934fb628bc679d86f82ffc0c76e2dedf2a8e8d4479310` |

## Preservation and gate disposition

Initial status: **51 dirty tracked paths + 4 untracked paths**, with no staged
diff. All **553 Git-visible file/deletion entries** and index bytes were hashed
before and after each run. The directory was initially absent; no unknown files
were overwritten. No live code, test, docs, design, plan, configuration or lockfile
was edited, staged or deleted.

| Preserved input | Before and after SHA-256 |
| --- | --- |
| Git-visible content/mode/deletion manifest | `3fa5b12a659f6b671aa543af89f5f46de61d7d2d3df48dd9a0c867bfcff37e56` |
| Git index bytes | `a966503715762ae180e3a8b1d9634fd1f9fd0e8a6f945d4bffc75aed062dc706` |
| Tracked working-tree binary diff | `8fc596fb692cd39f337e1ff7e91c25c260730be83f5c73db713b1dfa91d7424a` |
| Staged binary diff (empty) | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| Root `uv.lock` | `df840a80e08e062e5af3714c70053396c8628cc7fa62ae938d11bdf45939f4f8` |

Root `git diff --check` exited 0. Root status remains unchanged. `git check-ignore`
confirms the subject and all run directories are ignored; `git ls-files roadmap`
is empty. Authored ignored text has a whitespace/syntax/local-path gate; its exact
hashes and command outputs are saved by `artifact-gate-01.json`, with a complete
file/symlink inventory in `artifact-gate-01-files.json` (excluding those two
self-referential receipt files). Third-party vendor/cache text is not treated as
authored text; copied inputs have separate byte-integrity assertions.

**Deferred, not PASS:** cwd root
`UV_CACHE_DIR=/tmp/opencode/huron-effort-uv-cache make docs` and
`python roadmap/check_docs.py`. Starlight owns root `.venv`, shared cache and docs
build output; neither command was run by this worker. Independent maximum review
must follow this writer terminally and rerun with two new environment/run IDs.
No live Python/frontend/agent suite is applicable to ignored prototype-only edits.

No subprocess timeout occurred. Every spawned process group was checked after
exit; **no residual owned process groups** were observed in any run. No server or
browser was started. All artifacts, including the failed run, are retained under
this subject; cleanup remains with the parent/user, not automatic.

## Decision recommendation and remaining blockers

Recommend carrying the **native PEP 420 `huron` namespace** into the separately
approved Phase002 packaging cutover: neither distribution should own a root
`huron/__init__.py`; server and SDK must own disjoint descendant paths. Preserve
`from huron.client import Client` and `from huron.catalog import Dataset`, the
independent wheel and the direct `client.datasets` collaboration. Carry the
split-path/editable counterexample checks into production distribution gates.

This entails an explicit production decision to remove the live server
`src/huron/__init__.py` and qualify its packaging/import contracts and normal
server installation. **That deletion is not performed or authorized here.** Do
not introduce a second initializer, compatibility shim, or claim same-directory
coexistence alone solves the namespace problem. `huron-sdk` remains only an
experimental distribution name, not an approved registry name.

This experiment does **not** establish a working backend, server dependency
health, an authoritative wire contract, credential storage/issuance/refresh,
authorization, schema metadata behavior, tus, publication, retries, concurrency,
durability, production SDK API surface, performance, cross-platform packaging or
support across every Python >=3.12 minor. The synchronous seam is illustrative;
production sync/async choice and token-provider design remain blocked. The native
server result proves copied packaging mechanics, **not a migrated live server**.

Independent review findings/disposition: **not yet available**. This writer's
self-check is not independent review. Shared gates, parent reconciliation and
independent maximum qualification remain required before accepting this probe.
