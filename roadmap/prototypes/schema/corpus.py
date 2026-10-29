"""Fixed named inputs and expected outcomes, established before the first run."""

from copy import deepcopy
import hashlib
import math
import rfc8785

DIALECT = "https://json-schema.org/draft/2020-12/schema"
BASE = {"$schema": DIALECT, "type": "object", "properties": {
    "title": {"type": "string", "minLength": 1}}, "required": ["title"]}
EXT = {"type": "object", "properties": {"count": {"type": "integer"}},
       "required": ["count"]}
EMPTY = {"type": "object", "properties": {}}
NESTED = {"type": "object", "properties": {"sample": {
    "type": "object", "properties": {"age": {"type": "integer"}},
    "required": ["age"]}}, "required": ["sample"]}
FORMAT = {"type": "object", "properties": {"recorded": {
    "type": "string", "format": "date-time"}}, "required": ["recorded"]}


def pin(uri, document):
    """Build an input pin independently from the candidate digest helper."""
    return {"uri": uri, "document": document,
            "sha256": hashlib.sha256(rfc8785.dumps(document)).hexdigest()}


def with_ref(uri):
    """Make a required title field referring to a pinned resource."""
    return {"type": "object", "properties": {"title": {"$ref": uri}},
            "required": ["title"]}


LABEL = "urn:huron:schema:label:1"
REF_BUNDLE = {"base": with_ref(LABEL), "references": [
    pin(LABEL, {"type": "string", "minLength": 1})]}
BAD_PIN = deepcopy(REF_BUNDLE)
BAD_PIN["references"][0]["sha256"] = "0" * 64
CYCLE_A, CYCLE_B = "urn:huron:schema:a:1", "urn:huron:schema:b:1"
CYCLE = {"base": with_ref(CYCLE_A), "references": [
    pin(CYCLE_A, {"$ref": CYCLE_B}), pin(CYCLE_B, {"$ref": CYCLE_A})]}
CHAIN = [f"urn:huron:schema:chain:{n}" for n in range(1, 10)]
DEEP = {"base": with_ref(CHAIN[0]), "references": [
    pin(uri, {"$ref": CHAIN[n + 1]} if n < 8 else {"type": "string"})
    for n, uri in enumerate(CHAIN)]}


def case(name, request, expected="ok", path="", mode="ordinary"):
    """Keep explicit expected code and normalized location beside each input."""
    return {"name": name, "request": request, "expected": (expected, path), "mode": mode}


def supplied(metadata, base=BASE, extension=None):
    """Build request fixtures without conflating metadata null with omission."""
    bundle = {"base": deepcopy(base)}
    if extension is not None:
        bundle["extension"] = deepcopy(extension)
    return {"metadata": metadata, "bundle": bundle}


CASES = [
    case("01_valid_base", supplied({"title": "run"})),
    case("02_missing_base_required", supplied({}), "validation:required"),
    case("03_valid_additive_extension", supplied({"title": "run", "count": 2}, extension=EXT)),
    case("04_missing_extension_required", supplied({"title": "run"}, extension=EXT),
         "validation:required"),
    case("05_identical_property_overlap_rejected", supplied({"title": "run"}, extension=BASE),
         "overlap", "/extension/properties"),
    case("06_weakening_overlap_rejected", supplied({"title": ""}, extension={
        "type": "object", "properties": {"title": {"type": "string"}}}),
         "overlap", "/extension/properties"),
    case("07_unknown_field_rejected", supplied({"title": "run", "extra": True}),
         "validation:additionalProperties"),
    case("08_valid_nested_object", supplied({"sample": {"age": 2}}, NESTED)),
    case("09_invalid_nested_type", supplied({"sample": {"age": "two"}}, NESTED),
         "validation:type", "/sample/age"),
    case("10_nested_unknown_field", supplied({"sample": {"age": 2, "x": 0}}, NESTED),
         "validation:additionalProperties", "/sample"),
    case("11_valid_declared_format", supplied({"recorded": "2026-10-05T06:00:00Z"}, FORMAT)),
    case("12_invalid_declared_format", supplied({"recorded": "yesterday"}, FORMAT),
         "validation:format", "/recorded"),
    case("13_valid_pinned_local_ref", {"metadata": {"title": "run"}, "bundle": REF_BUNDLE}),
    case("14_missing_ref", {"metadata": {"title": "run"}, "bundle": {"base": with_ref(LABEL)}},
         "missing_ref"),
    case("15_digest_mismatch", {"metadata": {"title": "run"}, "bundle": BAD_PIN}, "digest_mismatch"),
    case("16_network_ref", supplied({"title": "run"}, with_ref("https://example.invalid/schema")),
         "ref_uri", "/base/properties/title/$ref"),
    case("17_ref_cycle", {"metadata": {"title": "run"}, "bundle": CYCLE}, "ref_cycle"),
    case("18_ref_depth_bound", {"metadata": {"title": "run"}, "bundle": DEEP}, "ref_bound"),
    case("19_unsupported_dialect", supplied({"title": "run"}, BASE | {"$schema": "draft-07"}),
         "dialect", "/base/$schema"),
    case("20_unsupported_keyword", supplied({"title": "run"}, BASE | {"allOf": []}),
         "keyword", "/base/allOf"),
    case("21_new_metadata_and_bundle", supplied({"title": "new"})),
    case("22_new_metadata_omission", {}, "metadata_required"),
    case("23_explicit_null", supplied(None), "metadata_null", "/metadata"),
    case("24_supplied_empty_evaluated_normally", supplied({}), "validation:required"),
    case("25_later_omission_inherits_exact_base_pair", {}, mode="inherit"),
    case("26_replacement_without_bundle", {"metadata": {"title": "replacement"}},
         "bundle_required", "/bundle", "with_base"),
    case("27_schema_only", {"bundle": {"base": BASE}}, "schema_only", mode="with_base"),
    case("28_latest_changed_does_not_change_inheritance", {}, mode="latest"),
    case("29_retry_retains_frozen_pair", supplied({"title": "frozen"}), mode="retry"),
    case("30_caller_mutation_cannot_change_frozen_content_digest", supplied({"sample": {"age": 2}},
         NESTED), mode="mutation"),
    case("31_unknown_format_rejected", supplied({"recorded": "anything"}, {
        "type": "object", "properties": {"recorded": {"type": "string", "format": "custom"}}}),
         "format_policy", "/base/properties/recorded/format"),
    case("32_schema_size_bound", supplied({}, {"type": "object", "properties": {
        "x" * 65537: {"type": "string"}}}), "size_bound"),
    case("33_empty_metadata_empty_schema", supplied({}, EMPTY)),
    case("34_nested_extension_overlap_rejected", supplied({"sample": {"age": 2}}, NESTED,
         {"type": "object", "properties": {"sample": {"type": "object", "properties": {
             "new": {"type": "string"}}}}}), "overlap", "/extension/properties"),
    case("35_extension_required_cannot_target_base", supplied({"title": "run"}, extension={
        "type": "object", "properties": {}, "required": ["title"]}),
         "required_scope", "/extension/required"),
    case("36_ref_siblings_rejected", supplied({"title": "run"}, {"type": "object", "properties": {
        "title": {"$ref": LABEL, "type": "string"}}}), "ref_siblings", "/base/properties/title"),
    case("37_unsafe_jcs_integer", supplied({"count": 2**53}, EXT), "non_jcs"),
    case("38_ref_validation_error_location", {"metadata": {"title": 2}, "bundle": REF_BUNDLE},
         "validation:type", "/title"),
    case("39_ref_caller_mutation_frozen", {"metadata": {"title": "run"}, "bundle": REF_BUNDLE},
         mode="ref_mutation"),
]

# Additional bounds fixed before the second run; no first-run expectations changed.
TOO_DEEP = "leaf"
for _ in range(34):
    TOO_DEEP = {"child": TOO_DEEP}
TOO_MANY_REFS = [pin(f"urn:huron:schema:many:{n}", {"type": "string"}) for n in range(1, 34)]
LARGE_REFS = [pin(f"urn:huron:schema:large:{n}", {"type": "object", "properties": {
    "k" * 60000: {"type": "string"}}}) for n in range(1, 6)]
CASES.extend([
    case("40_metadata_depth_bound", supplied(TOO_DEEP), "json_bound"),
    case("41_metadata_node_bound", supplied({"title": [0] * 4097}), "json_bound"),
    case("42_reference_count_bound", {"metadata": {}, "bundle": {
        "base": EMPTY, "references": TOO_MANY_REFS}}, "ref_bound"),
    case("43_aggregate_bundle_size_bound", {"metadata": {}, "bundle": {
        "base": EMPTY, "references": LARGE_REFS}}, "bundle_bound"),
])


def numeric_request(metadata, field, site="base"):
    """Place the same numeric field in a base, additive extension or pinned resource."""
    document = {"type": "object", "properties": {"x": field}, "required": ["x"]}
    if site == "base":
        return supplied({"x": metadata}, document)
    if site == "extension":
        return supplied({"x": metadata}, EMPTY, document)
    assert site == "reference"
    uri = "urn:huron:schema:numeric:1"
    try:
        entry = pin(uri, field)
    except rfc8785.CanonicalizationError:
        # Nonfinite/unsafe Python integers have no JCS pin: admission must reject
        # the document before checking this deliberately unusable placeholder.
        entry = {"uri": uri, "document": field, "sha256": "0" * 64}
    document["properties"]["x"] = {"$ref": uri}
    return {"metadata": {"x": metadata}, "bundle": {"base": document, "references": [entry]}}


# Fixed numeric expectations do not consult the candidate profile. Both Python
# numeric representations and both signs are exercised at the safe-integer edge.
NUMBERS = [("zero_int", 0, "ok"), ("zero_float", 0.0, "ok"), ("negative_zero", -0.0, "ok")]
for sign, sign_name in ((1, "positive"), (-1, "negative")):
    for name, value, expected in (
        ("inside_safe_int", 2**53 - 2, "ok"),
        ("last_safe_int", 2**53 - 1, "ok"),
        ("inside_safe_float", math.nextafter(float(2**53 - 1), 0), "ok"),
        ("last_safe_float", float(2**53 - 1), "ok"),
        ("first_unsafe_int", 2**53, "non_jcs"),
        ("first_unsafe_float", float(2**53), "non_jcs"),
        ("above_unsafe_int", 2**53 + 1, "non_jcs"),
        ("above_unsafe_float", math.nextafter(float(2**53), math.inf), "non_jcs"),
        ("large_integral_float", 1e16, "non_jcs"),
        ("huge_integral_float", 1e20, "non_jcs"),
        ("below_exponent_boundary", math.nextafter(1e21, 0), "non_jcs"),
        ("exponent_boundary", 1e21, "ok"),
        ("above_exponent_boundary", math.nextafter(1e21, math.inf), "ok"),
        ("avogadro", 6.02214076e23, "ok"),
        ("maximum_finite", float.fromhex("0x1.fffffffffffffp+1023"), "ok"),
        ("fraction", 0.125, "ok"),
        ("binary_approximation", 0.1, "ok"),
        ("large_fraction", 1424953923781206.25, "ok"),
        ("fraction_below_integer", math.nextafter(1.0, 0), "ok"),
        ("minimum_subnormal", 5e-324, "ok"),
        ("minimum_normal", float.fromhex("0x1p-1022"), "ok"),
        ("below_decimal_boundary", 1e-7, "ok"),
        ("decimal_boundary", 1e-6, "ok"),
    ):
        NUMBERS.append((f"{sign_name}_{name}", sign * value, expected))

for name, value, expected in NUMBERS:
    CASES.append(case(f"numeric_metadata_{name}", numeric_request(value, {"type": "number"}),
                      expected))
    for site in ("base", "extension", "reference"):
        for keyword in ("minimum", "maximum"):
            # A rejection is specifically about schema admission, not invalid data.
            metadata = value if expected == "ok" else 0
            CASES.append(case(f"numeric_{site}_{keyword}_{name}", numeric_request(
                metadata, {"type": "number", keyword: value}, site), expected))

for name, value in (("nan", math.nan), ("positive_infinity", math.inf),
                    ("negative_infinity", -math.inf)):
    CASES.append(case(f"numeric_metadata_{name}", numeric_request(value, {"type": "number"}),
                      "non_jcs"))
    for site in ("base", "extension", "reference"):
        for keyword in ("minimum", "maximum"):
            CASES.append(case(f"numeric_{site}_{keyword}_{name}", numeric_request(
                0, {"type": "number", keyword: value}, site), "non_jcs"))

for site in ("base", "extension", "reference"):
    for value, expected in ((0.125, "ok"), (-0.75, "validation:minimum"),
                            (0.75, "validation:maximum")):
        CASES.append(case(f"numeric_{site}_fractional_range_{value}", numeric_request(
            value, {"type": "number", "minimum": -0.5, "maximum": 0.5}, site),
            expected, "" if expected == "ok" else "/x"))
    for value, expected in ((0, "ok"), (-1, "validation:minimum"), (1, "validation:maximum")):
        CASES.append(case(f"numeric_{site}_integer_fractional_range_{value}", numeric_request(
            value, {"type": "integer", "minimum": -0.5, "maximum": 0.5}, site),
            expected, "" if expected == "ok" else "/x"))

for value, expected in ((0.125, "ok"), (1e30, "ok"), (-1e30, "ok"),
                        (1e20, "non_jcs"), (-1e20, "non_jcs")):
    CASES.append(case(f"numeric_nested_array_{value}", numeric_request(
        [{"value": value}], {"type": "array", "items": {"type": "object", "properties": {
            "value": {"type": "number"}}, "required": ["value"]}}), expected))
