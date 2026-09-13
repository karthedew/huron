---
status: accepted
---

# Controller generation is the verification epoch

M1b's independent verification failed three times because certification authority was
split: the cutover service scans and writes the report and record, and the controller
endorsed whatever stored record it was shown plus its current observations, with
revocation held in an in-memory field that an authorized caller could bypass by
re-endorsing a revoked receipt without rescanning. We decided that the controller's
durably persisted generation is the verification epoch and its only authority state: the
generation advances on disk at every epoch end — every `establish`, every controller
start, every failed or disagreeing live observation (persisted before the failure is
reported), and every abandonment the client declares — and no operation admits a record
whose fence names any other generation. Because `establish` is the first step of
`prepare`, which always performs a full scan and ends its own epoch if it does not
return, a record whose fence names the live generation is proof that the scan that
produced it completed under this epoch.

## Consequences

- Revocation has exactly one form: the generation advances on disk before the refusal
  is written. There is no endorsement state, durable or in memory; `certify` and
  `validate_certificate` collapse into one stateless `validate`, and a lost reply is
  resolved by calling `validate` again under the same generation. Controller restart
  advances the generation and forces a rescan.
- Every failed observation ends the epoch: volume identity, engine transport (connect,
  timeout, status), writer inventory, the PostgreSQL role fence and database identity,
  storage I/O under the maintenance claim, and cancellation during any of these. A
  mismatched argument (wrong run, stored record, report digest, operator or peer) is a
  refusal of the presented receipt and does not end the epoch, so a bad client cannot
  burn another attempt's epoch by sending garbage.
- The fence binds the maintenance database identity as one string
  `<system_identifier>/<database_oid>/<datname>`, captured at `establish` through
  `DatabaseExclusion.identify()` and compared by the adapter at every database
  observation: the client's fence check, `exclude`, and the controller's `validate`. The
  private maintenance settings are loaded once at controller start and are never
  digested or emitted; a configuration edit takes effect only at restart, which ends the
  epoch. Restoring the old database after an observed identity disagreement stays
  invalid because the generation already moved.
- Every `prepare` appends a new report/record pair at the next sequence number; report
  and record share the number, and nothing is reused across `prepare` invocations. A
  stranded report or record is history. `run_id` remains only the audit and
  database-idempotence key.
- Any failure after `establish`, including a loss the client's own fence observed, ends
  the epoch through `abandon(evidence)`, which advances only when the evidence names the
  live epoch; the client never keeps private knowledge of a loss. Residual windows — an
  unobserved loss between fence checks, a failed `abandon` against a live controller, a
  client that dies before sending it — are bounded by the fence-check interval and the
  controller's next observation; they are documented, not closed.
- `prepare` takes the storage claim before `establish`: the kernel lock is the
  coordinator mutex and the epoch is the writer mutex, so a second coordinator is
  refused without ending the first's epoch.

## Considered options

- Move the full scan into the controller. Rejected: the controller is a serialized
  one-request-at-a-time socket server with a 10 s request timeout; an hours-long scan
  there blocks `check` and `restart` and repeats work the client-side service already
  does correctly.
- Sign or hash-chain the report so the controller can verify scan freshness from bytes.
  Rejected: bytes cannot prove when exclusion held, and the cutover operator who would
  present the signature is the same trusted operator who writes both files.
- Persist endorsement (`certified_sha256`) in `ControllerState`. Rejected: in every case
  where it would be consulted the generation already refuses, so it is dead state plus
  one fsync per endorsement and one more invariant.
- A controller-issued token per `establish`, or a digest of the private maintenance
  settings in the fence. Rejected: the token is a second copy of the generation; the
  digest is a secret oracle over a low-entropy file and the wrong proxy for "same
  database".
- Keep the same-run report reuse and refuse any retry whose run already has evidence.
  Rejected: it pushes a new UUID per crash onto the operator and new finding/audit rows
  onto the database for the same population.
