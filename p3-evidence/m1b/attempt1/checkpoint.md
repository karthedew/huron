# M1b attempt 1 — incomplete implementation checkpoint

No functional acceptance or verification verdict. Parent owns P3_EXECUTION.md.

Current additions (all untracked; preserve unrelated working tree):
- core/integrity/models.py: Pydantic canonical evidence, observations, exact legacy membership, transitions, maintenance grants.
- core/integrity/ports.py: consumer-owned LegacyStorage, MaintenanceAuthority, WriterExclusion, DatabaseExclusion, LegacyMaintenance.
- core/integrity/verification.py: canonical document/identity/ancestry verifier, full storage inspection, degraded findings, missing envelope handling. Exact parent generation documents still NOT validated.
- core/integrity/cutover.py: grant authentication, controller/role fencing, periodic checks via TaskGroup, union catalog/storage inventory, resolve, durable report then numbered record, retry. Not wired or tested yet.
- pkg/rawstore/maintenance.py: descriptor-based traversal, regular-file streaming, seal/owner/link/inventory checks, immutable evidence installation. Missing IO-error-per-file handling needs improvement; current descriptor exceptions can stop scan. Read controls bounded 64MiB; mutation defenses untested. Root unknown entries and structural generation inventories need review.
- pkg/metastore/maintenance.py: PostgresRoleExclusion, dedicated owner/admin refusal, NOLOGIN old/new, old direct/parent grant revocation, confirmed termination, public/table/column/security-definer effective access checks.
- pkg/metastore/legacy.py: strict schema0010 maintenance, parent lookup/import/degraded findings/session resolution. NEW and not tested. Needs import audit, existing row conformance and complete migration guard tests review.
- schemas protocol-inventory-v1.json and protocol-transition-v1.json generated from models. Loading round trips tested; schema map and malformed conformance completeness pending. Runtime validators enforce constraints beyond generated schemas; review schema parity.
- unit tests: test_protocol_documents.py (10), test_integrity_storage.py (11), test_legacy_verification.py (9).
- contract test_writer_exclusion.py (2).

Tests observed:
- 30 focused unit tests passed before latest missing-envelope/core/legacy additions.
- Models100%; maintenance97.14% (line66 oversized-after-open,208-209 file-kind race defense); verifier96.20% (unreadable document exception path); ports not imported during focused tests0%.
- Real PostgreSQL role tests2 passed4.65sec; log role-contract.log. Retained process31841 completed successfully. Disposable Podman VM started within same parent Python process as pytest; stopped machine across command lifecycle is normal. Machine rootful Podman6.0.2. Docker socket from machine inspect ConnectionInfo.PodmanSocket.Path; TESTCONTAINERS_RYUK_DISABLED=true.
- Focused Ruff/mypy/pydoclint and radon/complexipy passed for current core after identity helper decomposition; rerun all after edits.
- No full gate, docs, coverage ratchet, source/native inventories, actual old artifact/controller proofs or final diff review yet.

Controller design (implemented, runtime proof still pending):
Root-owned local named volume backing inaccessible to app UIDs; root-owned daemon socket unavailable to app or ordinary operators. Root controller authenticates ordinary operators using Unix peer credentials and configured operation/root grants, mediates all normal restart authority, persists fenced state before stopping/removing complete daemon-wide writer inventory. No app daemon socket. Generation changes invalidate scan. Root/daemon/storage administrators explicitly trusted, ordinary Compose automation cannot directly use daemon. Refuse unmanaged host/bind mount, remote/NFS volume, unreachable daemon, foreign/privileged bypass containers. Need an actual controller with restart admission, not listing/removal-only proof. Controller-managed Compose first; implement actual startup/restart path and test old artifact. Current Compose has no Raw volume and uses DB owner; Containerfile command stale huron.service.api.main:app (fix to applications.api); don't use broken old startup as exclusion evidence. Actual old source available before M1a via git history: HEAD6082088; older commits49e26b2,80b6def,db5fc84; inspect before selecting/pinning old source. May build disposable actual historical source artifact and record digest.

Remaining large work:
1. Enforceable controller + authenticated client adapter + Compose/dedicated DB identities, settings/wiring/main lakectl entry/import contracts.
2. Complete structural generation and identity verifier/schema parity/missing-corrupt behavior.
3. Core coordinator tests (including lost midscan fence, auth rejection, report-before-record resume, exact membership) and filesystem remaining error defenses.
4. PG legacy adapter full real contracts including sessions/claims/migrations0010->0011, role column/function/ownership/admin/inherited tests, unit boundary tests for adapter line coverage without substituting them for real proofs.
5. Genuine controller/old-artifact already-admitted writer shutdown + restart/readiness/write refusals, foreign writer/generation/unreachable/fence loss integration.
6. All requested gates, whole coverage>=94.96 ratchet, touched100% except independently reviewed unreachable defenses. Keep native pyscn90 settings unchanged; report known sub90 failure separately per user exception. Fullsrc native JSON/logs/counts/source hashes in attempt1.
7. Docs design/deployment current status; update M1a pending phrases to independent functional PASS link ../p3-evidence/m1a/verification1/report.md. M1c init/startup/activation not shipped; no fullP3 completion.

Skills read: project .claude/skills/oop-design, .agents/skills/codebase-design, .agents/skills/postgresql-table-design. No FastAPI edits yet. Read complete workflow/P3 plan and P3_DESIGN (some combined tool output was truncated; re-read relevant omitted portions if needed), AGENTS, relevant architecture/raw/rbac portions. Parent instructions forbid nested delegation and all production cutover/roles/services modifications. No commit/push. Maintain 60sec updates to parent where possible and required <=15min progress contract.


## Resumed implementation update

- Added applications/lakectl/{engine,settings,controller,exclusion,server,wiring,main}.py.
  Root-only Linux controller owns durable restart admission, authenticates Unix peer
  credentials, inventories all daemon containers and refuses foreign mounts/privilege.
  It binds named-volume device/inode and controller generations. Authenticated describe
  supplies actual storage path/owner/device/inode to root-local CLI wiring; arbitrary
  scanner paths are not accepted. Root/daemon/storage administrators remain trusted.
- CLI now wires CutoverService to real ControllerClient, PostgresRoleExclusion,
  PostgresLegacyMaintenance and MaintenanceStore. Private maintenance configuration
  holds SecretStr database credentials. Commands controller, restart, protocol cutover
  --prepare are exposed via project lakectl entry point. No init/activation/startup claim.
- Application independence includes lakectl. Containerfile's stale service.api CMD fixed
  to applications.api.main. No actual Compose fixture/deployment policy installed yet.
- Focused Ruff/format/mypy/pydoclint pass for all eight lakectl files after wiring.
- Earlier focused tests now include 13 storage (100%), 11 legacy verification (100%),
  10 protocol models (100%), six coordinator (91.78%, nonempty/periodic cases pending).
  Real PostgreSQL two-role tests previously passed. No controller runtime proof yet.
- Remaining correctness review: private config read TOCTOU/ancestor ownership; complete
  structural generation validation; raw file IO errors as findings; complete effective
  DB sequence/database privileges; schema0010 import/audit/race contracts; controller
  run turnover after generation loss; actual Linux/old artifact fixture and full gates.


Latest measured progress:
- 41 focused unit tests pass (models/storage/verifier/coordinator); per-entry storage
  IO errors now become ENTRY_IO_ERROR and healthy sibling inspection continues.
- Expanded PostgreSQL contract test run: six of seven passed; remaining test GRANT
  lacked FUNCTION keyword and is corrected. Rerun session85712 active at checkpoint.
  Prior sequence-privilege query required CASE to prevent PostgreSQL planner calling
  has_sequence_privilege on ordinary tables; production corrected and six tests pass.
- Private configuration uses held no-follow descriptors, ancestor ownership checks,
  and 1MiB bound. Controller new-run acquisition advances generation without releasing
  exclusion, allowing full reverification after lost generation.
- Actual Linux VM Python3.13 venv/pip probe succeeded and cleaned its temporary root.
  Shared VM default daemon socket0660/store0755 is intentionally unsupported. Next
  fixture uses its own private root/runroot/socket, no shared daemon permission edits.
- Latest wiring/role changes passed focused Ruff/format/mypy; all nine import contracts kept.


## Actual runtime evidence (latest)

- Seven real PostgreSQL role tests pass11.49s, role-contract-expanded-pass.log.
- Schema0010 import/session/audit/findings/replay plus upgrade-to-head contract passes
  3.65s, legacy-contract.log. Adapter now rechecks imported row under lock and only
  marks healthy matching COMMITTING sessions COMMITTED; other sessions fail.
- Eight coordinator focused tests pass including nonempty real-document orphan and
  crash after report before numbered record, followed by same-fence replay.
- Real private Linux controller passed (controller-probe-labeled.log). Initial loader
  failures diagnosed using .agents/skills/diagnosing-bugs/SKILL.md: custom graphroot
  inherited var_lib_t; default is container_var_lib_t. Applying matchpathcon-derived
  default context with chcon on ONLY owned graphroot before extraction fixes runtime.
  No SELinux policy entries, shared graphroot/socket changes, or relaxed controller
  namespace/capability/security options. All owned resources cleaned.
- Historical source archive legacy-source.tar: commit db5fc84cd7bfe049692ef2abb16fb32570ccf5a2,
  archive SHA256 b1ad409fb8c193be2c03fb10aa63b0be4d11722cd0f364b52ba0aaab135de4dd.
  Current Containerfile additionally fixed missing README COPY found in real image build.
  Historical fixture changes packaging COPY README only; actual application source
  remains unchanged, and corrected applications.api.main command is passed at runtime.
- Actual historical HTTP proof PASS in legacy-http-authorized.log:
  image sha256:0c633b0486f93bf13fcb9ba9ba6854ad5dc827a8d9fbd11a909ad3aa32bfbcfa.
  Old API ready; create hierarchy and explicit developer binding via old API; begin
  upload; hold actual PUT with first64KiB observed on disk; disable/terminate old/new DB
  identities via dedicated cutover role; same HTTP request writes next64KiB despite SQL
  fence; controller terminates exact container; request closes and bytes stay unchanged;
  controller restart refused. All containers/image/network/volume/root cleaned.
- The successful probes are currently /tmp/huron-controller-probe.py,
  /tmp/huron-legacy-controller-probe.py (limited rawstore proof), and
  /tmp/huron-legacy-http-probe.py (actual HTTP proof). MUST convert successful HTTP
  scenario into durable pytest fixture/integration code; ad-hoc log is not final gate.
- Remaining: actual socket-peer/auth/foreign/generation/unreachable/lost-fence tests;
  old artifact restarted with revoked identity must show readiness/write refusal in
  addition to controller admission refusal; full structural generation validation;
  revision import audit completeness; schema parity; deployment config/docs; all touched
  coverage and full gates. No full M1b verdict, no coverage ratchet yet.

## Continued implementation checkpoint

- Durable expanded real Linux integration passed in `controlled-cutover-integration.log` (216.14 seconds): actual historical held HTTP request survives SQL exclusion, then controller shutdown stops it; revoked old artifact startup fails; real kernel UID authorization, wired core/storage/database preparation, foreign volume holder, changed generation and unreachable controller all exercised. Owned fixture root cleanup confirmed.
- Structural generation verifier covers exact database ancestry, CURRENT and full generation chain; canonical report binds structural digests. Complete integrity/rawstore focused suite was 58 passed, 100%.
- Added full unit coverage for every new lakectl and metastore maintenance module. First whole unit run passed 1,582 tests, 95.80%; every M1b production file 100%. Coverage floor raised from 94.96 to 95.80. Server dispatcher subsequently decomposed to remove a C grade; final whole suite rerun required.
- Expanded real PostgreSQL suite passed all 16 cases in 28.19 seconds (`maintenance-contract-expanded.log`), including owner/admin/replacement-role refusal, effective column/sequence/function/database/membership rights and transaction rollback on final/session ambiguity.
- Portable protocol schemas now enforce digest/outcome consistency; runtime adds revision path/ID and structural path uniqueness checks. Deployment templates live in `deploy/controlled/`; operator contract in `docs/operations/controlled-cutover.md`. M1a independent PASS reconciled in plan/validation/roadmap. Strict docs build passed.
- Full static run: scoped Ruff, pydoclint, mypy, ty, imports, schema-map, complexipy pass. Radon dispatcher C has been fixed and is being rechecked. Native score 60/100 remains below unchanged90; report logs preserve exact counts.
- External full contract/integration/9GiB acceptance currently running in retained process session61465; logs `contract-full.log`, `integration-full.log`, `acceptance-full.log` and `external-gates.json`. Do not start/stop a competing VM lifecycle.
- Whole Ruff/format fail on unrelated new teaching files under learning/. Parent notified and owns user coordination; do not modify them without authorization. M1b scoped Ruff issues were fixed.
- Still required: final whole coverage after dispatcher change/mixed-population case; final static/source scan with native JSON/source inventory and hashes; external suites completion; final docs/diff review; final report. No functional/release PASS claim yet, no live cutover, no M1c activation/startup claim.

## Implementation delivery checkpoint

Local M1b functional acceptance PASS; independent verification next. See `report.md` and root `P3_M1B_VALIDATION.md`. Final unit1587passed95.80%, all17newproduction100%; baseline115sourcefiles unchanged. Fullcontract46pass, finalintegration14pass, full9GiBacceptance1pass. Staticlint now intentionally scopes tosrc per explicit user correction; source checks allpass except unchangednative90 threshold (60/100,213/919fragments,253pairs,58groups). Full132files analyzed0skips/no dead/highcomplexity; radonC/Bempty. Docs/diffpass. No active implementation changes remain; no liveproductionoperations orM1cactivation/startup. Superseded temporary probes removed; durable fixture/tests remain. Parent owns execution ledger and serial independent verification.
