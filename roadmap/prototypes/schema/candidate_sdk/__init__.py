"""Candidate SDK caller seam; not a built or shipped SDK distribution."""

from candidate_profile import ABSENT, SchemaBundle, resolve_metadata


def submit(request, *, base=ABSENT):
    """Preserve SDK keyword presence independently of metadata value."""
    bundle = ABSENT
    if "bundle" in request:
        spec = request["bundle"]
        bundle = SchemaBundle.compile(spec["base"], spec.get("extension", ABSENT),
                                      spec.get("references", ()))
    return resolve_metadata(supplied=request.get("metadata", ABSENT), bundle=bundle, base=base)
