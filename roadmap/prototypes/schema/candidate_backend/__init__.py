"""Candidate backend caller seam; no HTTP framework, services or product imports."""

import json
from candidate_profile import ABSENT, Rejected, SchemaBundle, resolve_metadata


def submit(request, *, base=ABSENT):
    """Decode a JSON body and map field presence to the shared profile operation."""
    try:
        body = json.loads(json.dumps(request, allow_nan=False))
    except ValueError as error:
        raise Rejected("non_jcs") from error
    metadata = body["metadata"] if "metadata" in body else ABSENT
    selected = ABSENT
    if "bundle" in body:
        value = body["bundle"]
        selected = SchemaBundle.compile(base=value["base"],
                                        extension=value.get("extension", ABSENT),
                                        references=value.get("references", ()))
    return resolve_metadata(supplied=metadata, bundle=selected, base=base)
