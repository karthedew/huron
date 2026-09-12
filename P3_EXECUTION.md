# P3 execution ledger — 2026-09-11

## Scope and runtime

The user approved stabilizing the existing duplication-plan D3a changes, pausing
that plan before D3b, and prioritizing P3 functional implementation and acceptance.
The [P3 plan](P3_IMPLEMENTATION_PLAN.md#execution-rules) records the exception:
native duplication must still be measured against 90 and reported, but its known
failure does not halt functional work. No scanner or CI threshold is relaxed.

Host: Codex. Orchestrator, implementation and verification model/reasoning settings:
inherited from the session, with no overrides. Native collaboration tools provide
serial children and live progress messages; nested delegation is prohibited.
Package path: `src/huron`, confirmed by `pyproject.toml`'s wheel package and tool
configuration. The separate duplication-plan scan covers all of `src`.

Starting HEAD: `6082088dbcf0eda6309e099f122ef01588ead088`. The working tree contains
existing D1–D3a source/test changes, planning documents, instruction/skill changes
and the ignored teaching workspace. Preserve all unrelated work. No commit, push
or live deployment is part of this checkpoint.

## Execution progress

| Task | Implementation attempt | Verification attempt | Status |
| --- | --- | --- | --- |
| D3a stabilization | 1, `/root/stabilize_d3a` | 1/3, `/root/verify_d3a` | Functional PASS; overall gate fails duplication; redesign paused |
| M1a functional acceptance | 1, `/root/m1a_acceptance` | 1/3, `/root/verify_m1a` | Functional PASS; overall quality fails duplication; not independently deployable |
| M1b exclusion and legacy verifier | 1, `/root/implement_m1b` | Not started | Implementation in progress; disposable test environments only |
| M1c cutover/startup | Not started | Not started | Pending |
| M2 governance and read admission | Not started | Not started | Pending |
| M3 recovery | Not started | Not started | Pending |
| M4 reconciliation and findings | Not started | Not started | Pending |
| M5 staging cleanup | Not started | Not started | Pending |
| M6 rebuild and activation | Not started | Not started | Pending |
| M7 final acceptance and handoff | Not started | Not started | Pending |

## Infrastructure and evidence limits

Active child: `/root/implement_m1b`, started 2026-09-11 18:49:05 UTC.
Last recorded progress at approximately 19:27 UTC: 36 focused tests and two real
PostgreSQL exclusion contracts passed. Filesystem/model/verifier coverage reached
100%; coordinator coverage still needs completion. Controller settings, engine,
persistent admission and client pass focused type/docstring checks; peer-authenticated
server, CLI wiring and the actual Linux old-artifact fixture remain outstanding.
No M1b certification has run. Implementation attempt 1; verification not yet started.
The preceding M1a implementation started 18:29:23 UTC and independent
verification started 18:40:16 UTC; both finished before this child launched.

Initial `df -h .` reports approximately **57 GiB free**, exceeding the 25 GiB
prerequisite for the single 9 GiB acceptance flow. Recheck before execution and
measure actual peak use. The previous 5.8 GiB observation is historical.

Disposable PostgreSQL tests use the discovered Podman socket. Do not use the
development stack's database as a test target. No deployment has been selected
for actual cutover or certification. Local POSIX and disposable controller tests
do not certify NFS or an unmanaged deployment; those proofs remain required when
claiming support for the respective environment.

## D3a implementation checkpoint

[Receipt and source identity](duplication-evidence/d3a/README.md): 1,429 unit
tests at 94.96%, 30 PostgreSQL contracts and 13 integration tests passed.
Non-duplication static gates passed; the native score remains 55 (210/799 cloned
fragments, 247 pairs, 57 groups, all 115 source files analyzed). Coverage's
configured floor was raised from 94.71 to 94.96 and checked with `coverage report`.
No production/test fix was needed.

[Independent verification](duplication-evidence/d3a/verification-20260911/review.md)
returned functional PASS on attempt 1, with the overall gate explicitly failing
only duplication. It reran 1,429 units at 94.96%, 30 contracts, 13 integrations,
static checks and strict docs. All 13 D3a-touched source files had 100% line
coverage; OpenAPI exactly matched D0. All child processes finished before M1a
implementation started. D3b–D7 remain paused.

Podman was stopped; keeping its startup and disposable test execution within
one retained tool process restored connectivity. Standalone startup was observed
to lose the VM after the tool process ended. No production database was used.

Subsequent full-gate receipts and source identities will be linked here after
each serial implementation/verification pass. Earlier test results are historical
evidence rather than proof of a later tree.

## Deployment baseline to reconcile in M1b/M1c

Inspection found `Containerfile` still starts `huron.service.api.main:app`, while
the implemented application lives at `huron.applications.api.main:app`. The
Compose application and migration services also share the development database
owner identity. These are concrete deployment integration work for the first
cutover release, not evidence that its old-writer exclusion contract exists.

## M1a implementation checkpoint

[Audit and command receipts](p3-evidence/m1a/attempt1/audit.md): the 9 GiB
interrupted real-socket upload/download passed in 90.41 seconds. Completion took
25.140 seconds and commit 11.348 seconds. The 0.2-second observer sampled peak
allocated file blocks of 18.01 GiB and minimum free capacity of 37.89 GiB;
these are sampled observations, not exact instantaneous bounds. The acceptance
test uses memory database stores, local APFS and real sockets; independent
PostgreSQL/POSIX coverage remains separate.

Added a 25 GiB pre-server capacity guard and five boundary/error tests, with
100% helper coverage. Full units: 1,434 passed at 94.96%; contracts: 30;
integrations: 13. All non-duplication static checks, strict docs, links and
whitespace passed. Native score remains 55 with all 115 source files scanned.
Production source hashes are unchanged from D3a. A failed Podman-connectivity
attempt is preserved alongside the successful same-process retry.

Only this attempt's unique temporary fixture was removed after measurement;
approximately 56.88 GiB remained free.

[Independent verification](p3-evidence/m1a/verification1/report.md) returned
functional PASS on attempt 1: 1,434 units at 94.96%, 30 PostgreSQL contracts,
13 integrations, all non-duplication static checks and docs passed. A separate
9 GiB acceptance passed in 82.85 seconds with sampled peak allocation 18.01 GiB
and minimum free capacity 38.84 GiB. Completion took 18.081 seconds and commit
11.324 seconds. Its unique fixture was removed, all verifier processes stopped,
and all 115 production hashes remained unchanged. Overall quality still fails
native duplication 55/100. M1b/M1c and subsequent milestones are not implemented
by this checkpoint; the next serial child is implementing M1b.

## M1b implementation in progress

Attempt 1 has exercised PostgreSQL role exclusion and a private Linux container
controller. The historical HTTP upload probe in
`p3-evidence/m1b/attempt1/legacy-http-authorized.log` admitted an upload, wrote
64 KiB, applied database exclusion, and observed another 64 KiB written by the
same held request. Controller shutdown then terminated the writer and request;
storage stopped changing and restart was refused. This demonstrates why database
exclusion alone is insufficient for an already admitted request.

The durable test in `tests/integration/test_protocol_cutover.py` subsequently
passed in 68.92 seconds, including cleanup; its receipt is
`p3-evidence/m1b/attempt1/legacy-http-integration.log`. It is not a full
M1b completion receipt: remaining implementation, coverage, deployment documentation,
full gates and independent verification are pending. Disposable local Linux proof
does not certify NFS or a production deployment. Earlier M1a quality measurements
do not describe this changing source tree.

The expanded durable Linux integration subsequently passed in 216.14 seconds
(`p3-evidence/m1b/attempt1/controlled-cutover-integration.log`). It covers the
historical HTTP writer, old startup under revoked credentials, unauthorized Unix
peers, authenticated cutover with structural database/filesystem checks, foreign
volume holders, changed controller generation, unreachable controller and cleanup.
Focused core/raw tests reached 58 passing tests and 100% targeted coverage across
seven modules. These remain implementation results; adapter coverage, edge cases,
deployment documentation, full gates and independent review are outstanding.

Subsequent focused adapter suites passed: engine 17 tests, private settings 13,
managed controller 12, each with 100% module coverage. Covered refusals include
surviving writers, unsafe volume/socket configuration, stale generations, replaced
volume identity and foreign/privileged containers. Controller tests also verify
durable exclusion before termination and distinct maintenance/restart grants.
Unix transport and CLI lifecycle coverage remain in progress.

Further focused suites passed with 100% module coverage: Unix client/server
(13 tests), CLI commands (9), wiring (2), and metastore maintenance boundaries
(18). Actual Linux integration supplies the kernel peer-identity proof; local
Unix-socket unit tests inject unavailable macOS peer metadata.

Expanded real PostgreSQL contracts passed 16 tests in 28.19 seconds
(`p3-evidence/m1b/attempt1/maintenance-contract-expanded.log`), including rollback
on unsafe role configuration or conflicting session/final evidence and audited
failure of unmatched sessions. Controlled Linux deployment templates and operator
documentation have been added. Documentation reconciliation and full-source
gates remain pending before independent verification.

### User-directed lint scope

The user explicitly directed that linting apply only to `./src`; `learning/`
must not be linted. This supersedes the earlier whole-repository lint targets
in the command workflow. The active implementer is reconciling canonical lint
commands and documentation while preserving source thresholds and test execution.
The earlier teaching-script failure is historical evidence, not an outstanding
requirement to modify teaching content.

## M1b implementation handoff and independent review

[Implementation attempt 1](p3-evidence/m1b/attempt1/report.md) returned ready for
verification with all processes stopped: 1,587 unit tests at 95.80% (new floor),
46 contracts, 14 integrations and full 9 GiB acceptance passed. All 17 added
production files have 100% coverage; 115 pre-existing production files are
unchanged. Source-only lint completes with its sole failure at native duplication
60/100: 213/919 fragments, 253 pairs, 58 groups; all 132 source files analyzed.
Strict docs and diff checks passed. These are implementation receipts only.

The serial independent verifier `/root/verify_m1b` has started attempt 1 of 3,
with inherited model/reasoning, source path `src/huron`, the user-directed `src/`
lint scope and the unchanged native-90 reporting exception. Its verdict is pending;
M1c through M7 remain outstanding. The verifier owns only
`p3-evidence/m1b/verification1/`; implementation files are not to be edited during
review. Evidence and source inventory are linked from the implementation report.

[Independent verification attempt 1](p3-evidence/m1b/verification1/report.md)
returned **functional FAIL**, despite passing 1,587 units at 95.80%, 46 contracts,
14 integrations and full 9 GiB acceptance. Four additional reproductions expose
descendant bind-mount inventory omission, undetected live Compose changes, and
fence-loss gaps around final persistence. Behavioral test corrections and stale
protocol status prose are also required. Native duplication independently remains
60/100 with complete 132-file coverage, separate from the functional failure.
All verifier processes stopped and owned fixtures were cleaned.

The sole active child is now `/root/fix_m1b_1`, implementation attempt 2 (fix pass
1), addressing all five review items. It will rerun the full gate with inherited
settings before independent verification attempt 2 of 3. Source-only lint remains
the user-directed scope. M1b is not complete; M1c through M7 remain outstanding.

Fix-pass feedback: all four independent reproductions now pass, with 78 focused
tests covering live configuration and overlapping mounts, persistence fence loss,
stranded-record refusal, fresh-run progress and cancellation of a held filesystem
write. The implementation uses durable pending evidence to distinguish incomplete
installation from usable certification. CLI behavioral tests and quoted-schema/
real Linux descendant-mount cases were added; status prose was reconciled.
Initial source checks pass, and full fix-pass validation is running. These are
not independent verification results and do not close attempt-1 findings yet.

[Fix pass 1](p3-evidence/m1b/fix1/report.md) completed with all five findings
addressed according to the implementer: 1,606 units at 95.840734% (floor 95.84),
46 contracts, 14 integrations, full 9 GiB acceptance and 86 focused/reproduction
tests passed. All 17 M1b source files have 100% coverage. Final source checks,
docs and diff checks pass except native duplication 60/100, 213/925 fragments,
253 pairs and 58 groups, with exact 132-file inventory. All owned processes and
fixtures were cleaned; pre-existing resources were preserved.

The independent verifier `/root/verify_m1b` is now running verification attempt
2 of 3, with evidence confined to `p3-evidence/m1b/verification2/`. It will verify
the pending-evidence validity contract and every original finding, then rerun
all gates. M1b remains unverified pending that verdict.

[Verification attempt 2](p3-evidence/m1b/verification2/report.md) returned
**functional FAIL**. All prior reproductions pass, but three new reproductions
show that pending-marker removal/fsync failure can leave usable-looking evidence,
fence loss during clearance can return success, and concurrent same-run calls
can clear each other's ownership. Full independent gates otherwise pass:
1,606 units at 95.840734%, 46 contracts, 14 integrations and full acceptance;
native duplication remains 60/100. All verifier processes and owned fixtures ended.

The sole active child `/root/fix_m1b_1` resumed for fix pass 2 (implementation
attempt 3), redesigning durable completion and cross-process ownership to address
all three findings. The next independent verification is attempt 3 of 3; a
functional failure there requires the command's architecture escalation rather
than another fix pass or progress to M1c.

[Fix pass 2](p3-evidence/m1b/fix2/report.md) completed: removable pending-marker
authority was replaced with kernel ownership, immutable prepared evidence and
live controller endorsement/consumer validation. Claimed final gates pass:
1,628 units at 95.880973% (floor 95.88), 48 contracts, 14 integrations and full
9 GiB acceptance; all 17 M1b source files have 100% coverage. Native duplication
remains 60/100, 213/935 fragments, 253 pairs, 58 groups, exact 132-file inventory.
All owned processes/fixtures ended. Historical marker-specific probes retain
documented obsolete-hook failures; replacement behavioral proofs require review.

The sole active child `/root/verify_m1b` is running final verification attempt
3 of 3, with evidence in `p3-evidence/m1b/verification3/`. It will independently
test the redesigned contract against the prior semantic failures and all M1b
acceptance criteria. M1b remains incomplete pending its verdict.

## Stopped at mandatory escalation

[Verification 3](p3-evidence/m1b/verification3/report.md) returned functional FAIL:
engine HTTP errors can leave endorsement reusable, maintenance database changes
are not bound to prior evidence, and direct re-endorsement can bypass required
reverification. The last finding is an unresolved authority handoff decision;
the first two are implementation defects within the plan. Existing suites pass
(1,628 units at 95.880973%, 48 contracts, 14 integrations, full 9 GiB acceptance),
but three independent authority regressions fail.

All three verification attempts are exhausted. No active child, fourth fix pass
or next-milestone implementation remains. All owned processes/fixtures ended and
the VM stopped. [The escalation](P3_IMPLEMENTATION_PLAN.md#escalation) records all
reviews, the retained uncommitted tree, design decisions and exact architecture
review/replanning invocations. M1b and P3 remain incomplete.
