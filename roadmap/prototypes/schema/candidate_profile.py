"""Throwaway restricted scientific metadata profile; no product imports or IO."""

from dataclasses import dataclass
import hashlib
import json
import re

import rfc8785
from jsonschema import Draft202012Validator, FormatChecker, SchemaError
from referencing import Registry
from referencing.exceptions import NoSuchResource
from referencing.jsonschema import DRAFT202012

DIALECT = "https://json-schema.org/draft/2020-12/schema"
PROFILE = "huron-restricted-metadata-probe-2"
ABSENT = object()
MAX_BYTES = 65536
MAX_BUNDLE = 262144
MAX_DEPTH = 32
MAX_NODES = 4096
MAX_REFS = 32
MAX_REF_DEPTH = 8
REF_NAME = re.compile(r"urn:huron:schema:[a-z][a-z0-9-]*:[1-9][0-9]*\Z")


def pointer(parts):
    """Render a normalized RFC6901 pointer (root is the empty string)."""
    return "".join("/" + str(p).replace("~", "~0").replace("/", "~1") for p in parts)


class Rejected(ValueError):
    """Stable code and location, without depending on validator prose."""

    def __init__(self, code, path=""):
        super().__init__(code, path)
        self.code, self.path = code, path


def canonical(value):
    """Admit bounded JSON only when ordinary decoding preserves value and JCS bytes."""
    stack = [(value, 0)]
    nodes = 0
    text_bytes = 0
    while stack:
        node, depth = stack.pop()
        nodes += 1
        if depth > MAX_DEPTH or nodes > MAX_NODES:
            raise Rejected("json_bound")
        if type(node) is dict:
            if any(type(k) is not str for k in node):
                raise Rejected("non_json")
            text_bytes += sum(len(k.encode("utf-8")) for k in node)
            stack.extend((v, depth + 1) for v in node.values())
        elif type(node) is list:
            stack.extend((v, depth + 1) for v in node)
        elif type(node) is str:
            text_bytes += len(node.encode("utf-8"))
        elif type(node) not in (int, float, bool, type(None)):
            raise Rejected("non_json")
        if text_bytes > MAX_BYTES:
            raise Rejected("size_bound")
    try:
        payload = rfc8785.dumps(value)
    except (ValueError, TypeError) as error:
        raise Rejected("non_jcs") from error
    if len(payload) > MAX_BYTES:
        raise Rejected("size_bound")
    # Some finite floats encode as integer tokens outside this encoder's integer
    # domain. Reject at admission, before copying schemas or returning metadata.
    # Re-encoding the bounded document also guards against lossy numeric changes;
    # compatible fractions and finite exponent-form values are not coerced away.
    try:
        decoded = json.loads(payload)
        replay = rfc8785.dumps(decoded)
    except (ValueError, TypeError) as error:
        raise Rejected("non_jcs") from error
    if decoded != value or replay != payload:
        raise Rejected("non_jcs")
    return payload


def digest(payload):
    """Return the SHA-256 of immutable canonical bytes."""
    return hashlib.sha256(payload).hexdigest()


def deny_retrieval(uri):
    """Reject every retrieval request without performing IO."""
    raise NoSuchResource(ref=uri)


def close_schema(schema, path=(), *, root=False):
    """Check the narrow allowlist and close every explicit object."""
    if type(schema) is not dict:
        raise Rejected("schema_shape", pointer(path))
    if "$schema" in schema and schema["$schema"] != DIALECT:
        raise Rejected("dialect", pointer(path + ("$schema",)))
    common = {"$schema", "type"}
    per_type = {
        "object": {"properties", "required", "additionalProperties"},
        "string": {"minLength", "maxLength", "format"},
        "integer": {"minimum", "maximum"},
        "number": {"minimum", "maximum"},
        "boolean": set(),
        "array": {"items", "minItems", "maxItems"},
    }
    if "$ref" in schema:
        if root:
            raise Rejected("root_ref", pointer(path))
        if set(schema) != {"$ref"}:
            raise Rejected("ref_siblings", pointer(path))
        if type(schema["$ref"]) is not str or not REF_NAME.fullmatch(schema["$ref"]):
            raise Rejected("ref_uri", pointer(path + ("$ref",)))
        return dict(schema)
    kind = schema.get("type")
    if type(kind) is not str or kind not in per_type or (root and kind != "object"):
        raise Rejected("schema_shape", pointer(path))
    unknown = set(schema) - common - per_type[kind]
    if unknown:
        raise Rejected("keyword", pointer(path + (sorted(unknown)[0],)))
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as error:
        raise Rejected("schema_shape", pointer(path)) from error
    result = dict(schema)
    if kind == "object":
        props = schema.get("properties")
        if type(props) is not dict:
            raise Rejected("schema_shape", pointer(path))
        if "additionalProperties" in schema and schema["additionalProperties"] is not False:
            raise Rejected("open_object", pointer(path))
        if not set(schema.get("required", [])) <= set(props):
            raise Rejected("required_scope", pointer(path + ("required",)))
        result["properties"] = {
            k: close_schema(v, path + ("properties", k)) for k, v in props.items()
        }
        result["additionalProperties"] = False
    if kind == "array":
        if "items" not in schema:
            raise Rejected("schema_shape", pointer(path))
        result["items"] = close_schema(schema["items"], path + ("items",))
    if "format" in schema and schema["format"] != "date-time":
        raise Rejected("format_policy", pointer(path + ("format",)))
    return result


def reference_edges(schema):
    """Collect references only from admitted schema positions."""
    stack = [schema]
    found = []
    while stack:
        node = stack.pop()
        if "$ref" in node:
            found.append(node["$ref"])
        stack.extend(node.get("properties", {}).values())
        if "items" in node:
            stack.append(node["items"])
    return found


def check_graph(roots, resources):
    """Reject cycles, missing pins and excessive expanded traversal before validation."""
    edges = {uri: reference_edges(doc) for uri, doc in resources.items()}
    starts = [ref for root in roots for ref in reference_edges(root)] + list(resources)
    stack = [(ref, ()) for ref in starts]
    visits = 0
    while stack:
        ref, ancestors = stack.pop()
        visits += 1
        if ref in ancestors:
            raise Rejected("ref_cycle")
        if len(ancestors) >= MAX_REF_DEPTH or visits > MAX_NODES:
            raise Rejected("ref_bound")
        if ref not in resources:
            raise Rejected("missing_ref")
        stack.extend((child, ancestors + (ref,)) for child in edges[ref])


@dataclass(frozen=True)
class SchemaBundle:
    """An admitted bundle owns immutable original and compiled schema bytes."""

    original: bytes
    compiled: bytes
    resources: tuple[tuple[str, bytes], ...]

    @classmethod
    def compile(cls, base, extension=ABSENT, references=()):
        """Freeze admitted version pins and compile disjoint property maps."""
        if len(references) > MAX_REFS:
            raise Rejected("ref_bound")
        base = json.loads(canonical(base))
        extension = {"type": "object", "properties": {}} if extension is ABSENT else extension
        extension = json.loads(canonical(extension))
        raw_resources = []
        resources = {}
        total = len(canonical(base)) + len(canonical(extension))
        for entry in references:
            uri, expected, document = entry["uri"], entry["sha256"], entry["document"]
            if type(uri) is not str or not REF_NAME.fullmatch(uri):
                raise Rejected("ref_uri")
            if uri in resources:
                raise Rejected("duplicate_ref")
            payload = canonical(document)
            total += len(payload)
            if total > MAX_BUNDLE:
                raise Rejected("bundle_bound")
            if digest(payload) != expected:
                raise Rejected("digest_mismatch")
            copied = json.loads(payload)
            resources[uri] = close_schema(copied)
            raw_resources.append({"uri": uri, "sha256": expected, "document": copied})
        left = close_schema(base, ("base",), root=True)
        right = close_schema(extension, ("extension",), root=True)
        if set(left["properties"]) & set(right["properties"]):
            raise Rejected("overlap", "/extension/properties")
        compiled = {
            "$schema": DIALECT,
            "type": "object",
            "properties": left["properties"] | right["properties"],
            "required": sorted(set(left.get("required", [])) | set(right.get("required", []))),
            "additionalProperties": False,
        }
        check_graph([compiled], resources)
        # Original aggregate may exceed the single-document limit, but every document
        # was bounded above and aggregate admission is independently bounded.
        original = rfc8785.dumps({"profile": PROFILE, "base": base, "extension": extension,
                                  "references": sorted(raw_resources, key=lambda r: r["uri"])})
        if len(original) > MAX_BUNDLE:
            raise Rejected("bundle_bound")
        return cls(original, rfc8785.dumps(compiled),
                   tuple((uri, rfc8785.dumps(doc)) for uri, doc in sorted(resources.items())))

    @property
    def sha256(self):
        """Identify the profile, original component documents and pinned references."""
        return digest(self.original)

    def validate(self, metadata):
        """Return frozen metadata bytes or a deterministic validation failure."""
        payload = canonical(metadata)
        metadata = json.loads(payload)
        registry = Registry(retrieve=deny_retrieval).with_resources(
            (uri, DRAFT202012.create_resource(json.loads(doc))) for uri, doc in self.resources
        )
        validator = Draft202012Validator(json.loads(self.compiled), registry=registry,
                                        format_checker=FormatChecker(formats=["date-time"]))
        errors = sorted(validator.iter_errors(metadata),
                        key=lambda e: (pointer(e.absolute_path), str(e.validator),
                                       pointer(e.absolute_schema_path)))
        if errors:
            error = errors[0]
            raise Rejected("validation:" + error.validator, pointer(error.absolute_path))
        return payload


@dataclass(frozen=True)
class MetadataPair:
    """Metadata and its validating bundle retain no caller-owned mutable objects."""

    scientific: bytes
    bundle: SchemaBundle

    @property
    def sha256(self):
        """Identify both scientific data and its exact bundle."""
        return digest(rfc8785.dumps({"metadata": json.loads(self.scientific),
                                    "bundle_sha256": self.bundle.sha256}))


def resolve_metadata(*, supplied=ABSENT, bundle=ABSENT, base=ABSENT):
    """Resolve explicit presence; latest is deliberately not an input."""
    if supplied is ABSENT:
        if bundle is not ABSENT:
            raise Rejected("schema_only")
        if base is ABSENT:
            raise Rejected("metadata_required")
        return base
    if supplied is None:
        raise Rejected("metadata_null", "/metadata")
    if bundle is ABSENT:
        raise Rejected("bundle_required", "/bundle")
    return MetadataPair(bundle.validate(supplied), bundle)


@dataclass(frozen=True)
class FrozenSubmission:
    """A model-only retry handle retains the already resolved pair."""

    pair: MetadataPair

    def retry(self):
        """Return the frozen pair without any schema registry lookup."""
        return self.pair
