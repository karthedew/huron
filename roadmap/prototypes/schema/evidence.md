# Prototype evidence: restricted schema composition and frozen metadata pairs

Current disposition: F1 fix attempt 1 self-check complete; ready for independent
maximum review 2 of at most 3. Review 1 was FAIL, not invalidated by its green
corpus/gates. The correction and exact red/green receipts are recorded below.
This is not independent PASS, shipped functionality or an approved product profile.

## Scope, profile and coordination

Original run (historical): non-production, isolated ignored throwaway experiment, implementation/prototype
attempt 1, 2026-10-05. Dispatch e317f71d-5d70-4816-97e8-e3bdaa10d650;
session ses_ef54624e6ffeD4LI60hgCgwJ1l. Configured preparatory/Low on
openai/gpt-6-astra; provider effort acceptance is not proven. This self-check is
neither independent review nor product-gate qualification. No code promoted.

Canonical claims: source:repo/read; plan:raw-phases/read (001–010);
prototype:schema/write (only roadmap/prototypes/schema/**);
build:docs/write, cache:uv/write, env:python/write for ordinary root docs outputs.
UV_CACHE_DIR=/tmp/opencode/huron-effort-uv-cache. No services, ports, external
fixtures, node tooling, OpenCode CLI, global skills or live source/config writes.
Claims are cooperative, not a sandbox. Inherited skill-resolution tooling issue
remains unresolved; canonical local skill files were read directly. No resume,
restart, lock manipulation or delegation occurred. Parent owns recovery and review.

Initial Git status showed extensive pre-existing staged tooling migration and
unstaged documents, frontend API files, deletions and untracked catalog interface
and design/raw-first.md. All belong to others. The prototype directory did not
exist. Before candidate edits, a digest of all extant Git-visible files and the
index was recorded; [the preservation check](check_artifacts.py) rechecks those
bytes, including locks/config/source. Ignored runtime assets outside this directory
are not covered by that fingerprint; no preservation claim is made for their
concurrent tooling outputs.

## Question, inputs and hypothesis

Sources: design/raw-first.md metadata section; CONTEXT.md Schema bundle and
Metadata/schema pair; readonly phase001 and phase004 contracts. This bounded
assignment overrides their older flat prototype-path illustrations, not their
readiness status. [Pre-run contract](experiment.md) records versions, hypothesis,
source/helper discovery and inputs. [Corpus](corpus.py) fixes named expected code
and RFC6901 location before execution. Cases 01–39 preceded the first run; 40–43
were fixed additional bounds before the second run. No failed expectations were
changed and no skip/xfail/suppression was used.

Composition hypothesis supported within the tested restricted profile: merge disjoint explicit
property maps and union required sets, then close the resulting object. Nested
objects close independently. Exact base-pair inheritance and frozen retries need
field presence and immutable content, not latest resolution or a nullable default.
The original claim that every admitted pair was usable was disproved by review F1;
the original 43-case corpus did not establish numeric roundtrip closure.

Counterexample observed: Draft202012Validator applied to allOf of a closed BASE and
EXT rejects {title: run, count: 2} with additionalProperties. The compiled profile
accepts that same instance (case03). A closed-base allOf is not the proposed design.

## Candidate profile and APIs

[Shared candidate](candidate_profile.py) has two immutable values, SchemaBundle and
MetadataPair; FrozenSubmission is only an in-memory retry handle. Composition,
presence resolution, bounds and graph checks are pure functions. No registry
service hierarchy or per-helper classes. JCS bytes remove nested aliasing, unlike
a frozen dataclass holding mutable dictionaries. This has serialization/decoding
cost, accepted for a small probe; no performance claim.

- Dialect: exact Draft2020-12 URI when declared; absent declaration defaults to the
  explicitly recorded profile dialect. Compiled root declares that dialect.
- Root components require explicit object properties. Extension property names
  must be disjoint even for identical definitions. Required may name only own
  properties. Nested additions inside an existing base property are deliberately
  forbidden, not merged; extension-owned nested objects are allowed and closed.
- Supported types: object, string, integer, number, boolean, homogeneous array.
  Per-type allowlist: object properties/required/additionalProperties=false;
  string minLength/maxLength/format; number/integer minimum/maximum;
  array items/minItems/maxItems. Type is mandatory unless the entire node is $ref.
- Unsupported: boolean schemas, null/union types, enum/const, allOf/anyOf/oneOf/not,
  if/then/else, pattern/patternProperties, unevaluatedProperties, dependencies,
  $id/$defs/$anchor/$dynamicRef, defaults, annotations and all other unlisted
  keywords. Reject, do not silently ignore. $ref siblings/root-component $ref reject.
- Format policy: only date-time, explicitly checked through installed
  FormatChecker(formats=["date-time"]). Unknown and otherwise standard formats
  reject at compile. Not a claim of complete format-assertion vocabulary support.
- References: exact urn:huron:schema:NAME:POSITIVE_VERSION and separate SHA-256
  pin over original RFC8785 bytes, copied into bundle identity. Alias alone is not
  trusted. Every supplied resource (including unused) is checked and frozen.
  Different bytes under the same expected digest reject; duplicate aliases reject.
  No fragments, relative URIs, network URIs, $id rebasing or lazy retrieval.
  Registry(retrieve=deny_retrieval).with_resources uses DRAFT202012.create_resource;
  iter_errors exercises actual installed referencing resolution on valid refs.
  A graph walk rejects cycles/missing refs/depth before validator traversal.
- Limits: canonical document 65536 bytes; aggregate originals/profile/pins 262144
  bytes; 32 resources; JSON nesting 32 edges; 4096 JSON nodes; reference depth 8
  edges and 4096 expanded reference visits. Iterative JSON admission precedes JCS
  and schema recursion. The structural and reference budgets are distinct; bounds
  do not establish production throughput or a fully hardened parser/memory budget.
- Numeric profile proposal 2: single-document admission must preserve numeric value
  and exact JCS bytes under ordinary json.loads followed by rfc8785.dumps. Unsafe
  Python integers, nonfinite values and floats that decode to unsafe integers reject
  as non_jcs at admission. Both signs of 1e20 reject; compatible fractional, safe
  integral, subnormal and finite exponent-form values (including 1e30 and maximum
  binary64) remain valid. This is narrower than RFC8785; see the correction rationale.
- Metadata: ABSENT sentinel differs from null and {}. New omission rejects;
  explicit replacement requires bundle; schema-only rejects; later omission returns
  the exact base object. Latest is not a resolution input. Bundle identity includes
  originals, refs, pins and profile; pair identity includes metadata and bundle hash.
- Errors: Rejected(code, path), with normalized RFC6901 pointer. Root pointer is
  empty. Required/additionalProperties errors point at the containing object,
  not a parsed human error string. First error chosen deterministically by instance
  pointer, validator keyword, schema pointer; all-error aggregation is not modeled.

Concrete future interface example (candidate, not shipped):

```python
bundle = SchemaBundle.compile(base_document, extension_document, pinned_resources)
pair = resolve_metadata(supplied=metadata_or_ABSENT, bundle=bundle, base=base_pair)
frozen = FrozenSubmission(pair)
assert frozen.retry() is pair
```

[SDK caller package](candidate_sdk/__init__.py) maps Python dictionary membership;
[backend caller package](candidate_backend/__init__.py) independently JSON roundtrips
and maps body membership. Both invoke the same shared profile. They are separate
prototype package directories, not built distributions, transport endpoints or
phase008 SDK packaging proof. Agreement detects mapping/presence drift, but cannot
detect a shared-validator/common-mode error. Explicit expected outcomes and the
allOf counterexample provide partial independent oracles; independent review and
broader conformance/adversarial testing are still required.

## Original commands and observed outcomes (historical)

All cwd /home/karl/repo/huron. Dependencies already installed; no install requested.
jsonschema 4.26.0, referencing 0.37.0, rfc8785 0.1.4, zensical 0.0.57 verified via
importlib.metadata before implementation. Official versioned jsonschema API docs,
referencing 0.37.0 API docs and Draft2020-12 validation spec consulted (URLs in
experiment.md). Documentation fetches did not retrieve runtime schemas.

| Exact command | Observed outcome |
| --- | --- |
| `.venv/bin/python -B roadmap/prototypes/schema/schema_bundle.py` | Exit 0 twice: first 39/39 per seam (78); then 43/43 per seam (86), all acceptance/error locations and successful pair digests agree. Counterexample asserted. Runtime socket connect/create_connection/DNS guards active with zero attempts. |
| `git diff --check` | Exit 0 baseline and post-probe; no whitespace diagnostics. |
| `python roadmap/check_docs.py` | Exit 0 baseline and post-probe; local links/fragments, ignored-plan dependencies, whitespace and phase structures pass its checks. |
| `UV_CACHE_DIR=/tmp/opencode/huron-effort-uv-cache make docs` | Exit 0; uv run --group docs zensical build --strict; No issues found; build finished in 0.21s. Ordinary ignored site/cache outputs only. |
| `git check-ignore -v roadmap/prototypes/schema/schema_bundle.py roadmap/prototypes/schema/evidence.md` | Exit 0; both matched .gitignore:40:/roadmap/. |
| `git ls-files roadmap` | Exit 0; empty. |
| `.venv/bin/python -B roadmap/prototypes/schema/check_artifacts.py` | Exit 0; 535 existing Git-visible file bytes and index bytes preserved; 8 ignored text files and 6 local links checked with no whitespace defects. |

Pre/post combined Git-visible byte fingerprint:
f1759128374aebe2282850cc4fd2428fd35805db80cdacfeb50933c2cf6469c5.
Pre/post index fingerprint:
53998d200d18ee33dbebebc0aef391c4a4972ed0c8ba6afc23d052846c1283f8.
The preservation checker intentionally fails if future unrelated source work changes
that historical inventory; this is a receipt check, not a reusable product test.

Acceptance includes every required case01–30. Extras31–43 cover unknown format,
schema size, valid empty object, nested overlap, extension required scope, reference
siblings, unsafe JCS integer, referenced validation location, ref alias mutation,
metadata depth/node bounds, reference-count and aggregate-size bounds. Full outcome
lines are emitted by the reproduction command; fixtures/expected codes are stored
in corpus.py. No application Python unit/lint/contract/integration gate applies to
this ignored experiment-only slice; no applicable gate was weakened or skipped.

## Limits, decision and handoff

Recommend carrying compile-then-close and immutable presence-aware pairs into
phase004/008 planning, subject to independent review and explicit profile approval.
Do not promote these files. No real database/NFS/tus/identity/access/concurrency or
durable idempotency guarantees: FrozenSubmission only models an already-admitted
retry handle, not identity fingerprints, conflict handling, crash persistence or
publication. It does not accept/reconcile a changed request under an identity.

SchemaBundle/MetadataPair dataclass constructors are trusted internal prototype
paths; arbitrary callers could bypass factories. Product design must guard decode,
construction and persistence re-admission. Candidate envelope shape validation,
duplicate JSON keys, hostile parser input, Unicode surrogate diagnostics, recursive
Python objects at SDK transport boundaries, authorization, version ownership and
transactional pins are out of scope. Resource graphs can be pinned with alias cycles
(case17); cycle rejection is genuine, not relying on impossible hash self-reference.

Remaining blockers: independent parent-dispatched review 2 after F1 correction,
durable profile decision and downstream inline evidence reconciliation, plus separately
owned tooling skill resolution. Missing user data/issuer/stale-base/hardware/SLO
decisions are not approved or resolved by this probe. Cleanup ownership is the
schema prototype owner/parent only; preserve unknown files. No commit, stage,
branch, push, service change, plan edit or shipped-product PASS claim.

## Independent review 1 finding and correction attempt 1

Supplied independent maximum review 1, ses_ef53be358ffePC58OGZ2ioSv6K, returned
FAIL. It reported all original 43 cases/86 outcomes and gates passing, plus 70
supplemental closure/reference/security/exact-byte/node/depth cases. Those are
reviewer-reported historical results, not this fix worker's independent rerun.
There was one confirmed finding, F1, on supported submit paths:

- Pre-fix candidate_profile.py lines 230–243 admitted
  `{"metadata":{"x":1e20},"bundle":{"base":{"type":"object","properties":{"x":{"type":"number"}},"required":["x"]}}`
  at both SDK and backend seams. The returned scientific bytes were
  `b'{"x":100000000000000000000}'`. Reading pair.sha256 (pre-fix lines 254–257)
  raised rfc8785.IntegerDomainError; bundle.validate(json.loads(pair.scientific))
  raised Rejected("non_jcs", ""). No constructor bypass or hostile parser was needed.
- A correctly JCS-digest-pinned resource `{"type":"number","minimum":1e20}`
  passed initial canonicalization but decoded to a Python integer outside the
  installed encoder's domain. Re-encoding the copied resource/original aggregate
  in compile (pre-fix lines 193–221) raised unnormalized IntegerDomainError at both
  seams. A green shared-validator corpus had missed a shared-validator defect.

Fix dispatch 64bcb4e0-aa3b-4f00-8f13-97002f6e22e7; session
ses_ef530bd00ffeP74SHc4LbotQmI; fix/prototype attempt 1, 2026-10-05, configured
maximum/Max on openai/gpt-6-astra. Provider effort acceptance is not observed or
proven. Original Low provenance remains unchanged. Start was 06:45:17Z; first
complete green gate set was recorded by 06:53:54Z. No child delegation, service
operation, production/config/phase-plan/lock/index edit or journal maintenance.
Read all eight original prototype files, full 001 and 004, AGENTS, canonical
prototype/implementation-plan/OOP skills and applicable OOP references directly.
Claims remain exactly source:repo/read, plan:raw-phases/read, prototype:schema/write,
build:docs/write, cache:uv/write, env:python/write. No .agents build was run.

### Correction and numerical profile proposal

The existing canonical() admission function still performs the same iterative
depth/node/text and encoded-byte bounds. Before returning bytes it now decodes
that bounded payload with ordinary json.loads, re-encodes with rfc8785.dumps and
requires both numeric-value equality and byte equality. Failure is normalized to
Rejected("non_jcs", "") **at admission**, shared by metadata, base, extension and
every reference document. Derived schemas only compose admitted numeric values.
Neither pair.sha256 nor its identity format was changed to catch a late exception.
The backend's allow_nan=False JSON encoder now also maps its admission ValueError
to non_jcs. No rounding, truncation, custom parse_int or coercion was introduced.

PROFILE is now huron-restricted-metadata-probe-2, deliberately binding the tightened
proposed contract into bundle identities. Successful bundle/pair digest strings
therefore change from profile 1; no old digest compatibility or product migration
is claimed. The original 43 expected codes/paths/inputs/modes remain byte-for-byte
identical under a deterministic fixture serialization.

Installed rfc8785 0.1.4 admits Python ints only in ±(2**53-1), but its float path
emits integer-form tokens for 2**53 <= abs(x) < 1e21. Ordinary json.loads makes those
tokens unsafe Python ints. Thus this proposed interoperability profile rejects
that float interval, symmetrically, while retaining compatible finite fractions,
subnormals, safe-integral floats and exponent-form values at/above 1e21 through
the maximum finite binary64. Exact numeric equality is relative to the submitted
Python int/binary64 value, not arbitrary decimal precision or lexical spelling.
Signed zero follows RFC8785's 0 normalization. All floats remain subject to the
explicit fixed-point check, not just a hard-coded magnitude guess.

RFC8785 section 3.1, 3.2.2.3 and Appendix B permit a broader binary64 domain than
this library/decoder combination (1e20 is not inherently forbidden by JCS).
Appendix D recommends strings for extra precision. The official v0.1.4 library
API and installed implementation were inspected; exact URLs and assumptions are
in experiment.md. Keeping the ordinary decoder and making admission a fixed point
was the smallest local correction; blanket float rejection would discard compatible
science values, and a new decoder/numeric representation would be a wider design.
The extra bounded decode/encode has cost; no performance claim is made. This is a
prototype profile proposal awaiting owner approval, NOT a shipped product choice.

### Coverage and exact red/green receipts

Reuse: corpus.case/supplied/pin and the existing two-seam runner, with deterministic
deep-copied inputs. All 43 old cases remain. Added 387 fixed cases: 49 numeric values
at metadata plus minimum/maximum in base/extension/reference (343); NaN and both
infinities at all seven sites (21); accepted/rejected fractional min/max ranges for
number and integer schemas at all three schema sites (18); nested-array numbers
(5). Both signs cover safe-int edges as ints and floats, 1e16/1e20, adjacent 1e21
values, 6.02214076e23, maximum finite, fractions, subnormals and decimal notation
boundaries. Unsafe Python ints/nonfinite reference documents cannot have valid JCS
pins; their fixtures use an explicit unusable placeholder and require non_jcs before
digest checking. Every finite 1e20/unsafe-float reference fixture has a correct pin.

For all 266 successful main cases per seam (532 total), assert usable pair identity,
value preservation, stable raw canonical documents, ordinary-JSON revalidation,
full bundle reconstruction, full public-seam resubmission and frozen retry. Extra
successful base/latest/replay pairs receive the same usable-pair checks. The try/
except that recognizes expected Rejected outcomes now encloses only submit: a
post-return Rejected or library exception is a hard failure, never an expected
admission rejection. Existing mutation/inheritance assertions were retained and
strengthened, not replaced. All 164 rejection cases per seam (328 total) match
fixed normalized codes/locations. Socket/DNS guards remain active; no runtime IO.

All commands below ran from /home/karl/repo/huron with existing dependencies, no
upgrades. Python 3.12.4, jsonschema 4.26.0, referencing 0.37.0, rfc8785 0.1.4,
zensical 0.0.57 were verified before and after the docs build.

```sh
.venv/bin/python -B -c 'import platform, importlib.metadata; print("Python", platform.python_version()); print({n: importlib.metadata.version(n) for n in ("jsonschema", "referencing", "rfc8785", "zensical")})'
```

This version command exited 0. Final post-evidence rerun of the complete command
set below also exited 0; docs built in 0.22s on that rerun. The final version/fixture
fingerprint receipt was printed at 06:56:56Z; full runner and preservation checks
completed green in the same gate batch.

| Exact command | Observed outcome |
| --- | --- |
| `.venv/bin/python -B roadmap/prototypes/schema/schema_bundle.py` before edits | Exit 0, original 43/43 cases per seam, 86 outcomes. This did not disprove F1. |
| `.venv/bin/python -B roadmap/prototypes/schema/reproduce_numeric.py` before candidate fix | Exit 1, all four counterexamples reproduced: metadata invalid pairs at both seams (identity IntegerDomainError; revalidation non_jcs), pinned minimum unnormalized IntegerDomainError at both seams. |
| `.venv/bin/python -B roadmap/prototypes/schema/schema_bundle.py` with new tests before candidate fix | Exit 1, first unsafe float 9007199254740992.0 returned a pair and failed the universal postcondition with IntegerDomainError. Original 43 expectations still matched. |
| `.venv/bin/python -B roadmap/prototypes/schema/reproduce_numeric.py` after fix | Exit 0, 0/4 counterexamples remain; all four reject during submit as non_jcs at root. |
| `.venv/bin/python -B roadmap/prototypes/schema/schema_bundle.py` after fix | Exit 0, 430/430 cases at each seam, 860 expected outcomes, including 532 successful and 328 rejected main outcomes. Universal identity/replay/revalidation/reconstruction checks pass; naive closed-base allOf counterexample still asserted. |
| `git diff --check` | Exit 0, no whitespace diagnostics. |
| `python roadmap/check_docs.py` | Exit 0, documentation links/fragments, ignored-plan dependency checks, text whitespace, phase references/skills/structures pass. |
| `UV_CACHE_DIR=/tmp/opencode/huron-effort-uv-cache make docs` | Exit 0, uv run --group docs zensical build --strict; No issues found; build finished in 0.21s. |
| `git check-ignore -v roadmap/prototypes/schema/schema_bundle.py roadmap/prototypes/schema/evidence.md` | Exit 0, both match .gitignore:40:/roadmap/. |
| `git ls-files roadmap` | Exit 0, empty. |
| `.venv/bin/python -B roadmap/prototypes/schema/check_artifacts.py` | Exit 0, original 535 Git-visible file bytes and index bytes preserved; 9 ignored text files and 6 local links pass. No preservation baseline changed. |
| `git diff --cached --exit-code a1a4afc4bf332649146b726fc59fa0e560fbb591 --` | Exit 0, existing staged tree unchanged against the assigned object. |

Original-case preservation command (exit 0 before and after; before used all CASES,
then after used CASES[:43]):

```sh
PYTHONPATH=roadmap/prototypes/schema .venv/bin/python -B -c 'import hashlib, json; from corpus import CASES; print(hashlib.sha256(json.dumps(CASES[:43], sort_keys=True, separators=(",", ":")).encode()).hexdigest())'
```

Fingerprint: 3df9b1bcc3ecb20bbe842db29a9b8e565dea713c7278e5f75a9799b82a49b7a4.
Source/index fingerprints remain the originals printed above. Limits remain
65536 single-document bytes, 262144 aggregate bytes, 32 JSON edges, 4096 JSON nodes,
32 refs, 8 ref edges and 4096 expanded visits. No thresholds, skips, xfails,
exclusions or assertions were relaxed. No application gates apply to this ignored
prototype-only slice; all assigned gates were run. There was no missing service
infrastructure because this question does not use services.

### Exact owned changes and handoff

All changes are under ignored roadmap/prototypes/schema/:

- candidate_profile.py: admission fixed-point/value check and proposed profile 2.
- candidate_backend/__init__.py: normalize JSON numeric admission ValueError.
- corpus.py: append the 387 numeric cases and reuse-compatible numeric fixture helper.
- schema_bundle.py: universal successful-pair postconditions, strict admission-only
  rejection handling and honest self-check banner/output.
- reproduce_numeric.py: added, four-case public-seam red/green reproduction.
- experiment.md: append pre-fix numeric hypothesis, profile rationale and official sources.
- evidence.md: preserve historical provenance/results and record F1, correction and gates.

candidate_sdk/__init__.py and check_artifacts.py are unchanged. The only new file
is reproduce_numeric.py, explaining 8 → 9 owned text artifacts. No deletions,
rebaseline, source/config/test/docs/phase-plan/lock/index changes, staging, commits,
branches, push, service startup or promotion. Source preservation is byte-checked,
not inferred from ignored git diff. Unknown work/data remain untouched.

Ready for parent-dispatched independent maximum review 2, not independent PASS.
Shared-validator/common-mode risk remains; these are not built SDK/backend products.
No DB/NFS/tus/auth/access/transaction/concurrency/durable-receipt claim. All original
constructor/parser limits remain explicit. User approval of a numeric product
profile and downstream plan reconciliation remain separate blocked work.
