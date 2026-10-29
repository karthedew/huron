# Phase 005: durable tus transfer and interoperability

Status: BLOCKED — durable-offset/fencing prototype and 002–004 prerequisites.

## Context and outcome

Current RawIngestionService.receive_part(session_id, file_id, part, chunks,
content_length=...) drives numbered parts. Current RawRuntime and PosixRawStore
separate domain/storage owners; 002 combines them as rawstore with private filesystem
implementation and public interface. Tus 1.0 replaces numbered PUT parts, one upload
resource per new/replacement file. Each file PATCHes sequentially, files run under
across-file semaphore concurrency. A completed transfer is not verified/publication.
Full MVP additionally requires full-copy release workflow, metadata/catalog/search,
access, production SDK and integrated UI; this useful backend slice is not MVP PASS.

New datasets require metadata/schema; submissions freeze a bundle and exact base.
Only new bytes are uploaded; retained base copies belong to 006. Authentication and
AccessControl enforce owner/current target authority on every transfer operation;
resource ancestry resolves server-side and hidden resources remain 404.

Approved 2026-10-06: pinned base stays immutable during transfer; head advancement
never auto-repins the attempt or replaces its exact metadata/schema pair. Publication
in 006 atomically compares expected base/current head with catalog publication
under qualified serialization, including expected empty head for concurrent first
pushes. Uncommitted losers return typed conflict (illustrative HTTP 409), no published
lineage/receipt or success; hidden candidates remain recoverable for cleanup.
After authorization, already-COMMITTED same-identity replay returns its original
outcome despite newer head. Caller-reviewed retry against a newly resolved base uses
new identity/fingerprint and exact pinned-pair inheritance, never silent merge/rebase.
This policy is not implemented wire behavior or a qualified DB/FS recovery algorithm.

## Prototype evidence

No tus interoperability or crash probe executed. 001 storage owner creates/runs
root `uv run python roadmap/prototypes/tus_crash.py --root roadmap/prototypes/data --bytes 1048576`.
Use two processes and real local filesystem, disposable PG16 offset/fence ledger;
variable PATCH sizes, zero-length, lost responses, crash before/after fsync and offset
transaction, duplicate/parallel PATCH, wrong offset, short/long body and restart.
HEAD must never advertise undurable bytes. A local advisory lock is not NFS proof;
record exact qualified fencing/durability assumptions, then repeat on nominated NFS
in 010. Primary protocol source: https://tus.io/protocols/resumable-upload .
Choose/pin client interoperability libraries after inspecting official installed APIs.

## Exact scope and ownership

- Replace current `applications/api/routes/v1/endpoints/ingest_sessions.py` part routes
  and corresponding schema models with proposed `endpoints/tus.py` and submission
  control endpoints. Preserve verified error/ownership/expiry behaviors deliberately.
- Proposed post-002 `core/rawstore/interface/{transfer,ports,errors}.py`,
  `_impl/transfer.py`, `_impl/filesystem/tus.py`; runtime/dependencies wiring and
  persistent `core/database/schema/transfers.py`, repositories/transfers.py plus
  Alembic migration. Current `core/raw/{ingest,ports,types}.py` and
  `rawstore/{store,completion}.py` are migration source evidence, not new public paths.
- Delete numbered-part methods/DTOs/routes and completed_parts-only resume contracts
  once all consumers/tests switch; no compatibility multipart adapter. Existing
  tests/ingest_client.py and unit/test_api_ingest_sessions.py evolve by behavior,
  not wholesale replacement. Add tests/contract/core/rawstore/test_tus_offsets.py,
  tests/integration/test_tus_transfer.py; retain process-death/admission scenarios.
- OpenAPI artifact and handwritten binary transport contract via 002 script.
  Ignored browser/Python interoperability probe clients only; production SDK 008/UI009.
- No publication implementation, migration resets, broad auth permissions, or array work.

Fresh deployment approved 2026-10-06 removes legacy active-upload conversion/draining
from MVP acceptance. Schema bootstrap/Alembic and new-session recovery still apply.
Nonempty targets refuse with operator action; no cancellation/deletion/reset of
existing uploads/data/volumes is authorized. Numbered-part behavior stays current
until atomic owned code/test cutover; never reinterpret part numbers as offsets.

## Interfaces and implementation examples

Proposed public domain operations, illustrative until prototype qualification:

```python
async def create_upload(actor, submission_id, file_spec) -> UploadHandle: ...
async def inspect_upload(actor, upload_id) -> DurableProgress: ...
async def append(actor, upload_id, expected_offset, chunks, length) -> DurableProgress: ...
async def cancel_upload(actor, upload_id) -> None: ...
```

Ports carry bounded byte streams and fence identity; application parses binary
headers/status and offloads blocking filesystem work, not buffering whole request.
Proposed durable append protocol: obtain cross-process same-file fence, reconcile
physical bytes against committed ledger offset, validate expected offset and declared
remaining length, stream bounded writes, fsync payload, commit ledger offset under
same fence, return offset. If ledger commit fails, HEAD remains at old offset and
recovery truncates unacknowledged tail under exclusive ownership before retry.
If response is lost after commit, HEAD returns durable offset without re-appending.
This is a hypothesis requiring crash evidence, not a proven NFS protocol.

Separate limits: client across-file semaphore; API transfer admission; verified-copy
admission in 006; deployment-wide capacity reservations; same-file fencing. Process
semaphore alone satisfies neither global capacity nor fencing. Short/oversize bodies,
offset conflict, unsupported Tus-Resumable and expiry return accurate statuses.
Zero-byte files still validate metadata/manifest/checksum and reach complete offset.
HEAD includes no-store; OpenAPI documents Tus-Resumable, Upload-Offset/Length,
Location, PATCH media type and all success/error statuses. Advertise only implemented
tus extensions. Whole-file hash/size/path verification remains separate from offset.

## Serial task slices

1. Pending: durable ledger/fence/recovery and capacity admission; real multi-process
   contract tests, no public PATCH until crash prototype supports it. Full Python gate.
2. Pending: POST/HEAD/PATCH binary HTTP and OpenAPI, bounded streaming/cancellation;
   delete owned numbered-part code and migrate helpers at reviewed atomic cutover.
3. Pending: variable PATCH/zero-length/retry/browser+Python interoperability and
   process-death acceptance. Preserve existing 9 GiB interrupted/resume/read proof
   through protocol migration, not a substitute for eventual 50-user qualification.
Each slice has independent baseline/final reruns, exact scope above, skills below,
full gate below and max three serial reviews. No standalone “transfer done” MVP claim.

## Skills

`.agents/skills/oop-design/SKILL.md`, `.agents/skills/fastapi/SKILL.md` plus streaming
reference, `.agents/skills/postgresql-table-design/SKILL.md`,
`.agents/skills/implementation-plan/SKILL.md`; `.agents/skills/playwright-cli/SKILL.md`
for browser interoperability. No Svelte component work in this phase.

## Acceptance and complete applicable gates

Root locked uv/Python >=3.12: `make lint`;
`uv run pytest -m unit --cov=src/huron --cov-report=term-missing`;
`uv run pytest -m contract`; `uv run pytest -m integration`; `make test-acceptance`;
`make docs`; `git diff --check`; `uv run python scripts/check_openapi.py --check`;
`uv run python scripts/check_database_schema.py` (scripts must exist from 002/004).
Prerequisites PG16/testcontainers, real filesystem, isolated Linux/Podman complete
integration runner with historical Git object, >=25 GiB acceptance free disk. NFS
claims require actual nominated NFS; missing environment is BLOCKED, never skip.

Retain 96.01% coverage floor, import contracts, radon C+/MI B+ diagnostic findings,
complexipy 15 and duplication 0.80 ratchet; no suppressions/xfails/weak assertions.
Reuse tests/contract/test_ingest_process_death.py, test_writer_exclusion.py,
tests/integration/test_verified_raw_ingest.py and tests/acceptance/test_raw_ingest_gate.py.
Deterministic clocks/barriers, real disk/DB locks, mocks only external boundaries.
Capture memory/backpressure evidence and every crash point. Named-session CLI
browser upload probe uses owned server and ignored artifacts; no full frontend gate
unless frontend source changes (then replan scope and include all web gates).
Independent reviewer reruns commands and interoperable clients with exits/logs.

## Blockers and readiness

001 durable-offset/fence corpus and nonempty-target refusal proof, 002 owner/stack
cutover, 003 authority, 004 submission schema freeze. Prototype owner names NFS
limitations explicitly. Independent review before
`/implement-markdown roadmap/plans/005-tus-transfer.md`.

## Execution ledger

Planning writer attempt 1; no implementation/probes/checks run for phase; review 0.
Future session/role/model/timestamps/command/verdict must be recorded. Progress at
least every 15 minutes, parent poll every minute; one writer or reviewer at a time.

## Escalation / final receipt

BLOCKED draft. Receipt must prove durable HEAD after crashes, binary interoperability
and owned path deletions; neither a tus library import nor transferred bytes proves publication.
