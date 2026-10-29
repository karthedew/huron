# Planning/checking handoff — 2026-10-06

No production implementation is authorized. The user permits planning, prerequisite
checks/corrections and isolated experiments, then requires an explicit approval
checkpoint before production application, migration, deployment or live Starlight
implementation. Fresh deployment and stale-base conflicts are approved; deletion
of existing files/data/volumes is not. All children cited below are terminal.

## Checker contract and product-policy independent review

Maximum reviewer ses_ef0d73ae6ffeShc645txcgdzV5, dispatch
3818200d-e18f-4145-b5d7-2122de0151fe, terminal observed 03:10:36 UTC:

- Checker contract review 2/3: F1-F3 resolved, no new plan-contract defect. The
  correction is limited to retained artifacts; fresh Starlight execution still
  needs its own finite output/reproduction protocol.
- Fresh-deployment/stale-base reconciliation review 1/3: all 11 documents inspected,
  2,084 lines, 100 required headings, eight links; no new policy defect.
- Both COMPLETE verdicts remain FAIL: root checker exits 1 with 2,330 unchanged
  vendor/report whitespace findings, and the original harness fails before case 1.
  This is the known owned defect, not an infrastructure failure or a waiver.
- Strict make docs, diff, ignore and preservation checks passed. Zero changes
  across 77,078 recorded source/roadmap entries, including 553 Git-visible paths,
  HEAD/index and retained artifacts; no relevant residual processes.

Independent proofs: roadmap/checks/3818200d-review-input-proof.json,
3818200d-review-text-contracts.json, 3818200d-review-gates.json,
3818200d-review-preservation.json and corresponding before/after/process receipts.
Requested/recorded maximum selects Astra max; provider effort acceptance is unproven.

Parent approves enrollment of ONLY the exact retained 1,140 vendor Markdown and
44 report attachment identities/hashes and lock/receipt bindings verified in that
input proof, with its non-hostile local-classification limitations. This is technical
authorization for a future prerequisite-checker correction, not a PASS, production
authorization, permission to rewrite artifacts, or permission to enroll new runs.
The future exclusive maximum writer must recheck every binding against this proof
and stop on drift. Preserve original 63 assertions/harness and all authored coverage.

Before actual checker code: finish the self-contained execution-plan placement under
roadmap/plans and exact owned-file/output mapping. Use the reviewed checker contract,
not a broadened artifact registry. Rerun the defect baseline before edits, then require
checker exit0, all63 original cases plus new discovery tests, strict docs and complete
preservation gates, followed by independent maximum implementation qualification.
SDK requalification remains separate; its earlier FAIL is not retroactively changed.

Policy writers now cover immutable pinned base, atomic head/publication comparison,
expected-empty-head races, hidden conflict losers, authorized committed replay even
after head advancement, and explicit newer-base retry with a new identity/fingerprint
and resolved pinned metadata pair. Fresh schema bootstrap and nonempty-target refusal
remain required; legacy-data conversion is not. All product phases remain BLOCKED.
Durable wording in CONTEXT.md:100-101 and design/raw-first.md:61-62,244-246 still needs
a separately owned planning reconciliation preserving pre-existing user edits.

## Identity comparison — recommendation, awaiting user decision

Read-only preparatory discovery ses_ef0f36dd9ffeEhciE8AmPtKa5n, dispatch
eb8472f2-9c2e-4491-bd33-3b76a988b30b, recommended Keycloak as Google sign-in broker
and issuer of separate short-lived Huron-audience API access tokens. Managed Auth0
was compared as an alternative; a bespoke Huron authorization server was rejected
as unnecessary scope. Current configured Keycloak is 26.3, not a qualified production
image/digest. Official 26.3.0 tagged docs support broker/PKCE/device/audience flows;
actual Google/client configuration and device-login traversal remain unqualified.

The user has been asked, but has NOT yet approved this direction. Huron still owns
data permissions; external directory still owns group facts. Current bearer validation
does not yet establish ID-token/access-token discrimination or issuer-qualified account
mapping. PyJWT2.13.0 individual-key cache has no time expiry despite the JWKS-set TTL;
do not promise five-minute removed-key revocation. Browser PKCE state is currently in
a signed, not encrypted, cookie; reconcile server-side state in the future plan.
The full terminal report contains exact code locations, tagged citations and fixture/
real-provider negative matrices. No auth code, provider or service was changed.

## Number-model comparison — proposal requiring a new isolated probe

Read-only preparatory discovery ses_ef0eca713ffePyJ57uRDfbv3Mx, dispatch
64ee04db-01ab-491c-ab4b-7fe0cc5969be, recommends correcting representation/decoding,
not adopting profile2's artificial magnitude gap as product policy. RFC8785 permits
finite binary64 values such as1e20; ordinary Python decoding turns its canonical
integer-form token into an int rejected by rfc8785's separate integer guard.

Candidate: immutable canonical bytes own identity; an explicit number/JSON codec
handles reconstruction and schema validation consistently; JSONB is a derived query
projection, not retry/export authority. This is NOT qualified or implemented. Probe
Python/Node independent oracles and real PG16 round trips, numeric schema bounds,
frozen base inheritance, restarted replay and caller mutation. Include AppendixB
2**68 shortest-decimal spelling, subnormals, maximum finite, negativezero, nonfinite,
nonrepresentable exact integers and JSONB's null-character limitation. Do not silently
round exact caller values or call arbitrary precision fully JCS-compatible. Determine
whether actual metadata needs exact beyond-binary64 values/signed zero; explicit
string/schema representations are alternatives. Raw file contents remain byte data,
not subject to metadata numeric admission. Preserve historical restricted-prototype
PASS as bounded evidence, never relabel it as full-domain qualification.

## No-sudo controlled runner — discovery remains BLOCKED

Read-only preparatory discovery ses_ef0d48b59ffeEXEk3xeRPEDhbP, dispatch
9b14169a-6eeb-41da-83ae-94d173e1a69c, verified the historical Git object and exact
archive digest expected by the unchanged test. Docker27.2.1/Compose2.29.2 are present;
host UID1000 and no Podman. The existing huron-cutover-runner:local image is only an
unqualified inventory candidate, with no discovered reproducible runner recipe.

The focused test bypasses sudo only when pytest itself runs as Linux UID0. Its helper
requires genuinely private rootful Podman/overlay storage/network and performs broad
cleanup only inside that private engine. Host Docker socket substitution, VFS guessing,
or a privileged container on this shared host is not proof or a safe shortcut. Foreign
services are active; port9000 belongs to Ethereum Lighthouse. Nothing was started.

Next: reviewed isolated runner-provisioning prototype, preferably a disposable VM
without host disk/credential shares; sanitized dirty-source projection plus minimal
historical Git object database, actual pinned tool provenance, private engine/storage/
cgroup/network and cleanup proof before the unchanged focused test. No host device,
writable host cgroup, kernel-module, foreign-service or data mutations authorized.
Available disk is not a reservation. Focused runner success would not qualify the
complete contract/integration/durability suite. No sudo, test weakening or skipped gate.
