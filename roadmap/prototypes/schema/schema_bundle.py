"""Reproduce the isolated restricted-schema experiment; writes no files."""

from copy import deepcopy
import hashlib
import importlib.metadata
import json
import socket
from unittest.mock import patch

from jsonschema import Draft202012Validator
import rfc8785

import candidate_backend
import candidate_sdk
from candidate_profile import ABSENT, FrozenSubmission, Rejected, SchemaBundle
from corpus import BASE, CASES, EXT, supplied


def assert_usable_pair(pair):
    """Every admitted pair has usable identity, frozen retry and ordinary-JSON replay."""
    metadata = json.loads(pair.scientific)
    assert rfc8785.dumps(metadata) == pair.scientific
    assert pair.bundle.validate(metadata) == pair.scientific
    expected_digest = hashlib.sha256(rfc8785.dumps({
        "metadata": metadata, "bundle_sha256": pair.bundle.sha256})).hexdigest()
    assert pair.sha256 == expected_digest
    assert pair.bundle.sha256 == hashlib.sha256(pair.bundle.original).hexdigest()
    for document in (pair.bundle.original, pair.bundle.compiled,
                     *(doc for _, doc in pair.bundle.resources)):
        assert rfc8785.dumps(json.loads(document)) == document
    original = json.loads(pair.bundle.original)
    rebuilt = SchemaBundle.compile(original["base"], original["extension"], original["references"])
    assert rebuilt == pair.bundle
    assert rebuilt.validate(metadata) == pair.scientific
    frozen = FrozenSubmission(pair)
    assert frozen.retry() is pair
    assert frozen.retry().sha256 == expected_digest
    assert frozen.retry().bundle.validate(json.loads(frozen.retry().scientific)) == pair.scientific


def run_case(seam, case):
    """Exercise one public caller and compare observable frozen values or failures."""
    request = deepcopy(case["request"])
    mode = case["mode"]
    base = ABSENT
    if mode in {"inherit", "with_base", "latest"}:
        base = seam(supplied({"title": "pinned"}))
        assert_usable_pair(base)
    if mode == "latest":
        latest = seam(supplied({"title": "new", "count": 99}, extension=EXT))
        assert_usable_pair(latest)
        assert latest.bundle.sha256 != base.bundle.sha256
    try:
        pair = seam(request, base=base)
    except Rejected as error:
        return (error.code, error.path), None
    # Only submit-time rejection counts as an expected failure. A late Rejected
    # or library exception in these postconditions must fail the whole run.
    assert_usable_pair(pair)
    if "metadata" in request:
        assert json.loads(pair.scientific) == request["metadata"]
    original = json.loads(pair.bundle.original)
    replay = seam({"metadata": json.loads(pair.scientific), "bundle": {
        "base": original["base"], "extension": original["extension"],
        "references": original["references"]}})
    assert_usable_pair(replay)
    assert replay == pair and replay.sha256 == pair.sha256
    if mode in {"inherit", "latest"}:
        assert pair is base
        assert pair.scientific == b'{"title":"pinned"}'
    if mode == "retry":
        frozen = FrozenSubmission(pair)
        before = (pair.scientific, pair.bundle.original, pair.sha256)
        latest = seam(supplied({"title": "new", "count": 99}, extension=EXT))
        assert_usable_pair(latest)
        request["metadata"]["title"] = "caller changed"
        assert latest.bundle.sha256 != frozen.retry().bundle.sha256
        assert frozen.retry() is pair
        assert (pair.scientific, pair.bundle.original, pair.sha256) == before
    if mode in {"mutation", "ref_mutation"}:
        before = (pair.scientific, pair.bundle.original, pair.bundle.compiled,
                  pair.bundle.resources, pair.sha256)
        if mode == "mutation":
            request["metadata"]["sample"]["age"] = "mutated"
            request["bundle"]["base"]["properties"]["sample"]["properties"].clear()
        else:
            request["bundle"]["references"][0]["document"]["type"] = "integer"
            request["bundle"]["references"][0]["sha256"] = "f" * 64
        view = json.loads(pair.scientific)
        view.clear()
        assert (pair.scientific, pair.bundle.original, pair.bundle.compiled,
                pair.bundle.resources, pair.sha256) == before
        assert_usable_pair(pair)
    return ("ok", ""), pair.sha256


def no_network(*args, **kwargs):
    """Make any accidental network attempt an immediate hard test failure."""
    raise AssertionError("runtime network IO forbidden")


def main():
    """Run every fixed case at both independently mapped candidate callers."""
    print("NON-PRODUCTION isolated prototype; self-check, not independent qualification")
    print("versions", {name: importlib.metadata.version(name)
                       for name in ("jsonschema", "referencing", "rfc8785")})
    assert len(CASES) >= 30 and len({c["name"] for c in CASES}) == len(CASES)
    with patch.object(socket.socket, "connect", no_network), patch.object(
        socket, "create_connection", no_network
    ), patch.object(socket, "getaddrinfo", no_network):
        for case in CASES:
            sdk = run_case(candidate_sdk.submit, case)
            backend = run_case(candidate_backend.submit, case)
            assert sdk[0] == case["expected"], (case["name"], "sdk", sdk, case["expected"])
            assert backend[0] == case["expected"], (case["name"], "backend", backend, case["expected"])
            assert sdk == backend, (case["name"], "seam disagreement", sdk, backend)
            print(case["name"], json.dumps({"code": sdk[0][0], "path": sdk[0][1]}), "both-seams MATCH")
        naive = {"allOf": [BASE | {"additionalProperties": False}, EXT]}
        errors = list(Draft202012Validator(naive).iter_errors({"title": "run", "count": 2}))
        assert any(e.validator == "additionalProperties" for e in errors)
        print("COUNTEREXAMPLE: naive closed-base allOf rejects valid additive count")
    print(f"RESULT: {len(CASES)}/{len(CASES)} cases at each seam; {2 * len(CASES)} expected outcomes; "
          "acceptance, normalized error locations and successful pair digests agree; "
          "every success checked for identity, frozen retry, revalidation and reconstruction")
    print("Runtime schema retrieval: registry deny callback; socket/DNS guards active; no IO attempted")


if __name__ == "__main__":
    main()
