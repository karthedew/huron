# M11 architecture review evidence and prototype assignment

Status as of 2026-11-09: **reconciled planning contract independently accepted through prerequisite gates**.
Original maximum complete reviews remain **FAIL/FAIL/FAIL**. Review3 found token-format cutover
ownership missing for `scripts/dev-login.sh` and its e2e/demo callers. Section 13 records the
substantive reconciliation writer proposal. The later independent maximum review returned PASS;
[plan §14](../IMPLEMENTATION_PLAN_LATEST.md#14-parent-acceptance-receipt-after-authorized-independent-review-2026-11-09)
records the parent-observed terminal verdict and resolution of R3-1.
The [final review and escalation receipt](../IMPLEMENTATION_PLAN_LATEST.md#12-final-independent-review-and-escalation-receipt)
records reviewer `ses_e412ba125ffeV3Y9o1hLnuYhTi`, checks, classification, owner and next action.
The later explicit user authorization allows ONE additional independent maximum review after this
writer is terminal, as a one-time exception with no automatic retry. It authorizes no implementation
and does not rewrite the original exhausted cycle or its historical receipt.
The original status was “planning evidence, awaiting independent architecture/prototype review”.
Sections 1–9 preserve that writer/fix history; section 10 records subsequent outcomes.
This is a planning PASS through explicit prerequisite gates, not product or complete-design validation.
Companion proposal: [M11 production architecture](m11-production-architecture.md).
Current draft: [replacement M11 phase plan](../IMPLEMENTATION_PLAN_LATEST.md).
Durable results: [bounded prototype evidence](m11-prototype-evidence.md).

## 1. Provenance, authority, and scope

This record synthesizes the terminal independent discovery from
`ses_e41c0ac7fffenvXnJq83K0pRBh`, architectural discovery attempt 1. Its full 804-line report was
read, including the continuation after the tool's first 782 lines:

```text
/home/karl/.local/share/opencode/tool-output/tool_1be587846001yUyBMZW7YtpcN1
```

That report's disposition was BLOCKED for implementation-plan readiness and production
qualification. Discovery made no edits and executed no product tests. Its collection-only pytest
commands are not test execution evidence. Its configured profile was maximum Astra;
`providerAcceptance: not-proven` is not a measurement of provider reasoning effort.

This writer's dispatch is `700931fb-c779-45b2-9d46-786c3089ece2`, child
`ses_e41a6e784ffeeewx93Xn6wbl72`, parent `ses_e41c1bd18ffer6qYUucJS8u5Gw`.
Role `implementation`, activity `planning`, attempt 1, profile `maximum`, claim `*:write`.
The environment identifies `openai/gpt-6-astra`; provider effort acceptance was not measured.
The claim conservatively reserves repository/resources for serial coordination, not edit permission.

Only these two new files are owned:

- `design/m11-production-architecture.md`
- `design/m11-review-evidence.md`

Both files, and their parent `design/` directory, were absent before editing. No source, test,
configuration, service, dependency, dispatch-state, branch, or old-plan change is authorized.
No probe code is written by this planning assignment. No delegation, commit, push, branch change,
reset, stash, or automatic revert is part of this work.

### Required reading completed

- [AGENTS.md](../AGENTS.md), [domain guidance](../docs/agents/domain.md), and
  [CONTEXT.md](../CONTEXT.md).
- [Orchestration](../.agents/workflows/orchestration.md) and
  [verification](../.agents/workflows/verification.md).
- Local skills and templates: [design-plan](../.agents/skills/huron-design-plan/SKILL.md),
  [prototype](../.agents/skills/huron-prototype/SKILL.md),
  [implementation-plan](../.agents/skills/huron-implementation-plan/SKILL.md),
  [design template](../.agents/templates/design-plan.md),
  [prototype template](../.agents/templates/prototype.md), and
  [phase template](../.agents/templates/phase-plan.md).
- [Old plan](../IMPLEMENTATION_PLAN.md) sections 3–9, plan-wide rules, every M11 task,
  risk register, and every M11 escalation/resolution through line 5799.
- [Architectural synthesis](../architectural_review.md), section S, and
  [ADR 0008](../docs/adr/0008-uploads-through-tusd.md).
- Area skills loaded: [oop-design](../.agents/skills/oop-design/SKILL.md),
  [postgresql-table-design](../.agents/skills/postgresql-table-design/SKILL.md), and
  [fastapi](../.agents/skills/fastapi/SKILL.md). This proposal uses direct collaborators and
  immutable values, not a new pattern framework.

`asd-ste100` and `writing-for-agents` are named by AGENTS.md but absent from the retained local
skill inventory. No external copy was fetched. Clear technical prose and instruction-scope checks
still apply; formal qualification with those unavailable skills cannot be claimed. The asset
owner, not this writer, reconciles that policy mismatch. No Svelte source or visible UI is changed.

## 2. Exact initial ownership inventory

Recaptured from `/home/karl/repo/huron-tusd` before writing. This matches discovery's ownership
description and supplied HEAD. **Every entry below is pre-existing and user-owned**, including
the staged agent-state removals, agent-tool corrections, old plan, and untracked repair work.

```text
$ git rev-parse HEAD
0dcdf1ff6a8689f704a73a0758a886c18b5d3584
$ git symbolic-ref --short HEAD
tusd-integration
$ git status --short --untracked-files=all
D  .agents/.dispatch-state/ledger.json
 M .agents/.gitignore
D  .agents/.test-build/dispatch-state.js
D  .agents/.test-build/implementation.js
 M .agents/README.md
 M .agents/scripts/check-assets.mjs
 M .agents/scripts/check-resolved.mjs
 M .agents/tests/assets.test.js
 M .agents/tests/implementation.test.js
 M .agents/tests/launcher.test.js
 M .opencode/README.md
 D .opencode/commands/implement-markdown.md
 D .opencode/plugins/implementation.ts
 D .opencode/tests/implementation.test.js
 M IMPLEMENTATION_PLAN.md
 M docs/api-errors.md
 M docs/concepts/raw-ingest.md
 M docs/openapi.json
 M pyproject.toml
 M src/huron/applications/api/disk/__init__.py
 M src/huron/applications/api/disk/placements.py
 M src/huron/applications/api/routes/v1/router.py
 M src/huron/applications/api/runtime.py
 M src/huron/core/lake/bootstrap.py
 M src/huron/core/lake/collections/lifecycle.py
 M src/huron/core/lake/lookups.py
 M src/huron/core/storage/__init__.py
 M src/huron/core/storage/errors.py
 M src/huron/core/storage/memory.py
 M src/huron/core/storage/placement.py
 M src/huron/core/storage/ports.py
 M src/huron/core/storage/posix.py
 M src/huron/pkg/fs/posix.py
 M src/huron/schema/naming.py
 M tests/conftest.py
 M tests/unit/api/test_lake_disk.py
 M tests/unit/api/test_lifespan.py
 M tests/unit/api/test_upload_hooks.py
 M tests/unit/lake/test_uploads.py
 M tests/unit/pkg/test_posix.py
 M tests/unit/schema/test_naming.py
 M tests/unit/storage/test_containment.py
 M tests/unit/storage/test_placement.py
 M tests/unit/storage/test_races.py
 M tests/unit/storage/test_storage.py
 M web/src/lib/api/openapi.ts
?? docs/agents/domain.md
?? src/huron/applications/api/disk/repair.py
?? src/huron/applications/api/routes/v1/endpoints/repairs.py
?? src/huron/applications/api/routes/v1/schema/repairs.py
?? src/huron/core/lake/repairs/__init__.py
?? src/huron/core/lake/repairs/models.py
?? src/huron/core/lake/repairs/operations.py
?? src/huron/core/storage/repair.py
?? tests/unit/api/test_repair.py
?? tests/unit/lake/test_repairs.py
?? tests/unit/storage/test_repair.py
```

`git branch --list m11.5-escalated` exited 0 and printed that branch. It remains reference material,
not something this worker may delete. The old synthesis's branch-deletion advice is overridden
by the plan's resolution at lines 5648–5656. That resolution also preserves the CLI source-folder
`os.walk` and names the event `disk.link_found`, not `disk.symlink_found`.

Initial working-file Git blob hashes, captured without writing objects:

| File | `git hash-object` result |
| --- | --- |
| `IMPLEMENTATION_PLAN.md` | `862e1bafc54c5ca88b0351ff7ee723662a1ac7f8` |
| `migrations/versions/0003_uploads.py` | `83757f7e73640356639ae07c45d7885660b9a6e3` |

Both staged and unstaged diffs for 0003 were empty. Regardless of that clean-file observation,
the proposed additive migration preserves it; no conclusion about an existing database's applied
schema or permission to rewrite data follows from Git status.

The initial root whitespace check exited 2:

```text
web/src/lib/api/openapi.ts:170: trailing whitespace.
```

The offending added line is an OpenAPI comment line with a trailing space. It is pre-existing
generated user-owned text, not fixed here. `git diff --cached --check` exited 0.

## 3. Current behavior and discovery findings

Line citations refer to the captured dirty working tree, not a clean HEAD reconstruction.
`D:` below cites line ranges in the full discovery report named in section 1. These are inspected
counterexamples, not newly executed reproductions. This writer reread the principal implementation
paths; associated test-coverage observations below retain their discovery provenance.

### Seven supplied claims

| ID | Finding and concrete sequence | Writer/consumer and coverage evidence | Design response |
| --- | --- | --- | --- |
| F1 | A replaced committed file loses its previous bytes before collection acceptance. Upload B replaces A, its receipt drops A's backup, a metadata write advances the base, then B's commit fails while public bytes remain B. | [Placer](../src/huron/core/storage/placement.py):92–141; [Placements](../src/huron/applications/api/disk/placements.py):63–80; [CLI push](../src/huron/applications/cli/sync.py):153–158; [Commits](../src/huron/core/lake/files/commits.py):134–140. Hook tests cover receipt refusal, not this later commit refusal. `test_push_tusd.py:428–440` checks conflict/stage only. D:51–79. | Private seal only; acceptance before public effects. |
| F2 | Row receipt order can disagree with filesystem order. A links A, B links B, B records, then A records; latest timestamp selects A while B is public. Clock skew/ties worsen it. | [PathLocks](../src/huron/core/storage/locks.py):18–43; [LakeDisk](../src/huron/applications/api/disk/lake.py):107–109; [upload receipt](../src/huron/core/lake/uploads/operations.py):124–141; [PostgreSQL upload adapter](../src/huron/core/metastore/uploads/postgres.py):87–99; commits:250–277. `test_commits.py:234–265` tests row ordering only; hook duplicates share one runtime. D:81–106. | Explicit objects and one fenced publication owner; times are diagnostic. |
| F3 | Missing-source replay can adopt unrelated same-size public content. Replay can record before its first marker-checked action, lacks fresh-branch compensation, and duplicate replacement can overwrite the useful backup. | Placer:84–90; Placements:82–96; LakeDisk:165–168,193–201; [POSIX primitives](../src/huron/pkg/fs/posix.py):285–299,385–404. `test_upload_hooks.py:161–183` lacks arbitrary same-size foreign content. D:108–155. | DB/object/seal identity, retained objects, exclusive temp names; no destination-based receipt reconstruction. |
| F4 | An old timed-out upload can finish after a newer success and overwrite it, even in one API process. | [CLI uploader](../src/huron/applications/cli/uploads.py):210–222 forgets attempt IDs; upload operations:82–114 have no supersession/reservation. `test_push_tusd.py:182–198` never releases an old delayed operation after newer success. D:157–172. | Timeout preserves IDs; late seal stays private; explicit durable supersession. |
| F5 | Removal-only lost-response recovery can falsely succeed after an unrelated version bump because the add loop is empty. Stage is then cleared. | CLI sync:295–304 and 157. `test_collections.py:198–204` covers a lost answer with an add; `test_edges.py:122–134` covers an absent add, not remove-only. D:174–202. | Required durable request UUID and exact outcome for every payload, including empty/removal-only commits. |
| F6 | CLI reuses `placed` and `committed`, while server requires fresh, unconsumed, owned latest receipt with exact spelling/hash/size. Response omits eligibility and expiry. | CLI uploads:40,112–128; [upload values](../src/huron/core/lake/uploads/models.py):89–106,122–132; commits:250–277. Server expiration/consumption tests exist; CLI reuse tests cover a valid unconsumed receipt only. D:204–230. | Expose eligibility/reason/expiry and consuming operation; committed objects recover through that outcome. |
| F7 | Only push locks state; add/rm/pull/checkout race it. Fixed `.tmp` uses truncation. Stage clear and base update are separate and unsynced. Source checks size, not a staged snapshot. | CLI sync:50–60,83–124,134,157–158,213–220; [state](../src/huron/applications/cli/state.py):160–189; uploads:158–184,335–342; [stage command](../src/huron/applications/cli/commands/stage.py):104–109. Same-size edits intentionally upload in `test_push_tusd.py:284–295`; shrinking is tested at 415–425. D:232–274. | One local mutation lock, atomic intent generation, private copy-on-add spool, documented source-read consistency limit. |

These are design defects as well as implementation gaps: D-8 and the old upload flow explicitly
prescribe several unsafe behaviors. Merely adding exception handlers would preserve the cause.

### Operational and adjacent-mutation findings

| ID | Finding | Evidence and disposition |
| --- | --- | --- |
| O1 | Worker counts do not bound executor queues or waiting requests. | LakeDisk:108–109,186–191. Preserve separate pools; add admission before submit. D:280–282. |
| O2 | No aggregate admission or physical-byte accounting. | Uploads.begin:86–103 checks only file size; [settings](../src/huron/applications/api/settings.py):165–173 has no aggregate budgets. Select finite global/catalog/principal reservations and cleanup-based release. D:283. |
| O3 | Two-second lake wait is not a total readiness bound. | [Runtime](../src/huron/applications/api/runtime.py):124–135 waits on DB/key reads first; [PostgresStore](../src/huron/core/metastore/postgres.py):95–111 lacks total acquisition/query timeout. D:284. |
| O4 | Probe timeout is not aligned with endpoint budget. | [Deployment](../deploy/openshift/deployment.yaml):26–31 omits `timeoutSeconds`. Select total deadline/probe budgets explicitly. D:285. |
| O5 | Hard-NFS work survives cancellation; pool shutdown does not prove old writer death. | LakeDisk:120–123,154–180,226–230. Require operational quiescence/fencing before replacement. D:286. |
| O6 | Runtime can close DB while outstanding physical work still needs settlement. | Runtime:137–143; `test_lake_disk.py:829–866` expects errors after pool shutdown. Add tracked drain and durable recovery. D:287. |
| O7 | Failed startup can leak an internally opened store. | Runtime:164–188,229–241; [app lifespan](../src/huron/applications/api/app.py):37–42. Explicit resource acquisition ownership/cleanup is required. D:288. |
| O8 | Initial provisioning depends on a running API that itself needs a writable prepared root. | LakeDisk:203–211; [adm CLI](../src/huron/applications/cli/commands/adm.py):225–228,452–454; plan:1455–1486. Select offline input-driven provisioning before writer start. D:289. |
| O9 | Recreate/one desired tusd replica does not fence an evicted old PATCH; lock deletion can overlap it. | Plan:437–450,1776–1782,5380. Reject the old accepted overlap residual. D:290. |
| O10 | Removal execution is still absent. | [removal rules](../src/huron/core/storage/removal.py) contain only `prune`; [commit route](../src/huron/applications/api/routes/v1/endpoints/files.py):54–58 and [collection delete](../src/huron/applications/api/routes/v1/endpoints/collections.py):188–192 drop removal work. Pending M11.6, not delivered behavior. D:291. |
| O11 | Filtering a recursive walk does not make a shallow sweep; mtime can target active tusd files. | Plan:4955–4957; POSIX primitives:411–427. Add a shallow port operation and identity/quiescence-based GC. D:292. |
| O12 | Publication durability ordering is incomplete. | POSIX primitives:235–259 sync a temporary file, not the parent after rename; rename/removal have no complete protocol. Add explicit sync/ack ordering; local tests cannot prove NFS persistence. D:293. |
| O13 | Metadata can publish older bytes last across replicas and uses a shared part name. | [disk directories](../src/huron/applications/api/disk/directories.py):85–97 and storage `write_bytes`. Same writer/guard discipline and unique temps required. D:295–303. |
| O14 | Repair rereads rows but can apply its plan's stale share group after a concurrent change. | [repair domain](../src/huron/core/lake/repairs/operations.py):58,68–78; [repair orchestration](../src/huron/applications/api/disk/repair.py):33–54. Bind each step to current resource ID/version/schema/group. D:305–310. |
| O15 | Workload/observability qualification is missing. | D:312–322 lists empty files, chunk boundaries, 10,000 entries, large totals, queue pressure, ENOSPC/EDQUOT/inodes, restart, late hooks, and cleanup backlog. `StalledStorage` proves scheduling only. |
| O16 | Production docs retain obsolete CLI-write/ACL claims. | `docs/architecture.md:199`, `docs/operator.md:14,149,376`, `docs/concepts/raw-ingest.md:25,85,274–278,336`, `docs/concepts/access-and-roles.md:191`, `docs/concepts/metadata-and-schemas.md:351–352`. Carry into pending M11.12, not this edit. D:518–539. |

Containment is not newly disproven. Discovery specifically preserves
[LakePath](../src/huron/core/storage/lakepath.py):12–59,
[PosixStorage](../src/huron/core/storage/posix.py):267–287, and the descriptor primitives:104–139.
The M11.5e escalation says **no containment hole was found** (plan:5689). Its failures concern
adapter fidelity and exact failure text/path, not permission to redesign containment.

## 4. Every M11 task reconciled

Recorded status is history, not a fresh qualification. “Present” means discovery inspected the
implementation/test structure. Task references below are line ranges in the unchanged
[old plan](../IMPLEMENTATION_PLAN.md). D:474–539 gives the independent reconciliation.

| Task | Recorded status | Current evidence and forward disposition |
| --- | --- | --- |
| M11.1 | Complete | Plan:3931–4034. Upload aggregate, receipts, stores, collection locking, and removal outbox present; PostgreSQL races at `tests/contract/test_postgres_races.py:199–260`. Retain accounting/locks; replace public-placement receipt semantics and outcome inference. |
| M11.2 | Complete | Plan:4036–4100. Inode conversion/share groups/constraints and migration tests present; `0003_uploads.py:20–116`, `tests/contract/test_migration.py:44–61`. Extend additively for objects/operations/reservations. |
| M11.3 | Complete | Plan:4102–4196. Runtime/settings/readiness/share-group API/pools present. Admission, total deadline, failure cleanup, and topology need correction. |
| M11.4 | Complete | Plan:4198–4287. Hook/auth/read routes and `Placements` present; endpoint `uploads.py:148–158` reaches the writer. Actual nginx/tusd integration absent. Replace pre-finish public effects. |
| M11.5a | Complete | Plan:4289–4353. Hash pool, overwrite backup, and reference branch present. Keep pools/branch; replace inadequate backup lifetime and duplicate handling with retained objects. |
| M11.7 | Complete | Plan:4355–4409. CLI tus path present and share-copy path removed. Fix timeout/eligibility/outcome/state defects. Its integration skip remains and must be replaced by real coverage. |
| M11.8a | Complete | Plan:4411–4466. Directory/metadata CLI verbs call API; `tests/unit/cli/test_directories.py:24–29` supplies read-only storage. Preserve no CLI lake writes. |
| M11.9a | Complete | Plan:4468–4558. ACL paths removed, read-only typing/import rules present. Pending prose removal belongs to M11.12; do not restore old ACL code. |
| M11.5b | Complete | Plan:4560–4603. `Destination(directory, rel_path)`, removal return shapes, configured-root validation present. Retain domain-path versus physical-path distinction. |
| M11.5c | Complete | Plan:4605–4745. `LakePath`, no-follow traversal, reduced port, containment/race coverage present. Preserve boundary; no newly demonstrated escape. |
| M11.5d | Complete | Plan:4747–4835. Directory verbs and sidecars wired. Extend ownership/order/durability; removal draining was never completed here. |
| M11.5e | In progress | Plan:4837–4944,5775–5799. Dirty repair code and tests present but not accepted. The 253-row matrix and exact code/path/message assertions at `test_containment.py:605–640` are preserved. Complete the user-approved resolution and a new independent cycle; also prevent stale group/metadata actions. |
| M11.6 | Pending | Plan:4946–5000. Only `prune` exists. No delivered Unlinker/Sweeper/removal orchestration/runner/election. Replan public removes and GC against object/operation identity, not inode/lease safety claims. |
| M11.8 | Pending | Plan:5002–5028. API repair is dirty; CLI repair/share-group options and full hints remain future work. `adm.py` has no repair command. Preserve read-only CLI behavior. |
| M11.9 | Pending | Plan:5030–5088. Mode/owner/group/unreadable findings and full provisioning absent. `storage/check.py:194–214` reports `.huron-part` but not finished `.huron-prev` handling. Carry check/provision obligations into bounded slices; add offline first install. |
| M11.10 | Pending | Plan:5090–5156. Real tusd/nginx tests, stack files/targets absent; CLI end-to-end still skipped. Missing offline images block real handoff qualification. |
| M11.11 | Pending | Plan:5158–5245. Existing OpenShift deployment has two API replicas and no lake mount (`deployment.yaml:6,40–51`). Upload resources/local overlay absent. Replan for single writable process and fenced replacement; shared cluster is not incidental test infrastructure. |
| M11.12 | Pending | Plan:5247–5310. Documentation task, **not** performance/acceptance implementation. All operator/user/design reconciliation obligations below remain. |
| M11.13 | Pending | Plan:5312–5355. Helm uploads/production values absent. Actual ONTAP setgid/security-style evidence gates production; Helm executable/fallback image absent in discovery. |

### M11.5e resolution retained exactly in intent

1. Keep full `MemoryStorage`; the shared per-case contract suite specifies behavior, with POSIX
   as reference unless a defect is explicitly fixed and recorded.
2. Metadata/part-file failures put that actual file in `path`, matching `detail`.
3. [RepairFailureOut](../src/huron/applications/api/routes/v1/schema/repairs.py):27–60 is the one
   authoritative failure-contract text; OpenAPI and web types are generated from it.
4. Run a new independent verification cycle after the owned fix. Historical green counts do not
   qualify the current dirty repair implementation or this proposal.

### M11.12 obligations that must not disappear

Carry forward export rules, fixed UID/GID/SCC/range selection, API/upload mounts and ownership,
safe tusd lock handling, share groups, provisioning, containment and failure recovery, every drift
finding, cleanup, AUTH_SYS limitations, hard-NFS readiness/drain/fencing, and the setgid measurement
procedure. Document actual local-cluster commands and limitations after their delivery.
Keep “Helm: not yet delivered” until M11.13 is actually qualified. Update push/resume/error/repair
and share-group guidance, architecture/concepts/web-design/README, obsolete ACL/CLI-write text,
and broken `apply-acl` anchors. Distinguish server `lake_path` from client `mount_prefix`.
The new accepted/pending visibility and exact-outcome semantics add to, not replace, that scope.

## 5. Infrastructure evidence and limits

The following is **discovery's observed inventory**, D:623–657, not a new service probe by this
writer. A future experiment must recapture it before allocating resources.

| Capability | Discovery observation |
| --- | --- |
| Python toolchain | uv 0.12.19; project Python 3.12.4; FastAPI 0.162.0; Pydantic 2.14.1; asyncpg 0.32.0; HTTPX 0.28.1; SQLAlchemy 2.1.6; Alembic 1.20.1; pytest 9.2.0; pytest-asyncio 1.4.1; testcontainers 4.15.0. |
| Quality tools | Ruff 0.17.3; mypy 2.4.1; ty 0.0.94; import-linter 2.15; radon 6.0.1; complexipy 8.3.0. |
| Node/web | Node 26.10.0; npm 11.19.1; Playwright 1.62.1 and cached Chromium. No browser launched. |
| Containers | Docker client/server 27.2.1; cached `postgres:16`, image prefix `88a36c64c100`. Existing `ocp-test-control-plane` left untouched. |
| Missing assets | `tusd`, `nginx`, `helm` not on PATH; targeted tusd/nginx-unprivileged/Helm image inspections exited 1. Do not download them. |
| PostgreSQL endpoint | `HURON_TEST_DATABASE_URL` unset; `pg_isready -h 127.0.0.1 -p 5432 -t 2` exited 2. psql 18.6 is only a client; server binaries not found. Use a private cached container. |
| Deployment tools | kubectl 1.37.1 with kustomize 5.8.1. Tool availability is not authority to mutate the existing cluster. |
| Filesystems | Repository ext4, about 500 GiB available; `/tmp/opencode` tmpfs, about 59 GiB; ample inodes; no NFS mount listed. Neither filesystem proves ONTAP behavior. |

No real tusd handoff, actual NFS/hard-mount outage, ONTAP setgid/security style, or production
fencing/durability evidence is available. Fake tus and `StalledStorage` cannot substitute.

### Ignored prototype location resolved without an ignore edit

Discovery correctly found bare `roadmap/prototypes/discovery-probe` **not ignored**. This writer
checked concrete children of the proposed alternate location:

```text
$ git check-ignore -v roadmap/prototypes/m11-production/__pycache__/probe.py roadmap/prototypes/m11-production/__pycache__/results.json roadmap/prototypes/m11-production/__pycache__/lake/object
.gitignore:2:__pycache__/  roadmap/prototypes/m11-production/__pycache__/probe.py
.gitignore:2:__pycache__/  roadmap/prototypes/m11-production/__pycache__/results.json
.gitignore:2:__pycache__/  roadmap/prototypes/m11-production/__pycache__/lake/object
exit 0
```

`git ls-files roadmap` exited 0 with no output. Thus an owned throwaway experiment can live entirely
under `roadmap/prototypes/m11-production/__pycache__/`, without modifying `.gitignore` or tooling.
The directory name is an isolation convention here, not production Python cache code. The next
worker must recheck concrete per-run children and absence before writing. No artifacts go into
the unignored parent. If the rule stops covering them, stop and report the blocker.

## 6. Bounded runnable prototype specification

### Assignment envelope and non-production boundary

Next work is `implementation` / `prototype`, followed terminally by `verification` / `review`.
Use maximum profile for the requested independent architecture/evidence qualification. A future
preparatory prototype is allowed only if the parent explicitly records that profile; wording does
not upgrade provider effort. Never delegate from the worker or resume it without reconciliation.

Prefer conservative `*:write` serial ownership for each probe slice. The parent must map the
claim to these exact allowed outputs/resources, not treat it as general edit permission:

- Owned code, manifests, logs, state, and lake directories only under the ignored prototype root.
- Read-only imports of the captured source/tests and the two design records.
- One uniquely named Docker network/container/volume for the probe; never `make up`, `make app`,
  existing containers, shared database URLs, or the existing cluster.
- Ephemeral loopback PostgreSQL port; only owned subprocesses and local test clients.
- Any Python bytecode/temp/cache output redirected below the ignored root, or disabled.

The worker creates a small `probe.py` runner and candidate adapter/state-model modules there.
They are throwaway, visibly labeled non-production, and must never patch/import-replace live source
files or edit tests/migrations/configuration. Current counterexamples call actual public operations.
The candidate uses its own PostgreSQL schema and real filesystem adapter in this owned directory.
It may implement missing primitives there; that is evidence about the candidate, not delivered code.

Run one slice per dispatch: publication counterexamples/model, CLI state, then runtime/admission.
Do not grow the first experiment into a production implementation. Each slice has a 15-minute
runner deadline, 5-second deterministic barrier waits, and a 60-second individual case bound unless
the command explicitly selects a larger transfer. Limit generated data to 2 GiB and require 8 GiB
free space plus adequate inodes before allocation. Large-scale acceptance later requires at least
the workflow's 25 GiB free-disk prerequisite and a separate resource claim; this is not that gate.

Copy this progress contract into each actual probe/review dispatch:

Every implementation, fix, and verification subagent must send a brief progress update at least every 15 minutes of elapsed time while its assignment remains active, including during validation. Send blockers, repeated failures, and suspected hangs immediately rather than waiting for the next interval. These are progress messages, not final implementation reports or verification verdicts. Keep each update to 2-4 short lines containing the phase/task, agent role and attempt number, elapsed time, concrete progress since the previous update, current operation or command, and the next step or blocker. If nothing has advanced, say so and identify the last observed activity; do not substitute 'still working' for evidence. Parent polls asynchronously at least once per minute.

### Private PostgreSQL setup, to be run by the prototype owner only

All commands below run from `/home/karl/repo/huron-tusd`. They were **not run by this writer**.
First inspect parent directories, ignored children, and the exact resource names. A successful
inspection of an existing resource is a collision: stop, never attach/delete it or assume ownership.
Use another explicitly recorded run suffix for subsequent attempts.

```sh
git check-ignore -v roadmap/prototypes/m11-production/__pycache__/probe.py roadmap/prototypes/m11-production/__pycache__/runs/a1/results.json
docker image inspect postgres:16 --format '{{.Id}}'
docker container inspect huron-m11-production-a1
docker network inspect huron-m11-production-a1-net
docker volume inspect huron-m11-production-a1-pg
```

Image inspection must succeed without a pull; each named resource inspection must show absence
before creation. After that check, create only these isolated resources:

```sh
docker network create --internal --label huron.probe=m11-production-a1 huron-m11-production-a1-net
docker volume create --label huron.probe=m11-production-a1 huron-m11-production-a1-pg
docker run --detach --pull=never --name huron-m11-production-a1 --label huron.probe=m11-production-a1 --network huron-m11-production-a1-net --publish 127.0.0.1::5432 --env POSTGRES_HOST_AUTH_METHOD=trust --mount type=volume,src=huron-m11-production-a1-pg,dst=/var/lib/postgresql/data postgres:16 -c fsync=on -c synchronous_commit=on -c full_page_writes=on
docker port huron-m11-production-a1 5432/tcp
docker exec huron-m11-production-a1 pg_isready -U postgres -d postgres -t 2
```

Trust authentication is for this disposable database only: isolated internal network, loopback
publication, no real data or credentials. Never apply it to a shared server. Poll readiness with
a 30-second total deadline. Record image ID, container ID, labels, port, and PostgreSQL version.
The runner receives `--postgres-container huron-m11-production-a1`, verifies that exact ownership
manifest/label/port, derives the URL itself, and rejects an inherited `HURON_TEST_DATABASE_URL`.
Do not print credentials in progress/log titles. No image build, package install, or download.

### Required runner CLI and reproduction commands

These commands become runnable **after the assigned prototype worker writes the specified runner**.
They are an artifact contract, not claims that `probe.py` exists today. `--help` must document the
four suites, resource checks, exit statuses, time/space bounds, and preservation on failure.

```sh
PYTHONDONTWRITEBYTECODE=1 uv run --offline --no-sync python roadmap/prototypes/m11-production/__pycache__/probe.py --suite publication-current --postgres-container huron-m11-production-a1 --run-id current-a1 --deadline-seconds 900
PYTHONDONTWRITEBYTECODE=1 uv run --offline --no-sync python roadmap/prototypes/m11-production/__pycache__/probe.py --suite publication-candidate --postgres-container huron-m11-production-a1 --run-id candidate-a1 --deadline-seconds 900
PYTHONDONTWRITEBYTECODE=1 uv run --offline --no-sync python roadmap/prototypes/m11-production/__pycache__/probe.py --suite cli --postgres-container huron-m11-production-a1 --run-id cli-a1 --deadline-seconds 900
PYTHONDONTWRITEBYTECODE=1 uv run --offline --no-sync python roadmap/prototypes/m11-production/__pycache__/probe.py --suite runtime --postgres-container huron-m11-production-a1 --run-id runtime-a1 --deadline-seconds 900
```

Each invocation requires an absent run directory, writes `runs/<run-id>/manifest.json`,
`events.jsonl`, `results.json`, and `evidence.md`, and uses separate subdirectories for current and
candidate lakes. It creates only uniquely named databases in the owned container. The owned runner
must durably record each intended database name and container identity in the run manifest before
creation or use, check absence, and record creation/migration outcomes. A collision stops the run.
For current-source probes, reuse `tests.support.postgres.with_database` and `alembic_config`, then
call `alembic.command.upgrade(config, "head")` against that owned database. Do not use
`migrated_database(server)`: its unconditional `finally` drops the database WITH FORCE even on
failure (helper lines 51–61). Do not edit that helper or wrap a probe in destructive teardown.
Do not call `truncate` on anything except that newly created database. Candidate tables live in a
distinct database/schema and are created by owned probe SQL, not by changing Alembic files.
Migration failure, timeout, hang, uncertain creation, or uncertain process state preserves the
database and its manifest for parent reconciliation. Database deletion is allowed only after
successful evidence capture and explicit ownership/process reconciliation under the cleanup
contract below; never drop in `finally` or force-disconnect a possibly live probe.

Build a real `PostgresStore(url, pool_size=4)`, `await connect()`, `build_runtime(settings,
store=store, storage=PosixStorage(root=owned_lake), ...)`, then `create_app(runtime=runtime)`.
Own and close each resource even if startup fails. `tests.support.api.service` is typed to
`MemoryStore` (lines 100–124): using that fixture alone is not a PostgreSQL race experiment.
Use HTTPX ASGI transport for current API behavior and a private uvicorn subprocess only where
separate-process or CLI network behavior is necessary. The runner must sanitize inherited service
configuration and never consume `dev.env` or a user's tokens/state.

### Cases and decisive observations

| Probe | Required current counterexample/control | Candidate experiment and acceptance observation |
| --- | --- | --- |
| P1: rejection and authorization | Commit bytes A, complete overwrite B, advance metadata version, submit stale B commit. Also revoke permission after upload and exercise invalid tree/receipt refusal. Capture DB file row and both byte hashes, not just HTTP status. | All pre-acceptance refusals leave A at the public name and unchanged final DB rows. B remains private/ineligible or ready according to the exact rejection rule. |
| P2: replay identity | Pending upload with no source, unrelated same-size public B; wrong marker; link at source/destination; termination/deletion while hashing. | No false ready receipt, no destructive undo of foreign bytes. A synced owned seal manifest can recover only its DB upload/object/attempt and hash. Missing or conflicting proof blocks/quarantines. |
| P3: crash matrix | Establish the current link-before-receipt/backup-drop windows without changing source. | Kill only owned worker subprocesses immediately before/after data fsync, seal manifest/dir sync, ready commit, acceptance, temp link, public rename/unlink, parent sync, step ack, final DB commit, response, and GC release. Restart and inspect rows, object IDs, bytes, count/version/audit, pending state, and charges. All architecture section 6 outcomes must hold. |
| P4: duplicates/order/fencing | Use two independent current runtimes on one isolated DB/lake; force link order opposite receipt order and duplicate backup creation. | Duplicate request/same digest yields one outcome; changed digest conflicts. Force reverse upload creation/completion order and clock ties/skew. Second writable candidate process refuses while the first is alive or uncertain, even after lease loss. Old owner resume cannot coexist with an authorized replacement. |
| P5: exact CLI outcomes | Lose request before apply versus answer after apply, then make unrelated metadata advance. Include removal-only, mixed, and zero-add/remove requests. Demonstrate the current removal-only false success. | Durable local UUID resolves exactly that operation. Rejected/unknown/blocked retains stage. Consumed upload routes to its operation, expired uploads reupload, superseded attempts cannot publish. Release an old timed-out hook after newer success and assert newer public bytes stay. |
| P6: local concurrency/crashes | Separate commands race current add/rm/pull/checkout with push; inspect fixed-temp and split-state windows. Do not mutate a real XDG directory. | Race every local mutation under the one candidate lock. Kill before/after spool fsync, state temp fsync, replace, directory sync, request send, final state replace, and GC. No lost intent or partial state. Test same-size edits, growth, truncation, pathname replacement, partial resume, ENOSPC, and retained old spool. Report source-snapshot limits even if detection catches a case. |
| P7: admission/lifecycle | More than 4 hashes/8 short calls; pool exhaustion; queued cancellation; failed startup and shutdown during placement. Controlled I/O barriers only. | Finite queues/bytes/counts; zero-byte count limit; no release before physical cleanup/quiescence; recovery capacity retained. Total readiness deadline includes DB/key waits. Store cleanup on failed startup, tracked drain, no new work after ownership loss. No claim to stop a kernel NFS call. |
| P8: real tusd/nginx | **External asset gate**, not runnable with current images. | Pinned real tusd: empty creation, duplicate pre-create, final PATCH timeout/retry, HEAD resume, rejected hooks, expected hash, writable-FD lifetime after finish, auth-before-body, cancellation during PATCH, restart and safe per-upload cleanup. Copy-and-seal bytes stay unchanged even if source changes. No production qualification until observed. |

P3 also interrupts immediately before and after every public-parent mkdir, private-directory mkdir,
empty-directory rmdir, and each corresponding containing-directory sync. Inject sync errors at
each boundary. Retry both already-existing and already-missing owned directories; verify identities,
inheritance, retained pending work, and no ready/step acknowledgment/final success on sync failure.
These local process-crash/fault probes do not prove power-loss persistence or NFS/ONTAP durability.

For the candidate publication slice, include one two-file overwrite/remove operation and a third
unrecorded sentinel; preserve the sentinel across every crash. Verify all final rows/bytes, not
private call sequences. Include nested paths, maximum allowed path components, case-fold collisions,
case-only spelling changes, file-to-directory and directory-to-file changes, and symlinks above/at
each relevant object/temp/target/marker. Compare an outside-tree snapshot before and after.

A model-level state explorer supplements, but never replaces, real adapters: enumerate duplicate,
timeout, cancel, expiry, supersede, accept, step, finalize, delete, and GC transitions over two
uploads/two paths/two clients. Check invariants after every transition; record any counterexample
trace. Do not treat a state-model run as a durability or tusd test.

Use deterministic barriers and controlled time/IDs. Exercise quota failure at each scope and the
exact boundary; free counters must never go negative or release twice. A blocked accepted operation
must remain charged through expiry and attempted deletion. A stale cleanup cannot delete a newer
object at a reused public path. Reopen/re-hash sealed data in a new process after each crash.

Workload sample, not capacity certification: 50 actor identities, 8 concurrent uploads, 0/1 byte,
64 MiB minus one/exact/plus one, and 10,000 zero-byte entries with 10,001 rejected. Use scaled finite
test quotas to force saturation without allocating a production-sized file. Run the larger chunk
sample separately if it threatens the slice deadline; record it as unrun until completed, never skip
it silently. Maximum supported production file and aggregate load remain an external measured gate.

### Existing coverage and fixtures to reuse

Before adding probe tests, read parametrized cases and fixtures, then reuse/extend observable
behavior rather than copy private implementation assertions:

- [API conftest](../tests/unit/api/conftest.py): marked real temporary lake and upload target,
  but its service store is memory unless explicitly assembled otherwise.
- [Disk helpers](../tests/support/disk.py): `snapshot`, `plant_symlink`, `PausingStorage`,
  `SIGNAL_TIMEOUT`; unbounded `StalledStorage.release.wait()` needs an owned bounded wrapper.
- [tusd hook helpers](../tests/support/tusd.py): `FakeTusd`, `UploadTarget`, hook request shapes.
- [CLI support](../tests/support/cli.py) and [fake tus transport](../tests/support/tus.py).
- [Lake builders](../tests/support/lake.py), [controlled clocks](../tests/support/clock.py),
  [PostgreSQL helpers](../tests/support/postgres.py), and
  [contract fixtures](../tests/contract/conftest.py).
- [Storage matrix](../tests/unit/storage/test_containment.py),
  [storage races](../tests/unit/storage/test_races.py),
  [upload hook tests](../tests/unit/api/test_upload_hooks.py),
  [CLI upload tests](../tests/unit/cli/test_push_tusd.py), and
  [PostgreSQL race tests](../tests/contract/test_postgres_races.py).

If fixture scope is unclear, a future probe worker can run, from root:

```sh
uv run --offline --no-sync pytest --fixtures tests/unit/api/test_upload_hooks.py -q
uv run --offline --no-sync pytest --fixtures-per-test tests/contract/test_postgres_races.py -q
```

Do not use the nonexistent `unit` marker. Mocks are confined to network, subprocess, clock, or
deliberate filesystem fault-injection boundaries. Assert bytes, rows, errors, permissions, retry
outcomes, and recovery. No suppressions, new skips/xfails, weakened assertions, thresholds, or
exclusions. Existing copy-absence assertions (`test_collections.py:207–218`) are obsolete; a later
owned production test slice should replace them with tus/publication behavior, not retain them as
evidence of resume correctness. Prototype workers do not delete production tests.

### Evidence, failure, and cleanup contract

Results distinguish `current counterexample observed`, `candidate invariant held`, `candidate
counterexample found`, and `blocked/unrun`. A runner exit 0 means its explicitly selected experiment
completed with its expected observations; it is never product PASS. A candidate counterexample
blocks downstream phase writing and is useful evidence, not something to hide by changing a test.

Record exact command/cwd, versions, time/space budgets, seeded IDs, DB queries/results, hashes,
process IDs/exit status, crash point, pending/outcome state, counters, and retained artifacts.
No credentials. On timeout/hang report immediately, list only owned live resources, preserve the
lake/database/logs, and stop for parent reconciliation. Do not retry while an old process may live.

After successful evidence capture and explicit review of ownership labels/IDs and database names,
reconcile all owned processes and connections and prove them quiescent before deletion. Only then
may the prototype owner drop its exact recorded databases without FORCE, or stop and remove its
exact container, then its exact private volume/network. Failed or uncertain runs retain all these
artifacts for the parent, including migration failures. Preserve run evidence.
No broad `docker prune`, process kill, or recursive removal of an unknown path. If the worker fails,
the parent owns reconciliation; a successor never steals resources by age or name alone.

Independent evidence review must rerun the reproduction and judge what it proves. Serial review
then fix, at most three review cycles before escalation. The next executable phase plan must inline
the essential observations rather than depend solely on ignored scratch files.

## 7. Exact gate reconciliation for later phase planning

The actual [Makefile](../Makefile):68–84, not a nonexistent workflow marker/target, defines the
Python gate. With no dependency installation, from root:

```sh
UV_OFFLINE=1 UV_NO_SYNC=1 make gate
```

It executes these commands in this order (radon output is captured and must be empty):

```text
uv run ruff check src tests scripts/cli_reference.py scripts/ste_check.py
uv run ruff format --check src tests scripts/cli_reference.py scripts/ste_check.py
uv run mypy
uv run mypy scripts/cli_reference.py scripts/ste_check.py
uv run ty check
uv run ty check scripts/cli_reference.py scripts/ste_check.py
uv run lint-imports
uv run python scripts/cli_reference.py --check
uv run python scripts/ste_check.py
uv run pytest -m "not integration" --cov=src/huron --cov-report=term-missing
uv run radon cc src --min C
uv run radon mi src --min B
uv run complexipy src --max-complexity-allowed 15
uv run python scripts/check_schema_map.py
```

The gate includes contracts and therefore needs PostgreSQL. Future owned checks use the isolated
server via `HURON_TEST_DATABASE_URL` so helpers do not pull/start a different container. Preserve
the 90% overall floor (`pyproject.toml:105`), touched-source 100% coverage or a specific unreachable
line justification (plan:2821–2823), empty radon output, complexity maximum 15, all current import
contracts, and the source scope. Do not lower any threshold to handle a baseline failure.

For persistence/publication phases add independent real tiers, from root:

```sh
uv run --offline --no-sync pytest -m contract
uv run --offline --no-sync pytest -m integration
```

`make test` uses `-m "not contract and not integration"`; that is the valid unit-only selection.
Discovery demonstrated `pytest --collect-only -m unit -q` exits 4 (unknown strict marker), after
2,203 tests were collected. Its integration collection exited 0 with two selected/2,201 deselected:
`test_section_one_end_to_end` and `test_every_role_end_to_end`. The latter is skipped at
`tests/integration/test_cli_end_to_end.py:34–37`; the former builds an API without a lake at
`test_api_postgres.py:26–32`. Neither qualifies real ingestion. CI's acceptance of pytest exit 5
is not test evidence. Do not manufacture a green integration tier by retaining that skip.

### Missing harness work, not a reason to edit tooling now

Discovery demonstrated `make -n docs` is a successful no-op and `make -n test-acceptance` exits 2
because there is no target. The workflow also lists pydoclint, pyscn, and duplication checks not
implemented by the current `make lint`. This writer inspected the Makefile and did not modify it
or the workflow to hide the mismatch.

A future code dispatch must explicitly own these harness additions before claiming those gates:

1. Real tusd/nginx isolated integration fixture with pinned offline images, private ports, and
   safe teardown; actual CLI upload/remove/overwrite/resume behavior, with the old skip removed.
2. Real PostgreSQL/filesystem publication-crash and recovery tests, including per-entry durable
   observations, late actors, local-state crashes, quota conservation, and ownership loss.
3. Bounded ingestion/workload acceptance runner with explicit file sizes, aggregate bytes, queue
   limits, latency/throughput reporting, free-disk preflight, and owned outputs. It may be exposed
   through a new target only in that assigned code slice. Until then no acceptance target exists.
4. Deployment render/smoke harness updated for single writer and offline provisioning. Shared
   cluster mutation requires an explicit resource assignment, not an incidental test command.

The asset owner separately resolves the workflow/tool availability mismatch. If a duplication
guard is restored, preserve its documented similarity 0.80/no-new-or-grown-clones rule; do not
invent a passing baseline or weaken it. Missing required infrastructure remains BLOCKED.

### Additive boundaries and their real commands

API contract writers regenerate from root with `UV_OFFLINE=1 UV_NO_SYNC=1 make openapi`, then
`npm run generate:api` from `web/`. Reviewers check snapshots, not edit generated files. Run
`uv run --offline --no-sync pytest tests/unit/api/test_openapi_snapshot.py tests/unit/test_error_contract.py`
in addition to the applicable full gate.

For web changes, from `web/`, every command must pass and check must have 0 errors/0 warnings:

```text
npm run check
npm test
npm run lint
npm run build
npm run test:e2e
```

Visible changes also need prescribed mobile/compact/desktop, light/dark/forced-color browser QA.
No browser work applies to these design files. No Svelte autofixer is installed; do not download it.

Actual site documentation commands are, respectively, root, `web/`, and `web/docs-site/`:

```text
UV_OFFLINE=1 UV_NO_SYNC=1 make docs-check
npm run docs:build
npm test
```

`docs:build` includes sync, Astro build, and post-build link checks. Confirm offline dependencies
before promising it. The two files in `design/` are not site-doc changes and require only the
assigned text/reference/link validation, not a product suite or site build.

After future deployment artifacts exist and offline images are supplied, preserve the M11
verification commands with no implicit image pull:

```text
docker run --rm --pull=never tusproject/tusd:v2.10.1 -help
docker run --rm --pull=never --entrypoint sh tusproject/tusd:v2.10.1 -c true
docker compose -f docker-compose.app.yml config --quiet
docker compose -f docker-compose.uploads.yml config --quiet
bash -n scripts/e2e.sh
uv run --offline --no-sync pytest -m integration tests/integration/test_uploads_tusd.py tests/integration/test_cli_end_to_end.py
kubectl kustomize deploy/openshift
kubectl kustomize deploy/local
helm lint --strict deploy/helm/huron -f deploy/helm/huron/ci/example-values.yaml
helm template huron deploy/helm/huron -f deploy/helm/huron/ci/example-values.yaml
cmp deploy/openshift/nginx-uploads.conf.template deploy/helm/huron/files/nginx-uploads.conf.template
```

The real integration fixture must run `nginx -t` on its rendered configuration. The proposed
Compose uploads file, local overlay, tusd test, and nginx files are currently absent. Helm is
unavailable; its old fallback image `alpine/helm:3.16.4` is absent too. Do not call these delivered
commands now. Local-cluster build/smoke/teardown targets also need implementation and explicit
owned context/resources before running. ONTAP setgid/security-style, AUTH_SYS, actual NFS durability,
and fencing evidence remain external; local ext4 or hostPath cannot replace them.

If agent assets change in a separate assignment, their gate is from `.agents/`:
`npm run check`, `npm test`, and
`OPENCODE_DISABLE_EXTERNAL_SKILLS=1 node scripts/check-resolved.mjs`, with declared
`build:agent-tools:write`. This architecture work does not qualify the pre-existing agent-tool dirt.

## 8. This writer's validation receipt

All checks run from `/home/karl/repo/huron-tusd`. Initial commands were read-only except normal
tool-owned output capture. No product suite, service start, dependency install, site build,
agent-tool suite, or prototype was executed; none applies to the two approved prose additions.

| Command/check | Outcome |
| --- | --- |
| Initial `git status --short --untracked-files=all`, `git rev-parse HEAD`, `git symbolic-ref --short HEAD` | Exit 0 individually; exact inventory/ref above. Combined shell command ended 2 because the following whitespace check failed. |
| Initial `git diff --check` | Exit 2, existing generated OpenAPI whitespace at line 170. |
| `git diff --cached --check` | Exit 0, no diagnostics. |
| `git branch --list m11.5-escalated` | Exit 0; branch present. |
| `git hash-object IMPLEMENTATION_PLAN.md` and `git hash-object migrations/versions/0003_uploads.py` | Exit 0; hashes above. |
| `git diff -- migrations/versions/0003_uploads.py` and cached equivalent | Exit 0, no output. |
| `git ls-files roadmap` | Exit 0, no output. |
| Concrete-child `git check-ignore -v` | Exit 0; all three paths matched `.gitignore:2:__pycache__/`. |
| Absence checks through file reader | Both owned file paths and `design/` absent before writing; no unknown file overwritten. |
| Final `git diff --check` | Exit 2; the same pre-existing `web/src/lib/api/openapi.ts:170` trailing whitespace and no other diagnostic. |
| `git diff --no-index --check /dev/null design/m11-production-architecture.md` | Exit 1 because the new file differs from `/dev/null`; no whitespace diagnostics. |
| `git diff --no-index --check /dev/null design/m11-review-evidence.md` | Exit 1 because the new file differs from `/dev/null`; no whitespace diagnostics. |
| `uv run --offline --no-sync python scripts/check_links.py design/m11-production-architecture.md design/m11-review-evidence.md` | Exit 0, no output. |
| Final status/ref/hash/branch recapture | Exit 0. Initial inventory retained, plus only the two owned design files; HEAD/ref, old-plan hash, 0003 hash, and reference branch unchanged. |
| Manual reference and contract self-check | Existing linked files resolve. Actual Makefile/package commands and pytest markers checked; proposed/absent artifacts are labeled. All 19 task rows and the repair resolution retained. Not independent review. |

Check exit statuses were captured explicitly with shell variables and `declare -p`, not inferred
from a wrapper's final exit. The text was reread. Self-check tightened GC's two-transaction boundary,
retention versus cleanup ownership, duplicate-seal accounting, and kept-directory tombstones.
Two attempted text patches had unmatched context and made no changes; minimal owned-file patches
were then applied. No unknown work was reverted. The link and new-text checks were repeated after
the final receipt edits before handoff.

The link checker validates relative file existence only, not anchors or unlinked proposed filenames.
Future/proposed paths and commands are explicitly labeled above; they are not delivery claims.

## 9. Review handoff and blockers

### Independent review 1 and planning fix attempt 1

Independent reviewer `ses_e41912c8effefzK43sk1bh9L4w` returned terminal **FAIL** with two findings.
This fix dispatch is `c36e848d-d977-4aa8-8233-651f234c4225`, child
`ses_e418f28b5ffe4YOAVFr7gf3YAW`, role `fix`, activity `planning`, claim `*:write`.
Recorded profile is preparatory, configured Low; provider effort is unproven.

| Finding | Writer disposition |
| --- | --- |
| Destructive PostgreSQL helper conflicts with preserve-on-failure policy | Writer-fixed pending re-review: require an owned recorded database lifecycle, reuse only URL/migration configuration helpers, and prohibit unconditional/forced teardown. Failed or uncertain artifacts remain for reconciliation. Helper unchanged. |
| mkdir/rmdir/private directory creation lack containing-directory sync ordering | Writer-fixed pending re-review: architecture requires per-directory sync, ownership-aware idempotent retries, and no acknowledgment/ready/final success on sync failure. Crash matrix and P3 include every new boundary and fault injection. No local power-loss/NFS proof is claimed. |

These are prose corrections only. No prototype or test was added or run, and this self-check is
not independent review or a PASS. Independent re-review remains required.

The parent should next dispatch independent architecture review of both files, then the isolated
prototype slices, then independent prototype evidence review. Only reviewed results can seed a
self-contained executable replacement phase plan. This writer's self-check is not that review.

| Gate / owner | Required next action |
| --- | --- |
| Independent architecture reviewer | Check publication/retention/lock/quota/cancel invariants, mutation ordering, bounded source semantics, and the exact supersessions against the preserved plan. |
| Prototype owner and independent reviewer | Implement/run only the ignored, isolated probe assignment; preserve current counterexamples and any candidate failures. No production promotion. |
| Offline asset owner | Supply pinned tusd/nginx and later Helm assets without downloads by these workers; run the real handoff/replacement probe. |
| Storage and cluster operators | Approve and demonstrate a usable external fence; record actual ONTAP setgid/security style, AUTH_SYS, sync/cache/outage evidence in an owned follow-up. |
| Site/workload owner | Supply maximum file, aggregate budget, concurrency expectations, and recovery/outage tolerance for measured qualification. Roughly 50 scientists is a hypothesis, not capacity evidence. |
| Agent-asset owner | Resolve absent language/instruction skills and workflow gate drift separately. Do not patch tooling as part of product architecture. |
| Parent / data owner | Approve any reuse/export/re-ingest of old test-bed data; otherwise use a fresh paired database/lake. Preserve 0003 and all initial dirty work. |

The design selects recoverable per-file visibility, required request identity, copy-and-seal,
single fenced writer, roll-forward after acceptance, finite admission, and local spooling. It does
not leave those engineering choices open. A demand for strict snapshot visibility or overlapping
writers would be a new external approval decision, not a hidden implementation detail.

## 10. Subsequent reviews and replacement-plan synthesis (2026-11-09)

The parent supplied these terminal outcomes for this synthesis; the writer read the actual
prototype reports/scripts/review2 results and verification log as well. Earlier FAIL/BLOCKED
records above remain history and are not rewritten into PASS.

| Subject | Subsequent disposition |
| --- | --- |
| Architecture review2 `ses_e418d3df1ffemcl49SpFu2Fxh7` | Preparatory PASS for bounded architecture/prototype handoff after both prose fixes. Not complete design or product qualification. |
| Prototype attempt1 `ses_e418afe08ffeZsw6A4Sev8ItbX` | Maximum, BLOCKED before behavior probes: Docker did not publish the specified loopback endpoint. Private resources/failure retained. |
| Prototype attempt2 `ses_e417b817dffeIue88PU914fPDa` | Preparatory narrow probe after parent approved the same retained container's private bridge endpoint. No networking/shared-service mutation. |
| Prototype review1 `ses_e417596feffe0nPZoj4GhNFbVj` | Preparatory independent rerun exit0 but FAIL: allocation manifest missing directory syncs. |
| Prototype fix `ses_e4172c685ffe81WFgbWSbBeALc` | Preparatory ignored-only fix: two directory syncs and fault checks, verifier selects actual run via HURON_PROBE_RUN. |
| Prototype review2 `ses_e41701208ffeePja0AkjkcfOrw` | Preparatory terminal PASS for narrow evidence; probe review2 and run-specific review2final --stop each exited0. |
| Plan synthesis `ses_e416d6114ffeSnhTOmiw4wDVwF` | Maximum implementation/planning, attempt1, dispatch f33fd29c-853a-4abd-8cb6-41d03ddacda7, *:write; self-check, not independent review. |
| Independent maximum replacement-plan review1 `ses_e414a07b4ffeiXZm8gPW2sUSqu` | FAIL; two blocking plan defects, preserved and dispositioned in section 11. |

The new durable prototype file includes exact commands, results, SHA-256 evidence hashes,
compact source excerpts, limitations and retained ownership. No essential conclusion depends
only on ignored scratch. In particular, the candidate was a small real-PG/FS model with logical
reconnects, **not** a killed-process/full-application/NFS proof. The real Placer counterexamples
did not execute a PG rejected commit; StateDir was two processes rather than whole CLI commands;
`_recover` used remote network answers faked; eligibility was pure model logic.

The replacement plan contains 42 small serial slices (P00–P39, with P27a/P27b/P27c), retains every M11 task and the
exact M11.12 documentation scope, and makes real application process-crash/duplicate-runtime,
real tusd integration, quotas/workload and external storage qualification actual gates. Only
P00 is ready for a separately admitted discovery assignment; later dependencies and blockers
remain explicit. Review1 failed; maximum review2 is pending after writer fix1. Its temporary unexposed schema/composition
staging is an implementation detail to approve at prerequisite freeze, never mixed production
writers or compatibility for old commit bodies/local state.

This synthesis owns only new `IMPLEMENTATION_PLAN_LATEST.md`, new
`design/m11-prototype-evidence.md`, and status/history/cross-link updates in these two design
files. Initial status was recaptured unchanged except those two earlier owned untracked design
files. HEAD/ref, reference branch and the old-plan/0003 hashes matched section 2. Root diff check
still reports only the existing generated OpenAPI whitespace at line170; this writer does not
fix it. User-owned agent tooling, application/repair dirt, old plan and probe artifacts remain.
The stopped prototype container, volume, network and four probe DBs are retained for the parent;
no restart, deletion or cleanup permission is implied.

Planning validation receipt is in the replacement plan's section 11, with the final command
outcomes also returned to the parent.
The applicable checks are root/new-text whitespace, four-document relative links, actual command/
path inspection, all-task/finding coverage and serial dependency review. Product/site suites do
not apply to these root/design-only prose edits. Missing language/instruction skills and workflow
gate drift remain asset-owner issues, not fetched dependencies or silently passing checks.

## 11. Replacement-plan review1 and planning fix1 (2026-11-09)

Parent-supplied terminal maximum reviewer `ses_e414a07b4ffeiXZm8gPW2sUSqu` returned **FAIL**.
Fix dispatch `b3f5cfb2-3585-43c6-94bf-35f0f73e356e`, child `ses_e413f9417ffeT4PMGHHwxXjNpM`,
is fix/planning, preparatory Low, serial `*:write`. Configured profile is not observed provider
effort. No delegation, code/config/test/probe/service/tooling/Git mutation is authorized or done.

| Blocking finding | Writer disposition, awaiting independent maximum review2 |
| --- | --- |
| P07 denies PG writes while its GC gate still runs ordinary build_runtime legacy mutation integration; conversion delayed to P27c | P07 now owns tests/support/legacy.py explicit PG constructor/test-only ASGI override and the actual integration caller. Production has no bypass setting. Existing real-PG role/domain assertions remain; runtime tests keep ordinary disabled-start coverage. Caller inventory covers direct domain, memory, production-disabled and isolated PG categories. P27c deletes the helper/override after journal conversion; P28 tightens only after direct fixture conversion. |
| UUID/body/digest local recovery lacks the server's instance/principal namespace | §3.5 now defines durable RecoveryBinding, authenticated combined identity route, DB/config/marker identity persistence, expected-binding request checks, TLS/canonical endpoint policy and explicit same-binding endpoint acceptance. P03/P22–P26/P29 add actor/instance/override/removal-only tests. P09/P11/P16/P27a/P27c/P31 own schema, adapters, validation, API and offline initialization. P06 freezes before downstream work; tests initialize via P11 so P31 introduces no cycle. |

Rechecked actual runtime.py build_runtime/bootstrap behavior; test_api_postgres.py:20–48,88–111;
contract/runtime and direct bootstrap callers; CLI config.py environment overrides and client.py
absolute-URL handling; auth.py whoami and health.py healthz. The existing settings UUID and separate
auth subject are real; the combined route/table/binding and new commands are proposals, not existing
fields. No /info route was assumed. Preserve all earlier review/prototype failures and limitations.

Owned changes are only the four plan/design records. The architecture's section 13 records the
proposal corrections; prototype evidence adds review history/explicit untested limits, not results.
All 42 slices, 19 M11 rows and F1–F7/O1–O16 coverage remain. The complete prose validation receipt
for this fix follows in the replacement plan; product/site suites are not applicable. This writer's
checks are not independent review. No design-ready, implementation-ready or product verdict is given.

## 12. Replacement-plan review2 and planning fix2 (2026-11-09)

Parent-supplied terminal maximum reviewer `ses_e41375e91ffeReJef3Uy9rhbnM` returned **FAIL**.
Review1 P07 and instance binding are resolved except the two findings below. Fix dispatch
`6d0c6f4b-86ac-4918-b170-0ade3e50eaf3`, child `ses_e412f6ce4ffer6joD6no6pwOVR`, is
fix/planning, configured preparatory Low, serial `*:write`; provider effort is not measured.

| Finding | Writer disposition pending final maximum review3 |
| --- | --- |
| HIGH: identity authentication precedes local destination trust; refresh can leak to selected issuer/API | §3.5 specifies local approval and credential-provenance checks before any credential-bearing identity/refresh/exchange. P23 owns Services/Session/Oidc/ApiClient, TokenState, errors and legacy token refusal. First login and endpoint move require informed approval and fresh destination-specific auth. P22 atomic manifest covers acceptance rollback/crash selection. P03/P23/P25/P27b/P29 require transport-observed non-disclosure with valid/expiring tokens and all selection changes. |
| MEDIUM: new context root absent from exact registry/panel ownership | P27b owns commands/__init__.py::LAYOUT, Settings placement, context.register single group registration, test_panels.py expectations and existing org/catalog coverage, generated help/reference and full GP/GD gates. No duplicate registration or weakened layout guard. |

Static reread: client.py:45–49 attaches token before URL dispatch; Services.oidc/session/api:55–68
uses effective selections; login.py:160–185 refreshes then exchanges; state.py:20–27 has no token
provenance. context.register:49–52 registers only org/catalog; commands/__init__.py::LAYOUT and
test_panels.py::EXPECTED omit context; scripts/cli_reference.py:95–106 rejects unplaced commands.
These are inspected facts, not executed leak tests. Proposed symbols are not delivered code.
Only the four owned documents changed. History, 42 slices, 19 M11 rows and F1–F7/O1–O16 remain.
No probe/service/product suite ran; the plan's fix2 receipt records prose checks. Self-check is
not independent review; review3 is the final permitted review before reconciliation on failure.

## 13. R3-1 focused planning reconciliation, writer attempt1 (2026-11-09)

The full handoff, full replacement plan and all three design records were read, with AGENTS.md,
orchestration/verification, assignment/phase/design templates and domain guidance. Canonical
implementation-plan and design-plan skills were loaded. The local skill directory still has no
asd-ste100 or writing-for-agents; this is policy drift, not permission to fetch or claim formal
qualification. This writer reread actual credential sources, callers, fixtures/tests, Makefile,
active docs and historical M11.11:5158–5245, including the raw-token smoke at 5220–5226.

Dispatch 74172ff5-25cb-4bbc-b53a-e76fab96563e, child ses_e410c833fffesQVUD7YKqcsdDO, parent
ses_e41163e2cffegYfUEyI61BqEIg: implementation/planning, reconciliation attempt1, configured
maximum, model openai/gpt-6-astra. Provider effort acceptance is not-proven. Conservative *:write
coordinates the worktree/shared check outputs only; no service or port assigned. Exact edit scope
is IMPLEMENTATION_PLAN_LATEST.md and these three design records. HANDOFF_M11_PLAN.md, old plan,
source/tests/scripts/config/Makefile/tooling and every unknown dirty/untracked path remain read-only.

The parent supplied the earlier launch refusal, “Only markdown-orchestrator may launch workflow
children”, with status [] and no child started. The user selected the orchestrator switch and
Continue, and explicitly authorized substantive reconciliation then ONE additional independent
maximum review with no automatic retries. This writer acts only on the received ordinary dispatch;
no journal recovery/bypass, nested agent or self-resume. Parent records terminal and dispatches the
separate reviewer. The writer neither calls itself that reviewer nor claims acceptance.

### Inspected producer/consumer/reference inventory

These are static observations of the present tree, not executed security tests. Line numbers refer
to source files left unchanged by this planning turn. Future symbols and checks are specified in
the phase plan, not claimed present APIs.

| Present evidence | Classification and selected future owner |
| --- | --- |
| scripts/dev-login.sh:14–41,44–50 | Direct password-grant/exchange producer; password/company-token curl argv and O_TRUNC four-field JSON bypass all new collaborators. P23 creates scripts/dev_login.py; P27b deletes the entire shell helper/alias. A JSON-format-only patch is rejected. |
| CLI login.py:160–192; state.py:20–27,89–113,183–189 | Session.login exchanges/saves Tokens; token returns a valid bearer before refresh logic; state has no provenance and fixed unsynced temp. P22 primitives, P23 isolated new collaborators, P27b all-reader/producer cutover and old credential API removal. |
| commands/session.py:26–59, services.py:55–68, client.py:45–49, config.py:17–23,38–51, app.py:35–47 | Device/browser login calls acquisition before Session; config/env/global URL selection reaches a token callback before actual destination dispatch. P23/P27b share approval/provenance and FreshLogin for ordinary calls as well as recovery, with explicit uploads selection. Existing HTTP client follow_redirects=False is retained, not treated as destination approval. |
| scripts/e2e.sh:72–81,94–111 | Sources dev_login; login_as switches alice/bob/carol/dave/erin in one isolated state root. P27b changes invocation/secret/trust plumbing, P33 proves full real-stack every-role workflow. Current fixed ports/project and unconditional cleanup also need the already owned P33 isolation transition. |
| scripts/demo-noaa.sh:42–66,81–101 | Persistent isolated cache config/state, direct helper before describe-org; NOAA_RAW bypasses fetch; currently provisions online. P27b changes fresh login/inputs before first read without discarding cache; P33 moves provisioning before writer startup and tests cached offline rerun. |
| examples/noaa/load.sh:6–8,63,239–285 | Not a token writer: requires authenticated CLI, compares remote hashes, stages/pushes changes and republishes changed metadata. P27b removes raw-token bootstrap guidance/reset-adoption claims; P33 verifies unchanged cached rerun via real CLI and rows/bytes. fetch.py is data acquisition, not credential ownership, and is not run or changed here. |
| Makefile:55–57; README:22–48,158–197,254–298,373–375; examples/noaa/README.md:86–105 | Live entry points/instructions include direct shell helper/password and demo/e2e workflows. P27b owns auth/config/target/docs cutover, example approval JSON and stdin/terminal invocation. P33 owns stack resource wiring and actual complete run evidence. No command-change deferral to P36. |
| docs/architecture.md:194–214,240–243; docs/user-guide.md:7–17,32; docs/operator.md:381–393 | Active state/login and pre-release instructions. P27b updates relevant sections (including context Settings row), P33 full workflow/resource wording; P36 retains unrelated M11.12 duties. Raw token copying cannot remain a recommended workaround. |
| tests/support/cli.py:197–207; tests/integration/test_cli_end_to_end.py:88–94 | Two direct minted-token CLI-state producers. P27b replaces both positive login factories with approved fresh acquisition/exchange; no config-stamped provenance. The latter's pre-existing skip at34–37 remains baseline only until P33 replaces stack/removes skip, not new proof. |
| tests/unit/cli/test_login.py:14–24,100–129; test_foundation.py:75–97 | Existing device/browser/refresh/logout/error, private-mode and state coverage to retain/extend. Explicit invalid/malformed/legacy documents remain negative fixtures only. P23 tests new collaborators, P27b transitions old token tests and all actual command paths without weaker assertions. |
| tests/unit/cli/conftest.py:24–53; tests/support/cli.py::Cli/Router/LoopThread; tests/fakes/{issuer,prompter}.py | Reusable scoped tmp_path, memory-lake, controlled clock and HTTP/prompt fixtures. FakeIssuer.handler currently has no password grant; Router.observe runs after the IdP branch. P23 owns controlled grant/observation extension and new tests/support/devauth.py loopback/subprocess fixtures, not a separate issuer or fake durability claim. |
| Old IMPLEMENTATION_PLAN.md:5202–5204,5220–5226,5368 | Historical pod token injection/copy workaround. Old text is unchanged. P34 explicitly replaces it with independent host/pod fresh approved helper sessions, private XDG/emptyDir and local-only helper ConfigMap; no raw JSON injection. |
| CLI commands/__init__.py:26–35,56–68, context.py:49–52; test_panels.py:10–19,39–64; scripts/cli_reference.py:95–106 | Earlier registry correction retained: P27b owns context after config, one registration, existing org/catalog tests and five panels, generated reference; strict guard unchanged. |
| core/security/broker/{exchange,tokens}.py; API endpoints/auth.py; tests/support/api.py | Server token issuer/exchange and API-only bearer fixtures, not CLI-state producers. Real validation/PG tests retained. Already assigned recovery-identity/protocol work remains P27a/P27c; no R3-1 broker redesign. |
| docker/seed/run.mjs:428–471; web/e2e/support/seed.mjs::huronToken/SeedClient | Dev seed password grant/ephemeral exchanged-token cache, no CLI XDG files. Classify separately; P27c/P33 already own protocol/real-byte seed transitions. Do not introduce TokenState or the CLI password adapter into the seed merely to satisfy this inventory. |
| web/src/lib/server/{oidc,huron-api,sessions,guard}.ts and their tests; web/e2e fake IdP | BFF authorization-code exchange and process-memory sessions, separate auth owner, no CLI token writer. No auth rewrite in this slice. Retain relevant GW gates if existing protocol-consumer work touches web code. |
| CHANGELOG.md:43, docs/web-design.md:1425, architectural_review.md and old plan references | Historical/indirect e2e records, not live credential invocation owners. Preserve history; phase-plan supersession explains changed contracts. HANDOFF_M11_PLAN.md remains read-only and describes the pre-reconciliation finding/admission context. |

The source/test search found no additional CLI TokenState producers beyond those above. At future
cutover, P27b must re-inventory dev-login/dev_login/Tokens/write_tokens/tokens.json and classify every
remaining reference, including new callers; this static receipt is not authority to ignore later code.

### Writer disposition and acceptance still required

**R3-1, medium PLAN DEFECT:** writer-addressed by a concrete replacement design, **not independently
resolved**. The phase plan §3.5 now specifies one public scripts/dev_login.py interface, an exact
development approval JSON schema distinct from ordinary config, a repository-only password adapter,
and shared FreshLogin/DestinationApproval/CredentialStore/LocalState ownership. Approval precedes
credential-free discovery at the approved issuer and then approval of all used provider endpoints;
only afterward may fresh credentials leave. Existing tokens are never inputs to that fresh flow.
No secrets in argv/logs/progress and no --yes/trust-all shortcut. Legacy state remains refused and
preserved; explicit verified fresh login can replace credentials only, not working intent/bindings.

P22 owns atomic credential-only and combined endpoint primitives. P23's new collaborator and script
tests use isolated response fixtures without depending on the later identity route. P27b changes
all positive credential producers/consumers/docs at once and exercises helper then real CLI over
P27a's real router. P27c removes the P07 legacy PG test composition as before. P29 repeats real-app
crash/concurrency. P33 supplies full PG/API/IdP/nginx/tusd e2e and cached NOAA offline idempotence;
P34 supplies actual host/pod deployment smoke without token injection. Exact future commands and
isolated resource prerequisites, including separate host/pod approvals and cached NOAA input, are
inline in those phases. GDEV adds explicit script Ruff/format/mypy/ty checks because Makefile's
CHECKED_SCRIPTS covers only cli_reference.py and ste_check.py. GP/GC/GD and full workflows remain.

Required public tests cover absent/malformed/legacy state, permission/refusal, first approved fresh
helper auth then real CLI call, identity switches, valid/expiring tokens, changed API/uploads/issuer/
client/discovery/provenance, decline/auth/identity failure, contention and interrupted saves. Assert
zero password/company-token/bearer/refresh delivery at unapproved receivers, old credential bytes
and all intent retained on failure, and complete old/new generation recovery after commit boundaries.
Use real filesystem/PG where their contracts apply; no private-call-count substitute, no new skip,
xfail, suppressed failure or lowered coverage/threshold. No such test was run or added here.

### Preserved state and current check scope

Initial status matches §2 exactly plus the four already present owned plan/design documents and
HANDOFF_M11_PLAN.md. HEAD is 0dcdf1ff6a8689f704a73a0758a886c18b5d3584 on tusd-integration;
m11.5-escalated is 04958ad538eac69f16a6abdd3925350781e4d718. Old plan and 0003 hashes match §2;
0003 staged/unstaged diffs are empty. Initial tracked/cached numstat inventories were captured for
comparison without adopting their hunks. The first combined hash command named a nonexistent
migration path; the corrected read-only command captured the actual 0003 hash. No file was created.
Five context-mismatched patch attempts made no changes; smaller owned-document patches followed.

Only the four owned documents changed. Section 2's exact initial inventory and phase-plan §12 are
preserved. The prototype's seven hashes/narrow Placer/StateDir/_recover and six logical reconnect
observations remain; the new helper/NOAA/smoke contracts have no probe result. No service, container,
probe, product/site suite, P00, install, cleanup/reset/revert/stash/commit/push/branch or tooling edit
was performed. Applicable current checks are the complete five-document handoff link command,
root/cached whitespace, separate /dev/null whitespace for all five, and manual anchor/count/path/
dependency inspection. Outcomes are in phase-plan §13 and the writer's terminal report; they are
self-check evidence, not an independent review or acceptance. Original FAIL/FAIL/FAIL remains.
