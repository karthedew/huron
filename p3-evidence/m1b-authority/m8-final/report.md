# M1b authority implementation — final gate report

Scope: `P3_M1B_AUTHORITY_IMPLEMENTATION_PLAN.md` M8.1–M8.2, run against HEAD
`e22d0003cfd97f0f75df01c04b3c493bef5eeaf8` on this host. This report records what the
implementation's own gate observed. **It does not claim verification.** See
"Independent verification has not started" at the end.

## 1. Per-milestone attempt counts and verdicts

Every milestone (M0–M7) passed both implementation and independent verification on the
first attempt: implementation 1/1, verification 1/1, no fix passes, no escalation.
M0–M6's independent verification receipts existed in
`p3-evidence/m1b-authority/<milestone>/verification1/` before this M8 gate ran. M7's did
not: at the time this M8 gate ran, `p3-evidence/m1b-authority/m7-docs/verification1/` did
not yet exist. It has since been created by the M7 verifier's own rerun of its checks
(`docs`, `grep-status`, `grep-banned-sense`, `diff-check`, `git-status.log`, `head.txt`,
`source-inventory.sha256`, `source-inventory-diff.log`, `passages.log`), producing
`p3-evidence/m1b-authority/m7-docs/verification1/report.md`, dated 2026-09-12, which
restates the same verdict this report already recorded for M7: **PASS** ("Every
`P3_M1B_AUTHORITY_DESIGN.md` "Design: T6" §1.1–§1.9 passage was applied literally, nothing
outside the edit list changed, both §2 invariant greps match the expected residual list,
`make docs` builds strict-clean, and no `src`/`tests` file moved."). That ordering —
M7's receipts recorded after this M8 gate, not before it — is stated here explicitly so
the sentence below is accurate rather than assumed. Confirmed by `ls
p3-evidence/m1b-authority/m7-docs/verification1/`: `diff-check.exit`, `diff-check.log`,
`docs.exit`, `docs.log`, `git-status.log`, `grep-banned-sense.exit`,
`grep-banned-sense.log`, `grep-status.exit`, `grep-status.log`, `head.txt`,
`passages.log`, `report.md`, `source-inventory-diff.log`, `source-inventory.sha256`. With
that directory now present, the statement "confirmed by re-reading
`p3-evidence/m1b-authority/<milestone>/verification1/` for each milestone" holds for
M0–M8: every recorded `unit.exit`/`pytest-unit.exit` is `0`, every `lint.exit` is `2`
with the duplication step as the sole failing step (the individual `pydoclint`/`mypy`/
`ty`/`ruff`/etc. sub-logs several verifiers recorded separately all exit `0`),
`diff-check.exit` is `0`, and no verification directory contains a fix-pass or a second
attempt directory.

| Milestone | Directory | Implementation | Verification | Verdict |
| --- | --- | --- | --- | --- |
| M0 — Baseline receipts | `m0-baseline` | 1 | 1 | pass |
| M1 — Database identity binding | `m1-identity` | 1 | 1 | pass |
| M2 — Append-only sequencing | `m2-sequencing` | 1 | 1 | pass |
| M3 — Operator `--validate` path | `m3-validate-path` | 1 | 1 | pass |
| M4 — Epoch cutover (atomic) | `m4-epoch-cutover` | 1 | 1 | pass |
| M5 — Epoch behaviour proofs | `m5-behaviour-proofs` | 1 | 1 | pass |
| M6 — Contract/integration on containers | `m6-containers` | 1 | 1 | pass |
| M7 — Documentation reconciliation | `m7-docs` | 1 | 1 | pass |
| M8 — Final full gate, ratchet, report | `m8-final` | 1 (this report) | not yet started | — |

## 2. M8.1 gate outputs (summary lines)

Run in order from the repository root against the final tree; full logs are in
`p3-evidence/m1b-authority/m8-final/`.

| Command | Log | Exit | Summary |
| --- | --- | --- | --- |
| `git rev-parse HEAD` | `head.txt` | — | `e22d0003cfd97f0f75df01c04b3c493bef5eeaf8` |
| `uv run pytest -q tests/unit --cov=src/huron --cov-report=term-missing --cov-report=json:coverage.json` | `unit.log`/`.exit` | 0 | `1677 passed, 1 warning in 123.79s`; TOTAL 95.92% (floor 95.92 already met — no ratchet needed, see §3) |
| `make lint` | `lint.log`/`.exit` | 2 | Every step before duplication clean; fails only at `check_duplication.py` (native score 60/100, see §4) |
| `uv run --locked python scripts/check_duplication.py src` | `duplication.log`/`.exit` | 1 | `60/100`, cloned fragments `213/937`, pairs `253`, groups `58` |
| `docker ps` (before) | `podman-before.log`/`.exit` | 0 | Empty — no containers running |
| `uv run pytest -q -m contract` | `contract.log`/`.exit` | 0 | `49 passed, 1692 deselected in 132.66s` |
| `uv run pytest -q -m integration -s` | `integration.log`/`.exit` | 1 | `1 failed, 13 passed, 1727 deselected in 13.48s` — the single expected environment-gap failure (§6) |
| `uv run pytest -q -m integration -s --deselect …test_actual_legacy_http_request_is_terminated_and_cannot_restart` | `integration-runnable.log`/`.exit` | 0 | `13 passed, 1728 deselected in 13.57s` |
| `docker ps` (after) | `podman-after.log`/`.exit` | 0 | Empty — no containers left running |
| `df -h .` | `df.log` | — | `36G` available (before acceptance) |
| `make test-acceptance` | `acceptance.log`/`.exit` | 0 | `1 passed, 1740 deselected in 50.35s` (the 9 GiB interrupted/resumed multipart upload round-trips byte-identically) |
| `df -h .` (after) | `df-after.log` | — | `36G` available, captured after the fixture cleanup described in §5 (not immediately after the acceptance run) |
| `make docs` | `docs.log`/`.exit` | 0 | `zensical build --strict`: "No issues found" |
| `git diff --check` | `diff-check.log`/`.exit` | 0 | No whitespace errors |
| `--co` unit/contract/integration | `collect.log` | — | `1677 tests collected`; `49/1741 tests collected (1692 deselected)`; `14/1741 tests collected (1727 deselected)` |
| `git status --porcelain` | `git-status.log` | — | See §8 |
| source inventory | `source-inventory.sha256` | — | 243 tracked `.py` files hashed under `src/huron` and `tests` |

Every command exits 0 except `make lint` and `check_duplication.py` (the duplication
exception, expected) and the full `-m integration -s` run (the single environment-gap
node, expected). All acceptance criteria in M8.1 are met: unit 1677, contract 49,
integration 14 collected; all 17 M1b production/test files plus every new production
file are traced at 100% line coverage in `coverage.json` (§3).

## 3. Coverage: baseline, completion, ratchet history

| Point | TOTAL (measured) | `fail_under` at that run | Unit count |
| --- | --- | --- | --- |
| M0 baseline | 95.88097% | 95.88 | 1634 passed |
| M1 | 95.89901% | 95.89 (ratcheted from 95.88 within M1) | 1643 passed |
| M2 | 95.89961% | 95.89 (unchanged) | 1643 passed |
| M3 | 95.91807% | 95.91 (ratcheted from 95.89) | 1661 passed |
| M4 | 95.92458% | 95.92 (ratcheted from 95.91) | 1659 passed |
| M5 | 95.92458% | 95.92 (unchanged) | 1677 passed |
| M6 | 95.92458% | 95.92 (unchanged) | 1677 passed |
| M7 | 95.92458% | 95.92 (unchanged) | 1677 passed |
| **M8 (this gate)** | **95.92458%** | **95.92 (unchanged — already the floored value)** | **1677 passed** |

Ratchet outcome at M8.1: `pyproject.toml`'s `[tool.coverage.report] fail_under` was
already `95.92` going into this gate (set at M4). The M8 measured total,
95.92458303118201%, floors to two decimals to `95.92`, equal to the current floor. Per the
plan's rule ("if not, leave it"), **no change was made to `pyproject.toml`**, and the unit
command was not rerun a second time — the single recorded run already reflects the correct
floor. All 11 production files under `src/huron/core/integrity/`,
`src/huron/pkg/metastore/`, and `src/huron/applications/lakectl/` touched by this plan are
at 100.0% line coverage in `m8-final/coverage.json` (`models.py`, `ports.py`,
`generations.py`, `cutover.py`, `maintenance.py`, `settings.py`, `controller.py`,
`server.py`, `exclusion.py`, `wiring.py`, `main.py`); the remaining M1b files (the two
schema JSON documents and the test modules) are not coverage-measured targets.

## 4. Native duplication score: baseline and completion

| Point | Score | Cloned fragments | Pairs | Groups |
| --- | --- | --- | --- | --- |
| M0 baseline | 60/100 | 213/935 | 253 | 58 |
| M8 completion | 60/100 | 213/937 | 253 | 58 |

The fragment denominator moved from 935 to 937 (two additional total fragments from the
plan's net code growth); the numerator (213 cloned), pair count (253) and group count (58)
are unchanged. The score has not worsened by more than the plan's own added lines, per
rule 2; the 90/100 threshold remains unmet and is reported, not gated (`make lint` exits 2
at the duplication step only, on every milestone from M0 through M8).

## 5. Acceptance run

`make test-acceptance` (`uv run pytest -m acceptance`) ran the 9 GiB interrupted/resumed
multipart upload end to end: `1 passed, 1740 deselected in 50.35s`. Free space before the
run was 36G (`df.log`, comfortably above the 25 GiB prerequisite `require_upload_capacity`
enforces); after the run, `df -h .` (`df-after.log`) also reads 36G.

Temporary-fixture check (recorded in `acceptance-fixture-check.log`): immediately after
the passing run, the test's own `tmp_path` root (`/tmp/pytest-of-karl/pytest-109/…`) still
held 9.1G on disk — not the sparse 4K upload-source file, but the server's materialized,
real-byte COMMITTED revision payload written under the fixture's `ApiSettings.data_root`.
This is expected pytest behaviour, not a defect introduced by this plan: pytest's
`tmp_path` fixture does not delete its directory at session end by design (default
retention keeps recent numbered roots for post-mortem inspection); stale roots are swept
lazily at the start of a later session. Deleting it also required `chmod -R u+w` first,
because the committed revision tree was mode `555`/`444` — the Raw store's deliberate
immutability guarantee for a committed revision, not a permission bug. After confirming
the test had passed, this run's own tmp root (`pytest-109`) was `chmod`ed writable and
removed; no other `pytest-of-karl` directory (artifacts of earlier, unrelated sessions)
was touched. `df -h .` before and after this cleanup: 27G → 36G.

## 6. Recorded environment gap

`uv run pytest -q -m integration -s` produces `1 failed, 13 passed` here, not `14 passed`,
because `tests/integration/test_protocol_cutover.py::test_actual_legacy_http_request_is_terminated_and_cannot_restart`
cannot run on this host. Evidence
(`p3-evidence/m1b-authority/m6-containers/environment.md`, reconfirmed for this gate):

- `sudo -n true` → `sudo: a password is required`, exit 1 — non-interactive `sudo` is
  unavailable to this uid-1000 user.
- `which podman` → no output, exit 1 — Podman is not installed on this host.
- `docker --version` → `Docker version 27.2.1, build 9e34c9b`, exit 0 — Docker is present
  and used for the contract suite's disposable PostgreSQL containers and the three
  Docker-based integration modules, which all pass.

The test invokes `tests/controlled_deployment.py` through `_local_linux_invocation`, which
requires root (or passwordless `sudo -n`) because the script itself provisions a private
Podman engine. The failure observed in `integration.log`:

```
sudo: a password is required
...
E    AssertionError: assert 1 == 0
E     +  where 1 = CompletedProcess(args=['sudo', '-n', 'python3',
'/home/karl/repo/huron/tests/controlled_deployment.py', 'provision', ...],
returncode=1).returncode
tests/integration/test_protocol_cutover.py:86: AssertionError
```

**`tests/controlled_deployment.py`'s M4.8 assertions — `validate` called twice with no
generation change, an observed real SQL connection loss advancing the generation before a
pure refusal, a fresh `prepare` allocating `sequence == 2`, and the restart generation
delta — remain UNEXECUTED on this host.** Running them requires either a Linux
root/`sudo -n` environment with Podman installed, or the macOS Podman-VM path the same
script also supports. No test file, fixture, or the script itself was edited, skipped, or
xfailed to work around this gap; the deselect used to isolate the runnable subset
(`integration-runnable.log`) is a command-line flag on this one gate invocation, not a
marker or exclusion committed to any file.

## 7. The three repro behaviours and the tests that refuse them

All three verification-cycle-3 repro behaviours from the prior authority work are refused
on the final tree, each ending the epoch (advancing the on-disk generation) before the
refusal:

| Repro | Node id | Behaviour |
| --- | --- | --- |
| 1 — observed unreachable engine permanently revokes | `tests/unit/test_controller_epoch.py::test_failed_observation_ends_the_epoch_before_the_refusal[engine_connect]` | `httpx.ConnectError` propagates during observation, then a later `validate` raises `ValueError("controller exclusion generation changed")` |
| 2 — changed maintenance database configuration | `tests/unit/test_controller_epoch.py::test_failed_observation_ends_the_epoch_before_the_refusal[database_identity]` | Observation raises `ValueError("maintenance database identity differs from the fence")`, then `"generation changed"` |
| 3 — revoked receipt cannot be re-endorsed | `tests/unit/test_controller_epoch.py::test_failed_observation_ends_the_epoch_before_the_refusal[foreign_writer]` | Observation raises on `"foreign writer"`, then `"generation changed"`, with no operation able to re-admit the record — `certify` no longer exists in the port, controller or client |

No operation can re-admit a record under an ended epoch: `certify` is deleted from
`src/huron/core/integrity/ports.py` and every caller
(`grep -rn "certify\|validate_certificate\|CertificationIndeterminateError" src tests --include='*.py'`
is empty outside historical prose in design/plan documents). The server's refusal of the
deleted operations is proven directly by
`tests/unit/test_controller_transport.py::test_server_refuses_malformed_oversized_and_actor_supplied_requests`,
which is parametrized to include `{"operation":"certify","transition":{}}` and
`{"operation":"validate","transition":{}}` payloads and asserts the server refuses both.

## 8. The T4 decision

T4 §6.1's decision rule was resolved at M1.6/re-confirmed at M6.1: `pg_control_system()`
is executable by the non-superuser `probe` role against a disposable
`PostgresContainer("postgres:16")`. Decision-rule branch (a) applies — the primary query
ships as designed in `src/huron/pkg/metastore/maintenance.py`; the T4 §6.1 contingency
(fallback query, alternate identity pattern, `IDENTITY` literal, routing token) was never
triggered and remains closed. Confirmed again in this gate's contract run: `contract.log`
shows `49 passed`, including
`tests/contract/test_writer_exclusion.py::test_identify_binds_cluster_and_database_and_refuses_a_foreign_fence`.

## 9. The pydoclint deviation

The methods at `src/huron/pkg/metastore/maintenance.py` lines ~54/73/101 are the concrete
adapter `PostgresRoleExclusion`, not Protocol stubs; their `Raises:` sections name
`ValueError` and their bodies do raise it, so DOC502 does not fire there — pydoclint is
silent on that file, as on the rest of the tree.

The real, accepted deviation sits at the ports, not the adapter. The Protocol stubs in
`src/huron/core/integrity/ports.py` have `...` bodies:
`DatabaseExclusion.identify` (`:172`), `.exclude` (`:182`), `.check` (`:193`), and
`WriterExclusion.establish` (`:109`), `.check` (`:127`), `.abandon` (`:139`), `.validate`
(`:154`) — confirmed by
`grep -n "def identify\|def exclude\|def check\|def establish\|def abandon\|def validate" src/huron/core/integrity/ports.py`.
This repo's `[tool.pydoclint] skip-checking-raises = false` (`pyproject.toml:125`) means
pydoclint refuses a literal `Raises:` section on a method whose body contains no `raise`
statement (DOC502). Because every one of those seven methods is `...`-bodied, the
design's literal `Raises:` sections were written as prose instead ("Refuses with
`PermissionError` if…", "Propagates `OSError` if…", and the `DatabaseExclusion` methods'
equivalent `ValueError` prose) — with no `pydoclint` configuration loosened to
accommodate it. This deviation was resolved in T1's design and confirmed by execution in
M1's verification; it was carried through unchanged when M4 finalized `WriterExclusion`.

A related but distinct deviation is recorded in the design at T4 §5 (Rejected
alternatives), second bullet: a single private `_identify(connection) -> str` helper
shared between `identify()` and `_require_identity` in the concrete adapter was rejected
because pydoclint's DOC502 refuses a `Raises` section on a method whose body contains no
`raise` — the adapter avoids this by inlining the two `raise` statements directly into
`identify()` and `_require_identity` rather than routing through a shared raising helper.

`uv run pydoclint src` is silent on the current tree (exit 0, confirmed by direct
execution for this fix pass; also verified in every milestone's `lint.log` and in this
gate's `lint.log`, which fails only at the duplication step).

## 10. Files changed by this plan

`git status --porcelain`, filtered to this plan's intended files (the full, unfiltered
output is in `git-status.log`; the difference is exactly rule 7's untouched pre-existing
user files — `.opencode/package-lock.json`, `.opencode/package.json`, `design/index.html`,
`.pyscn/`, `scripts/main.py`, `tests/unit/test_books_upload_script.py`, `docs/adr/`,
`P3_M1B_ARCHITECTURAL_REVIEW.md`, `P3_M1B_AUTHORITY_DESIGN.md`,
`P3_M1B_AUTHORITY_IMPLEMENTATION_PLAN.md`, `design/roadmap.html`, `minihuron/` — none of
which this plan created, edited, or staged):

```
 M CONTEXT.md
 M P3_DESIGN.md
 M P3_EXECUTION.md
 M P3_IMPLEMENTATION_PLAN.md
 M P3_M1B_VALIDATION.md
A  design/core-map.html
 M design/layer-raw.html
 M docs/operations/controlled-cutover.md
 M pyproject.toml
 M src/huron/applications/lakectl/controller.py
 M src/huron/applications/lakectl/exclusion.py
 M src/huron/applications/lakectl/main.py
 M src/huron/applications/lakectl/server.py
 M src/huron/applications/lakectl/settings.py
 M src/huron/applications/lakectl/wiring.py
 M src/huron/core/integrity/cutover.py
 M src/huron/core/integrity/generations.py
 M src/huron/core/integrity/models.py
 M src/huron/core/integrity/ports.py
 M src/huron/pkg/metastore/maintenance.py
 M src/huron/schema/documents/protocol-inventory-v1.json
 M src/huron/schema/documents/protocol-transition-v1.json
 M tests/contract/test_writer_exclusion.py
 M tests/controlled_deployment.py
RM tests/unit/test_controller_certificates.py -> tests/unit/test_controller_epoch.py
 M tests/unit/test_controller_transport.py
 M tests/unit/test_integrity_cutover.py
 M tests/unit/test_lakectl_main.py
 M tests/unit/test_lakectl_wiring.py
 M tests/unit/test_maintenance_adapters.py
 M tests/unit/test_managed_controller.py
 M tests/unit/test_protocol_documents.py
?? p3-evidence/m1b-authority/
```

`design/core-map.html` is staged as added (`A`), per M7's `git add`; the rename of
`tests/unit/test_controller_certificates.py` to `tests/unit/test_controller_epoch.py` is
recorded as `R` (M4.6). Nothing is committed or pushed; `pyproject.toml` carries only the
ratchet history (§3), no other content change from this plan's own edits beyond what
M1–M7 already applied.

## Independent verification has not started

This report, and every document this plan wrote or touched, records the implementation's
own gate — the same gate every milestone's implementer and single-cycle verifier already
ran. **No document written by this plan claims "verified."** M1b's independent
verification (a fresh `/implement-markdown`-style verification pass over the whole
milestone sequence, or an equivalent independent review) has not begun. M1b, M1c and P3
remain incomplete per every historical status sentence this plan preserved.
