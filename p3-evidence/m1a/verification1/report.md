# M1a independent verification — attempt 1 of 3

**Functional acceptance: PASS. Overall repository quality gate: FAIL.**

Verified on 2026-09-11 in Codex, with inherited model/reasoning settings, no nested
agents, no source or test fixes, and no deployment. This verdict applies only to
M1a under the execution-priority exception in `P3_IMPLEMENTATION_PLAN.md`.
No actionable M1a functional issue remains. The native duplication score of 55
is below the unchanged requirement of 90; this is not a clean lint/CI/release pass.
M1b/M1c remain prerequisites to deploying the new protocol.

## Scope and independent review

Read AGENTS.md, the invoked implement-markdown workflow, the entire P3 plan and
design, current M1a validation record, Makefile, CI/acceptance workflows and project
configuration. Applied the actual project-local OOP, FastAPI, PostgreSQL,
codebase-design and writing-for-agents skills at their respective boundaries.
The current codebase-design skill contains an implemented vocabulary; the design's
historical scaffold observation is not treated as current methodology evidence.

Inspected actual storage, core ingestion/authorization, canonical document,
PostgreSQL adapter/migration/schema and API wiring code, and meaningful tests.
All 115 production Python hashes match the independently verified D3a tree and
remain identical before/after this verification. This continuation changes test
capacity/timing and documentation, not production code or migrations. Preserved
all unrelated D1–D3a, instruction, skill and parent-ledger edits.

| M1a requirement | Implementation reviewed | Independent test evidence |
| --- | --- | --- |
| 1. Separate paths; only begin creates root | `StagingPaths`, `create_staging`, descriptor-relative upload/completion/document traversal | Missing and relocated session/ancestor, nested symlink and delayed writer cases in `test_rawstore_materialize`; API/core upload tests |
| 2. Verified closed independent payload | `candidate`, `observe`, exclusive `install`, `PosixRawStore.finish_file` | Empty and multiblock copies; distinct inode/link count/seal; real held upload descriptors; open-writer observation; short/zero write, ENOSPC, fsync/fchmod failure and cancellation cases |
| 3. Idempotent completion; truthful COMPLETE | Core `_materialize_file`, conditional PostgreSQL file updates, operation-owned candidate cleanup | Matching/corrupt PostgreSQL losers cannot regress COMPLETE; abrupt death before/after COMPLETE transaction, retry retains installed inode; two real filesystem completers install one winner |
| 4. Frozen commit documents and validated replay | Core `commit`/`_publish_envelope`, `CommitIntent`, `freeze_commit`, immutable SQL trigger, `verify_envelope` | Row-lock contention and distinct clocks; same/different keys; changed metadata conflict; each document durability syscall boundary; process death at intent/document/final; exactly one revision/audit/outbox |
| 5. v2 and explicit legacy decoder; envelope-only rename | `CommitRecord`, committed-v2 schema, no-replace `commit_envelope`, device checks | v1/v2 decode tests, exact final inventory, bad final evidence refusal, cross-device errors, held descriptor cannot change final payload |
| 6. Migration refusal and RECOVERING claims | 0011 refusal, state transition vocabulary, immutable recovery ownership, preserved partial indexes | Real migration refuses all four nonterminal legacy states without advancing head; terminal migration succeeds; RECOVERING participates in both predicates and fences stale commit/renewal |
| 7. Schema map and conformance | `migrations/schema.sql`, protocol/wiring declarations | Schema-map check, real CHECK/trigger/claim assertions, strict typing and all nine import contracts |

The reviewed tests exercise byte content, inode identity, persisted state, refusal,
and retry results. Controlled Events/Barriers and database lock observations order
races; bounded waits detect hangs. Fault injection wraps actual filesystem or
PostgreSQL boundaries. The full-size test retains its 9 GiB size and 144 × 64 MiB
parts, stops the first client after 50 parts, resumes 94 parts, completes, verifies,
commits, and checks streamed download length/Content-Length/SHA-256.

Fresh core authorization remains on the public Raw service: session ownership,
resource discovery, current Raw write permission, claim principal, exact file
membership, and server-resolved ancestry are checked independently of HTTP guards.
No new suppression, skip, xfail, coverage exclusion, scanner tuning, compatibility
path or plan-narrating production comment was introduced in this continuation.
No production file is newly touched by this attempt, so no uncovered production
line is being waived. The new eight-statement capacity helper has 100% coverage.

## Independent command results

Full untruncated stdout/stderr is retained in the linked logs; JSON files record
exact commands, return codes, analyzer reports and source identity.

| Command | Exit | Result / transcript |
| --- | ---: | --- |
| `make lint` | 2 | [lint.log](lint.log): final native duplication check fails; all preceding constituents exit 0 |
| Ruff check / format | 0 / 0 | No diagnostics; 223 files formatted |
| pydoclint / mypy / ty | 0 / 0 / 0 | No findings; mypy checks 115 source files |
| import-linter / schema-map | 0 / 0 | Nine contracts kept; no schema-map findings |
| radon cc / mi | 0 / 0 | Both commands emitted no flagged entries |
| complexipy / pyscn check | 0 / 0 | No disallowed complexity or dead-code findings; clones informational in pyscn check |
| Native duplication for `src/huron` | 1 | Score 55; 210/799 fragments; 247 pairs; 57 groups |
| `uv run pytest --cov=src/huron --cov-report=term-missing --cov-report=json:...` | 0 | [unit.log](unit.log): 1,434 passed; 5,296/5,577 statements = 94.9614488076%; unchanged floor 94.96 |
| `uv run pytest -m contract` | 0 | [contract.log](contract.log): 30 passed, real disposable PostgreSQL 16 and local POSIX |
| `uv run pytest -m integration` | 0 | [integration.log](integration.log): 13 passed, real disposable PostgreSQL 16 and local POSIX |
| `make test-acceptance` | 0 | [acceptance.log](acceptance.log): 1 passed in 82.85 seconds; no skipped tests |
| Helper tests with `--cov=tests.acceptance_support` | 0 | [capacity-tests-retry.log](capacity-tests-retry.log): five passed, 8/8 statements, 100% |
| `make docs` | 0 | [docs.log](docs.log): strict build passed |
| Fresh duplicate scan of full `src` | 1 | [duplication-src.log](duplication-src.log): same score/fragments/pairs/groups |
| `git diff --check`, repeated after cleanup | 0 | [diff-check-final.log](diff-check-final.log) |

Every required tool resolved in the project environment; see [tool-results.json](tool-results.json)
and [tool-versions.log](tool-versions.log). Both native JSON invocations use pinned
pyscn 1.31.1, clone detection enabled, 115/115 files analyzed, zero skipped files;
see [native-invocations.json](native-invocations.json), [lint-native.json](lint-native.json)
and [duplication-src-native.json](duplication-src-native.json). Neither health score
nor a replacement formula is used as the duplication gate. Make's sequential
constituent exits are recorded in [lint-constituents.json](lint-constituents.json).

The first helper-test command passed its tests, but its enclosing zsh then failed
when attempting to assign the reserved `status` variable. That verifier harness
error is preserved in [capacity-harness-note.txt](capacity-harness-note.txt); a
subprocess-based retry captured exit 0 with no test or source change. Existing
third-party deprecation warnings remain. No selected suite skipped tests.

## Capacity, timing, and cleanup

The new guard checks `tmp_path` before API construction or server startup and
refuses below 25 GiB. It propagates an unavailable filesystem rather than admitting
the upload. Direct tests prove zero, one byte below, exact minimum, one byte above,
and failed observation. The Makefile, AGENTS.md and testing guide consistently
state 25 GiB. The calculation is one 9 GiB upload plus one independent 9 GiB
candidate, with 7 GiB headroom including the default 1 GiB completion reserve;
the source is sparse and download is streamed. This is admission, not reservation
against unrelated writers or parallel runs.

The independent observer ran with a unique verifier-owned temporary directory,
separate from all implementation fixtures, and sampled at approximately 0.2 s.

| Observation | Value |
| --- | ---: |
| Initial free capacity | 61,053,358,080 bytes (56.86 GiB) |
| Sampled peak allocated fixture-file blocks | 19,341,541,376 bytes (18.01 GiB) |
| Minimum sampled free filesystem capacity | 41,707,143,168 bytes (38.84 GiB) |
| Samples | 409 |
| Completion HTTP request | 18.080806 seconds |
| Commit HTTP request | 11.323856 seconds |

See [acceptance-storage.json](acceptance-storage.json), [storage-samples.csv](storage-samples.csv),
[storage-observer.py.txt](storage-observer.py.txt), and [acceptance.xml](acceptance.xml).
The measured block sum uses `st_blocks * 512` once per `(st_dev, st_ino)`.
Traversal is non-atomic: the sampled maximum is not an exact instantaneous peak.
Directory metadata, filesystem internals and open-unlinked files are excluded;
free capacity also reflects other consumers. No physical block-I/O or write
amplification was measured. Timings include each HTTP request's work and are one
local observation, not performance guarantees or thresholds.

Acceptance uses memory database stores, local Darwin/APFS files and real loopback
uvicorn/httpx sockets with development headers. It does not establish a
PostgreSQL-backed 9 GiB run. Real PostgreSQL evidence comes separately from the
contract/integration suites. Started the existing stopped Podman VM and kept the
launcher process alive through both suites; dynamically resolved its socket.
No production database was selected or migrated. All disposable test containers
were removed; pre-existing stopped containers were preserved.

Removed only `/var/folders/3t/dsbbphj948x65zmvkftl97580000gn/T/huron-m1a-verification1-3nm09ku0`.
[fixture-cleanup.json](fixture-cleanup.json) confirms it no longer exists and free
capacity returned to 61,046,099,968 bytes. The acceptance server shutdown assertion
passed; [process-check.txt](process-check.txt) found no surviving pytest, observer
or uvicorn processes. All verifier command sessions finished.

## Outstanding quality issue and delivery limits

1. **Medium — repository quality gate (`src/huron`, native reports above):**
   duplication score 55 is below 90. Keep reporting overall FAIL; resolve through
   the separately paused duplication design workstream without weakening the
   threshold, changing detection/exclusions, or coalescing distinct domain types
   only to game the score. The explicit P3 priority permits functional progress;
   no M1a functional fix is requested for this known quality failure.

No NFS cross-client proof, old-writer shutdown/restart exclusion, legacy inventory
certification, cutover/startup gate, production identity-provider acceptance, live
deployment or M1b–M7 functionality is certified. No commit, push or deployment was
performed. P3 stays incomplete. This verifier stops at M1a.
