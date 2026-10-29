"""Require admission-time rejection of numbers whose frozen JSON cannot be replayed."""

from copy import deepcopy
import json

import candidate_backend
import candidate_sdk
from candidate_profile import Rejected
from corpus import pin, supplied, with_ref


def main():
    """Report both public-seam counterexamples and fail if either escapes admission."""
    uri = "urn:huron:schema:numeric:1"
    requests = {
        "metadata": supplied({"x": 1e20}, {"type": "object", "properties": {
            "x": {"type": "number"}}, "required": ["x"]}),
        "pinned_minimum": {"metadata": {"title": 1e21}, "bundle": {
            "base": with_ref(uri), "references": [
                pin(uri, {"type": "number", "minimum": 1e20})]}},
    }
    failures = 0
    for caller in (candidate_sdk, candidate_backend):
        for name, request in requests.items():
            label = f"{caller.__name__}/{name}"
            try:
                pair = caller.submit(deepcopy(request))
            except Rejected as error:
                print(label, "admission", error.code, repr(error.path))
                assert (error.code, error.path) == ("non_jcs", "")
                continue
            except Exception as error:
                failures += 1
                print(label, "UNNORMALIZED admission exception", type(error).__name__)
                continue
            failures += 1
            print(label, "INVALID PAIR returned", repr(pair.scientific))
            for operation, invoke in (
                ("identity", lambda: pair.sha256),
                ("revalidation", lambda: pair.bundle.validate(json.loads(pair.scientific))),
            ):
                try:
                    invoke()
                except Exception as error:
                    detail = (error.code, error.path) if isinstance(error, Rejected) else ""
                    print(label, operation, type(error).__name__, detail)
                else:
                    print(label, operation, "returned")
    print(f"Admission counterexamples: {failures}/4 remain")
    raise SystemExit(bool(failures))


if __name__ == "__main__":
    main()
