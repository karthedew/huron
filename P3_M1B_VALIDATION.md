# M1b corrective implementation validation — 2026-09-11

Implementation attempt 3 / fix pass 2 addressed all three findings from
[independent verification 2](p3-evidence/m1b/verification2/report.md). **Local
functional validation passed; [independent verification
3](p3-evidence/m1b/verification3/report.md) returned functional FAIL on three
authority regressions and the M1b workflow stopped at escalation.** The
authority model recorded below is superseded by
[ADR-0001](docs/adr/0001-controller-generation-is-the-verification-epoch.md),
reviewed in
[P3_M1B_ARCHITECTURAL_REVIEW.md](P3_M1B_ARCHITECTURAL_REVIEW.md) and designed in
[P3_M1B_AUTHORITY_DESIGN.md](P3_M1B_AUTHORITY_DESIGN.md); this file is the
historical record of attempt 3. M1b is not independently deployable.
Initialization, activation/startup, recovery and cleanup capabilities remain
planned.

The [complete corrective report](p3-evidence/m1b/fix2/report.md) contains all
actual gate logs, failures, coverage, source/scope hashes, native scans and cleanup.
Earlier implementation and verification receipts remain historical evidence.

| Gate | Result |
| --- | --- |
| Full unit suite | 1,628 passed; 95.88097332160656%; all 17 M1b source files 100% |
| Coverage ratchet | Raised from 95.84 to 95.88 |
| Full contracts | 48 passed, including independent-process contention and process-death recovery |
| Full integration | 14 passed, including historical writer isolation and live SQL consumer revocation/fresh verification |
| Full-size acceptance | 1 passed; unchanged 9 GiB / 144 × 64 MiB interrupted/resumed upload |
| Source checks | Pass except native duplication threshold; schema-map remains required |
| Complete native scan | 132/132 files, zero skips/errors; 60/100, 213/935 fragments, 253 pairs, 58 groups |
| Native quality | FAIL against unchanged 90 threshold; user-authorized functional-progress exception only |
| Complexity/dead code | No threshold violations or dead-code findings |
| Cleanup | All owned runners finished; private Linux fixtures absent and VM stopped |

The pending-marker mechanism is removed. Permanent kernel ownership excludes
independent maintenance processes through settled writes. Immutable files are
prepared history. Attempt 3 required a current controller endorsement, treated
lost acknowledgements as indeterminate and allowed same-run report-before-record
replay; verification 3 showed that endorsement could be revoked and re-granted
without a rescan, that the database identity was not bound to the fence and
that transport errors escaped revocation. ADR-0001 replaces endorsement with
the controller generation as the epoch: every failed observation, `abandon` and
restart advances it, a stateless `validate` admits only a record whose fence
names the live generation, a lost reply is resolved by validating again, and
every `prepare` appends a new report/record pair.

All four verifier1 probes pass. Unmodified verifier2 probes retain obsolete
pending-file assertions/barriers and are reported with their actual failures or
timeout, not as passing checks; replacement tests verify the new authority
contract directly. See the complete report for that accounting.

Only disposable local testing occurred. No production cutover, activation,
commit, push, frontend work or deferred D3b change occurred. All 115 pre-existing
source files and unrelated working-tree edits are preserved. Ordinary development
Compose, arbitrary host writers, remote engines and NFS remain unsupported.
