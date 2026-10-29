# Restricted metadata composition experiment (non-production)

Recorded before running the corpus, 2026-10-05. Configured dispatch:
implementation/prototype, preparatory (Low), attempt 1. Provider effort acceptance
is not independently observed. Own only this ignored directory. Existing extensive
staged tooling changes and unstaged source/documentation work are not ours.

## Hypothesis and fixed expectations

Compile disjoint base/extension property maps, union required fields, then close
the final object. Nested objects are independently closed; an extension cannot
modify any existing top-level property, including adding inside a base object.
References use registry-only immutable version URNs with separately verified JCS
SHA-256 pins. No reference siblings, fragments, dynamic references or network IO.
Absent metadata inherits the exact base pair; null rejects; empty is validated.
Frozen retry returns the original pair, not a re-resolution of latest.

The first 30 named cases and expected outcomes are fixed by the dispatch. Their
concrete data and explicit expected error codes/JSON pointers will be in corpus.py
before first execution. Additional fixed boundaries: unknown format rejects,
schema size overflow rejects, empty metadata with empty schema accepts, nested
overlap rejects, required outside own property map rejects, ref siblings reject,
unsafe JCS integer rejects. Naive closed-base allOf must reject the otherwise
valid additive instance. Any mismatch fails the run, including seam disagreement.

## Versions and inputs

Verified using `.venv/bin/python -B -c` and importlib.metadata before editing:
jsonschema 4.26.0, referencing 0.37.0, rfc8785 0.1.4, zensical 0.0.57.
Use installed Draft202012Validator.check_schema/iter_errors, FormatChecker,
Registry(retrieve=deny)/with_resources and DRAFT202012.create_resource.
No dependency installations or product imports required.

Base fixture: required nonempty string title. Extension: required integer count.
Nested fixture: required sample object with required integer age, closed.
Format fixture: required recorded string with date-time assertion.
Reference fixture: urn:huron:schema:label:1 points at nonempty string schema,
with SHA-256 of RFC8785 canonical document as an independently supplied pin.

Limits proposed for the probe: 64 KiB canonical bytes per document, 256 KiB bundle,
32 referenced resources, JSON depth 32, 4096 JSON nodes, 8 reference edges per path,
4096 expanded reference visits. A bounded iterative JSON walk precedes serialization,
schema checking and recursive reference traversal. Repeated aliases count toward
the budget. Format allowlist is only date-time; all other formats reject at compile.

## Source evidence and reuse

Inspected src/huron/core/raw/metadata.py, src/huron/schema/__init__.py,
src/huron/core/foundation/canonical.py, tests/unit/test_schema_loading.py,
tests/unit/test_schema_committed.py and tests/unit/conftest.py. Existing coverage
uses deterministic parametrization for required fields, unknown fields, bad format,
and loader path guards. Those tests concern packaged server envelopes, not additive
scientific schemas, so importing their envelope fixtures would test the wrong
contract. Reuse the validation/JCS approach and data-driven case style, not server
TestClient fixtures or mutable cached dictionaries. No tests or helpers modified.

## Primary API references consulted

- https://python-jsonschema.readthedocs.io/en/v4.26.0/referencing/
- https://referencing.readthedocs.io/en/stable/api/ (page identifies 0.37.0)
- https://json-schema.org/draft/2020-12/json-schema-validation

Official documentation fetches are not runtime schema retrieval. Runtime has no
HTTP/filesystem resolver. Restricted profile is not full Draft2020-12 support.

## Numeric correction contract (recorded before the fix)

2026-10-05, fix/prototype attempt 1, configured maximum/Max dispatch
64bcb4e0-aa3b-4f00-8f13-97002f6e22e7. This does not relabel the original Low run;
provider effort acceptance is not proven. Independent review 1 reported F1: both
submit seams admit metadata x=1e20, emit an unsafe Python-integer JCS token, then
pair identity crashes and replay rejects. A correctly pinned number resource with
minimum=1e20 also fails on copied-resource serialization with IntegerDomainError.
These are supported submission paths, not excluded arbitrary constructors/parsers.

Hypothesis for the correction: require every single-document admission to be a
value-preserving fixed point of rfc8785.dumps → ordinary json.loads → rfc8785.dumps.
Reject non-JCS or non-fixed-point inputs as Rejected("non_jcs", "") before returning
a bundle or pair. No float coercion, rounding, truncation, custom decoder or late
identity exception catch. Keep all 43 existing cases and every resource limit.
Run the same identity, ordinary-JSON revalidation, bundle reconstruction and frozen
retry assertions for every successful case, not just numeric regressions.

Proposed profile 2 is a bounded interoperability subset, NOT a shipped numeric
product choice or full RFC8785 support. With installed Python 3.12.4/rfc8785 0.1.4,
ints stay within ±(2**53-1). Floats must be finite and retain both numeric value and
canonical bytes after the standard decoder. In particular, integral floats with
2**53 <= abs(x) < 1e21 are rejected because their integer-form tokens decode outside
the library's integer domain. Finite exponent-form values at/above 1e21 are retained,
as are compatible fractions, minimum subnormals, maximum finite values and safe
integer-boundary floats. This non-contiguous float domain is deliberate evidence
about this Python encoder/decoder pair, not a claim that JCS forbids 1e20. Signed
zero follows RFC8785 and canonicalizes to 0; no additional numeric conversion occurs.
Normalize the backend JSON encoder's nonfinite-number ValueError during admission
to the same non_jcs rejection; no new hostile-parser/envelope claims.

Source/helper inspection: all eight existing prototype files, full phase001 and
phase004, current canonical.py/metadata.py, test_schema_loading.py,
test_schema_committed.py and unit/conftest.py. Extend corpus.case/supplied/pin and
the existing two-seam runner; no pytest fixtures are involved or unclear. New cases
cover both signs, safe-int boundaries in both Python representations, JCS exponent
transitions, fractions and finite extremes, numeric constraints in base/extension/
pinned resources, invalid finite constraints, nonfinite rejection and nested values.

Primary numeric sources checked without upgrading dependencies:

- https://www.rfc-editor.org/rfc/rfc8785.html (3.1, 3.2.2.3, Appendix B and D).
- https://github.com/trailofbits/rfc8785.py/tree/v0.1.4 (public dump/dumps and
  CanonicalizationError/IntegerDomainError/FloatDomainError API).
- Installed .venv/lib/python3.12/site-packages/rfc8785/{__init__,_impl}.py inspected
  read-only: integer guard ±(2**53-1); float encoder emits integer tokens below 1e21,
  rejects nonfinite values and uses exponent tokens at/above 1e21.

RFC8785 permits a broader binary64 range and recommends strings for greater
precision. This experiment does not adopt string-number schemas or a new decoder;
that product decision remains for profile approval/downstream planning. The simpler
admission fixed-point check keeps canonicalization ownership cohesive and adds one
bounded decode/re-encode; no performance guarantee is inferred.
