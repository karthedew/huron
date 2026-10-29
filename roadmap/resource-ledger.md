# Canonical orchestration resources

This dictionary is maintained by the parent. Exact labels are cooperative claims,
not path-prefix matching or a filesystem sandbox. Code is globally exclusive.
Every subject review uses its writer's label; checks claim their output separately.
No child may broaden scope or mutate unclaimed shared services.

## Resources

| Label | Exact ownership boundary |
| --- | --- |
| `source:repo` | Existing live repository source, tests, docs, design, agent assets, root/CI/build configuration, locks; excludes ignored roadmap outputs and runtime/build artifacts. Read-only during concurrent preparation. |
| `plan:docs-design` | `roadmap/starlight-design.md`, `roadmap/execution-2026-10-05.md`, `roadmap/README.md`, `roadmap/check_docs.py`; subject of pending Starlight design/checker review. |
| `plan:raw-phases` | Existing `roadmap/plans/000-agent-tooling.md` and product plans 001–010, read-only until assigned synthesis. |
| `checks:roadmap` | Disposable lifecycle-check fixture files and scratch validation outputs under roadmap; no edits to real phase plans. For SDK review 1, also ordinary independent `roadmap/prototypes/sdk-isolation/runs/review-01-*` run artifacts and `review-01-artifacts*` receipts (or fresh uniquely named replacements if occupied); no authored SDK/probe edits. SDK subject remains read-claimed and no other SDK work may overlap this review. |
| `build:docs` | Existing strict docs build outputs (`site/` and docs-specific cache) and its uv invocation; no shared concurrent docs build. |
| `build:agent-tools` | `.agents/.test-build/` and all outputs of agent-tools npm checks/tests, including each invocation's unique `/tmp/opencode/dispatch-test-*`, `journal-test-*`, `symlink-test-*`, `symlink-target-*`, `launcher-test-*` fixtures; never delete another invocation's data. |
| `runtime:inventory` | Read-only host service/port/mount and Docker ownership observations; no startup, shutdown, migration, secret values or data mutations. |
| `plan:mvp-readiness` | Future ignored readiness/inventory synthesis assigned by parent; no product or service changes. |
| `prototype:starlight` | Future isolated `roadmap/prototypes/starlight/` package, corpus, output and evidence; live docs untouched. |
| `service:docs-prototype` | Owned throwaway static docs preview on `127.0.0.1:4327`, only after proving the port free; record PID and stop only the owned process. No live application service changes. |
| `browser:docs-prototype` | Named Playwright CLI session `huron-docs-prototype`, its in-memory profile and ignored artifacts under `web/.playwright-cli/` and the Starlight prototype folder; no shared/default sessions or unrelated browser operations. |
| `prototype:schema` | Isolated `roadmap/prototypes/schema/` validator/corpus/caller-seam experiment and evidence; live domain code/locks untouched. |
| `prototype:sdk` | `roadmap/prototypes/sdk-isolation/` including copied server build inputs, candidate SDK sources, unique run directories, wheels, private venvs/cache/TMPDIR and evidence; live package/lock/root environment untouched. |
| `plan:effort-profile` | `roadmap/plans/astra-effort-profiles.md` and `roadmap/effort-profile-design.md`; maximum-effort bootstrap plan/design subject. |
| `prototype:effort-profile` | `roadmap/prototypes/effort-profile/` isolated API probe and all its outputs/cache; no live model/server calls. |
| `source:effort-profile` | Exact live bootstrap allowlist in `roadmap/plans/astra-effort-profiles.md`; globally exclusive during parent code edits; read-only for review. |
| `cache:uv` | For effort-profile gates, explicit `UV_CACHE_DIR=/tmp/opencode/huron-effort-uv-cache`; no other worker may mutate it concurrently. |
| `env:python` | Root `.venv/` synchronization by the existing uv docs-build invocation; no concurrent Python environment mutation. |
| `git:checkpoint` | Read-only checkpoint audit of Git status/diffs/history/index; staging and local commits belong only to parent after active subject review finishes. Never push or rewrite history. |
| `build:checkpoint` | One fresh, invocation-owned export of the staged checkpoint under `/tmp/opencode/huron-checkpoint-*`, including its own dependencies/builds/cache; no writes to live source/index or unrelated temp data. |
| `plan:skill-launch` | `roadmap/canonical-skill-launch-fix.md` correction and parent reconciliation receipt; read-only for checkpoint review. |
| `plan:checker-inputs` | `roadmap/checker-input-boundary-plan.md`: proposed ignored-checker discovery correction contract and review receipts only; no edits to checker, tests, dependency artifacts or other plans during synthesis. |

Checkpoint reconciliation: exact export may contain the unchanged tracked `dev.env`
blob already in HEAD/index; no untracked/local environment files are copied. Review
only private classifications, never credential values. Current owned export is
`/tmp/opencode/huron-checkpoint-Uhqf4Vzn`; it was verified identical to tree
`a1a4afc4bf332649146b726fc59fa0e560fbb591` and its first worker is terminal.
Subsequent export tests additionally claim `build:agent-tools` for fixed temporary
fixture locations. No test scope/assertion or selected-tree change is authorized.

## Resume checkpoint

The loaded tool schema now includes activity/claims and status returns ownership
summaries. Historical children have unknown legacy classifications, with terminal
receipts in the prior transcript; admission must reconcile them, not delete history.
Initial dirty-tree ownership was refreshed with full git status. All existing work
remains preserved. No journal/lock maintenance is authorized or attempted.

Initial concurrent preparation: Starlight design review reads `source:repo`,
`plan:docs-design`, `plan:raw-phases`, writes only `checks:roadmap` and `build:docs`;
Raw readiness discovery reads `source:repo`, `plan:raw-phases`, `runtime:inventory`.
No shared writes or subject-writer overlap. Evidence stays in child final responses
until the parent records outcomes after their subject claims are released.

## Claude Code session dictionary (2026-10-07)

Host Claude Code (session d88e4122); workers are Claude Code workflow subagents,
configured `claude-opus-5-5` effort max, provider acceptance not proven. The user
accepted the progress-delivery limitation on 2026-10-06. Exact labels remain
cooperative claims; code is admitted exclusively by running no other workflow.

| Label | Exact ownership boundary |
| --- | --- |
| `tool:roadmap-checker` | `roadmap/check_docs.py`, `roadmap/checks/test_check_docs.py`, `roadmap/checks/test_check_docs_discovery.py`, `roadmap/checks/starlight-markdown-inputs.v1.json`, `roadmap/checks/checker-input-boundary-receipt.md`, `roadmap/checks/recovery/`. Supersedes the `roadmap/check_docs.py` entry under `plan:docs-design`. |
| `checks:roadmap` | Checker/harness outputs, invocation directories `roadmap/checks/chk-*`, fixtures under `${TMPDIR:-/tmp}/huron-checker-discovery-*`. Reads ALL roadmap Markdown: no concurrent roadmap Markdown writer. |
| `plan:checker-inputs` | `roadmap/checker-input-boundary-plan.md` (reviewed contract, byte-identical `d2f71de5…`) and `roadmap/plans/checker-input-boundary.md`. |
| `prototype:sdk-isolation` | Same boundary as the OpenCode-era alias `prototype:sdk` above (`roadmap/prototypes/sdk-isolation/`). The two spellings name one resource. |
| `prototype:starlight` | `roadmap/prototypes/starlight/` as defined above. |
| `build:docs` | `site/` and the docs uv cache `UV_CACHE_DIR=/tmp/opencode/huron-effort-uv-cache` (the OpenCode-era `cache:uv` is inside this label). |
| `env:python` | Root `.venv/`. |
| `build:python-checks` | `.ruff_cache`, `.mypy_cache`, `.pytest_cache`, `.coverage*`, `htmlcov`. |
| `docs:durable` | `design/raw-first.md`, `CONTEXT.md`, `design/auth.html`, `design/rbac*.html`, `design/rbac*.md`. |
| `plan:identity` | `roadmap/plans/003-identity-directory-access.md` and identity receipts under `roadmap/`. |
| `prototype:runner` | `/var/tmp/huron-runner/**`, host port `127.0.0.1:24022`, one QEMU process; promoted evidence `roadmap/prototypes/runner/`. |
| `prototype:numeric` | Session scratch `prototypes/numeric/` (promoted to `roadmap/prototypes/numeric/`) and its owned `huron-numeric-probe-*` PostgreSQL container and port. |
| `scratch:<name>` | Session scratch directory `<name>/`, outside the repository. |

Session decisions and run identifiers are recorded in the session receipts promoted
under `roadmap/` after the checker correction qualifies.
