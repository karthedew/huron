# D6a candidates from the D1 native report

Read-only inventory of `duplication-src.json`, counted from `clone.clones` and
checked against source behavior. No changes, gate runs, or predicted score gains.
Locations below are D1 report locations; remeasure after D2–D5 before selecting.
Catalog/core hierarchy/HTTP duplication already assigned to D2–D5 is excluded.

## First bounded slice: optional auth reads

| Exact matching symbol | D1 file/range | Preserve |
| --- | --- | --- |
| PostgresApiKeyStore.get | api_keys.py:47–70 | Unknown handle -> None; revoked/expired rows returned unchanged for resolver evaluation |
| PostgresCredentialStore.get | credentials.py:44–64 | Unknown/missing password -> None; hash and provenance unchanged |
| PostgresSessionStore.get | sessions.py:46–68 | Unknown UUID -> None; both expiry timestamps and revoked state returned unchanged |
| PostgresPrincipalStore.get_user_by_subject | principals.py:56–81 | SQL filters to enabled users; disabled user and service-account subject return None |
| PostgresPrincipalStore.get_by_id | principals.py:135–154 | No kind/disabled filter; any principal returned to authorized administration |

Paths are under `src/huron/pkg/metastore/`. A typed adapter-private optional-query
executor can own fetch-one plus None/decoder handling, paired with fixed trusted
projections and explicit predicates. The two principal reads share their column
projection/decoder, but must retain different filters. Keep public auth ports and
concrete method names unchanged; their callers include password verification,
API-key/session resolvers, principal resolution and IdentityService.

Retain `rows.api_key_record`, `credential_record`, `session_record` and
`principal_record`: API-key owner aliases/UUID-to-string/scopes conversion, session
groups and auth method, and kind/disabled semantics are explicit contracts. No
reflective `Model(**row)` codec. Generic execution must not absorb security policy.

## Second bounded slice: required RBAC reads

| Exact matching symbol | D1 rbac.py range | Preserve |
| --- | --- | --- |
| PostgresRbacStore.get_role_binding | 543–565 | Missing row -> ResourceNotFound with binding-specific message; stored expiry returned |
| PostgresRbacStore.get_service_account | 757–783 | Principal-ID lookup joins principals for subject/disabled_at; disabled accounts retained |
| PostgresRbacStore.service_account_by_subject | 785–809 | Same joined projection, subject lookup; missing subject -> account-specific ResourceNotFound |

A distinct required-query operation may share fetch/decode mechanics with the
optional operation while keeping required-error identity explicit. Service-account
projection has two real lookup callers and a list caller. Current callers are
AccessPolicy's BindingFacts lookup, governance workflows and IdentityService;
D4 will change their module names before this slice runs. No broad repository
facade is needed and no core interface should expose SQL.

`PostgresRbacStore.bindings_at` (645–677), `list_service_accounts` (811–837), and
`list_policies` (972–992) are secondary list-execution candidates. Preserve exact
scope including NULL via IS NOT DISTINCT FROM, expired/disabled inclusion and
C-collated ordering. These are currently complete lists, not the catalog keyset
collection contract: do not silently paginate or filter them during helper reuse.

## Keep distinct from ordinary reads

- `PostgresRbacStore.revoke_role` (516–541) is atomic DELETE RETURNING; never replace
  it with get-then-delete. It may share result decoding only through a clearly
  mutating operation that preserves the single statement.
- `PostgresPrincipalStore.upsert_oidc_user` (83–133) is INSERT ON CONFLICT RETURNING
  with precise subject-collision translation; always returns a row and preserves
  disabled state. `disable` (195–218) is UPDATE RETURNING, permits any kind and
  replaces the disable timestamp. Neither is an optional ordinary lookup.
- `PostgresApiKeyStore.revoke_all_for` (131–154) and
  `PostgresSessionStore.revoke_all_for` (138–159) share execute/count mechanics,
  already using `affected_row_count`. Keep active-only update and timestamps;
  extracting another one-line wrapper alone earns little interface depth.
- `PostgresIngestWriter.lock_ingest_session` (652–670) must retain FOR UPDATE on
  its already acquired connection through the enclosing transaction. The similar
  `PostgresIngestReader.ingest_session` (850–867) is an ordinary pooled read.
  Do not merge those execution lifetimes. `ingest_file` (888–906) returns the
  nested LedgerEntry with session membership, not only the decoded file.
- Memory RBAC mutations and account lookups also appear in clone.clones. Their
  state ownership/uniqueness/compiled-binding effects are distinct from SQL query
  execution; do not fold them into this D6a slice merely for matching syntax.

## Acceptance and integration

Run real `tests/contract/test_auth_store.py` and `test_rbac_store.py`, existing
`tests/unit/test_stores_rows.py`, and affected password/API-key/session/principal
and authorization tests. Preserve missing-row, disabled-account and wrong-kind
cases plus exact auth record conversions; use existing public store contracts,
not mocked fetch-call assertions. HTTP login/session/API-key/service-account tests
check resulting refusal/redaction behavior. Strict wiring type checks prove the
unchanged ports; no protocol weakening or unchecked casts.

If Raw reads are selected later, include real commit-intent/process-death contracts
and restart integration. Touching mutation/fencing/durability semantics would add
D6b's full requirements; it is unnecessary for the first optional/required slices.
Preserve the exact current complete native report after each selected slice and
compare changed/new matches: these opportunities do not establish native 90.
