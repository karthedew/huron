# Raw interface-cutover inventory receipt

Preparatory read-only worker `ses_ef15b508fffeNQwpUX7e6fOXxl`, dispatch
`9d2cb369-b968-4bbb-bf85-50216f0902d8`, returned a terminal inventory report on
2026-10-06. Its complete module/symbol/consumer tables and line citations are in
that session's final response. This is not independent product qualification or
phase002 READY; no source, plans, caches or services were changed.

Verified counts: 18 Raw Python files (12 top-level, six private), seven Rawstore,
17 Metastore and seven Foundation. The historical assignment's count of 19
Metastore files was wrong; never invent deletion targets to match it.

Important verified constraints for the phase owner:

- Security consumes Foundation slug validation, shared errors and a type-only
  idempotency claim. Catalog already depends on Security; wholesale movement into
  Catalog introduces a forbidden reverse edge.
- Error inheritance affects Security denial handling, Integrity verification and
  HTTP registration. DomainError carries HTTP rendering today; owner-specific
  errors require coordinated raise/catch/transport mapping, not a spelling-only move.
- Private filesystem implementations still need a supported application construction
  boundary; API and lakectl cannot import newly private adapter paths.
- Include API problems/errors/expiry/guards/DTOs, all lakectl wiring/controller
  consumers, scripts/main.py, tests/controlled_deployment.py and private-coupled
  durability tests in the exact move map.
- MetadataSubmission and Integrity persistence/evidence Pydantic models need explicit
  domain-versus-transport boundary decisions. No byte-format change by relocation.
- UUIDv7 is used in domain creation and database adapters; clock ports have type-only
  consumers and the concrete SystemClock currently lives in Metastore. Constructor
  injection must update applications without Core importing Applications.
- Duplication baseline signatures include file paths. A move needs reviewed
  relocation-only accounting that preserves counts, similarity 0.80 and the
  no-new/no-growth rule, not a regenerated looser baseline.
- Current server wheel owns huron/__init__.py. The SDK must not introduce a second
  distribution owning that same file; namespace/co-install/uninstall qualification
  is still needed.

The current Project, numbered-part, revision/tag and policy semantics remain until
their separately scoped semantic cutovers. Structural interface work must preserve
404 nondisclosure, authorization-before-replay, transaction atomicity, crash recovery,
maintenance exclusion and existing scale tests. The proposed schema prototype's
numeric policy must not silently replace existing canonicalization during a move.

Remaining: exhaustive Security/transitive/string-reference consumer closure; exact
destination decisions for errors, slug rules, claims, clock/ID providers and adapter
construction; a final acyclic graph proof; runner/prototype/owner prerequisites.
Those gaps prevent phase002 execution, not independent docs work.

Read-only checks from repository root: git diff --check and full git status both
exit 0 before/after; HEAD 2b2e9c0; 51 tracked changes and four untracked files
preserved. No application tests or product PASS were claimed.
