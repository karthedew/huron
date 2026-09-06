"""Property tests pinning the invariants the pure catalog core is built on.

Generated inputs, rather than a handful of hand-picked examples, exercise nine
facts the rest of the system relies on without re-checking: that
:func:`~huron.pkg.catalog.paths.parse_revision_dir` inverts
:func:`~huron.pkg.catalog.paths.revision_dir` exactly; that
:func:`~huron.pkg.catalog.manifest.validate_manifest` catches every path
collision Unicode normalization and case folding can create, and separately
refuses every path whose NFC form differs from itself; that
:func:`~huron.pkg.catalog.manifest.canonical_bytes` does not depend on key
order and enforces the JCS-safe integer bound; that
:func:`~huron.pkg.catalog.ids.uuid7` produces well-formed identifiers whose
embedded timestamps never regress across calls; that every operation on
:class:`~huron.pkg.catalog.ingest.IngestSession`, including the per-file
:meth:`~huron.pkg.catalog.ingest.IngestSession.require` guard, only ever
lands on an edge of :data:`~huron.pkg.catalog.ingest.TRANSITIONS` and never
succeeds from a terminal state; that an
:class:`~huron.pkg.catalog.ingest.IngestFile`'s recorded parts never exceed
its plan and it completes only once every part has arrived; and that
:func:`~huron.pkg.catalog.ingest.compute_upload_plan` emits one entry per
manifest file that links only files identical to the parent's, with part
counts that cover every file's bytes exactly once.
"""

from __future__ import annotations

import itertools
import string
import unicodedata
from datetime import datetime, timedelta
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

import pytest
from hypothesis import assume, example, given, settings
from hypothesis import strategies as st

from huron.pkg.catalog.errors import (
    IllegalIngestTransition,
    IngestSessionExpired,
    PathCollision,
    PathRuleViolation,
)
from huron.pkg.catalog.ids import uuid7
from huron.pkg.catalog.ingest import (
    LEASE_TTL,
    PART_BYTES,
    TERMINAL_STATES,
    TRANSITIONS,
    FileState,
    IngestSession,
    IngestState,
    UploadAction,
    compute_upload_plan,
)
from huron.pkg.catalog.manifest import (
    MAX_SAFE_INT,
    Manifest,
    ManifestEntry,
    canonical_bytes,
    validate_manifest,
)
from huron.pkg.catalog.models import EntityRef
from huron.pkg.catalog.paths import (
    DATASET_SLUG_MAX,
    ORG_PROJECT_SLUG_MAX,
    RevisionPath,
    parse_revision_dir,
    revision_dir,
)

from .support import INGEST_OPERATION_TARGETS, ingest_file, ingest_session, run_ingest_operation

if TYPE_CHECKING:
    from uuid import UUID

pytestmark = pytest.mark.unit

_property = settings(deadline=None, max_examples=200)

_ROOT = PurePosixPath("/data")

_ALNUM = string.ascii_lowercase + string.digits
_ALNUM_OR_HYPHEN = _ALNUM + "-"


@st.composite
def _slugs(draw: st.DrawFn, min_size: int, max_size: int) -> str:
    """Build a slug of the shape the catalog's ``SLUG`` pattern accepts.

    Args:
        draw: The Hypothesis draw function.
        min_size: The shortest slug to build.
        max_size: The longest slug to build.

    Returns:
        A slug starting with a letter or digit, otherwise letters, digits and
        single hyphens, never containing ``--``.
    """
    length = draw(st.integers(min_value=min_size, max_value=max_size))
    characters = [draw(st.sampled_from(_ALNUM))]
    for _ in range(length - 1):
        previous = characters[-1]
        choices = _ALNUM if previous == "-" else _ALNUM_OR_HYPHEN
        characters.append(draw(st.sampled_from(choices)))
    return "".join(characters)


@given(
    org_slug=_slugs(2, ORG_PROJECT_SLUG_MAX),
    org_id=st.builds(uuid7),
    project_slug=_slugs(2, ORG_PROJECT_SLUG_MAX),
    project_id=st.builds(uuid7),
    dataset_slug=_slugs(2, DATASET_SLUG_MAX),
    dataset_id=st.builds(uuid7),
    revision_number=st.integers(min_value=1, max_value=999_999),
    revision_id=st.builds(uuid7),
)
@_property
def test_parse_revision_dir_recovers_exactly_what_revision_dir_encoded(
    org_slug: str,
    org_id: UUID,
    project_slug: str,
    project_id: UUID,
    dataset_slug: str,
    dataset_id: UUID,
    revision_number: int,
    revision_id: UUID,
) -> None:
    """Parsing a built revision directory returns the slugs, ids and numbers that built it."""
    organization = EntityRef(org_id, org_slug)
    project = EntityRef(project_id, project_slug)
    dataset = EntityRef(dataset_id, dataset_slug)

    path = revision_dir(_ROOT, organization, project, dataset, revision_number, revision_id)

    assert parse_revision_dir(_ROOT, path) == RevisionPath(
        org_slug,
        org_id,
        project_slug,
        project_id,
        dataset_slug,
        dataset_id,
        revision_number,
        revision_id,
    )


# Precomposed accented letters (é, É) are already stable under NFC, unlike a
# base letter followed by a combining accent, so paths built from this
# alphabet always pass validate_manifest_path's NFC check on their own merits
# and any collision found is genuinely the case-folding rule, not the NFC one.
_COLLISION_ALPHABET = string.ascii_lowercase + string.ascii_uppercase + "éÉ"


def _swapped(text: str, flips: list[bool]) -> str:
    """Return `text` with the case of each flipped letter toggled.

    Args:
        text: The characters to transform.
        flips: One flag per character in ``text``; ``True`` toggles the case
            of that character if it is a letter.

    Returns:
        The transformed string, the same length as ``text``.
    """
    return "".join(
        character.swapcase() if flip and character.isalpha() else character
        for character, flip in zip(text, flips, strict=True)
    )


@st.composite
def _casefold_collision_pair(draw: st.DrawFn) -> tuple[str, str]:
    """Build two distinct strings equal once NFC-normalized and case-folded.

    Args:
        draw: The Hypothesis draw function.

    Returns:
        Two different strings whose ``unicodedata.normalize("NFC",
        …).casefold()`` values coincide.
    """
    base = draw(st.text(alphabet=_COLLISION_ALPHABET, min_size=1, max_size=8))
    assume(any(character.isalpha() for character in base))
    flips = draw(st.lists(st.booleans(), min_size=len(base), max_size=len(base)))
    variant = _swapped(base, flips)
    assume(variant != base)
    return base, variant


@st.composite
def _pairwise_distinct_paths(draw: st.DrawFn, size: int) -> list[str]:
    """Build path segments whose NFC+casefold forms are pairwise distinct.

    Args:
        draw: The Hypothesis draw function.
        size: How many segments to build.

    Returns:
        ``size`` strings, each a randomly-cased rendering of one of ``size``
        labels that are pairwise distinct once case-folded.
    """
    labels = draw(
        st.sets(
            st.text(alphabet=_COLLISION_ALPHABET, min_size=1, max_size=8).map(str.casefold),
            min_size=size,
            max_size=size,
        )
    )
    rendered = []
    for label in labels:
        flips = draw(st.lists(st.booleans(), min_size=len(label), max_size=len(label)))
        rendered.append(_swapped(label, flips))
    return rendered


def _entries(path_segments: list[str]) -> list[ManifestEntry]:
    """Build manifest entries for the given payload-relative segments.

    Args:
        path_segments: The part of each path after ``payload/``.

    Returns:
        One valid :class:`ManifestEntry` per segment, sharing a fixed size
        and digest since neither participates in collision detection.
    """
    return [
        ManifestEntry(path=f"payload/{segment}", size=1024, sha256="0" * 64)
        for segment in path_segments
    ]


@given(pair=_casefold_collision_pair())
@_property
def test_validate_manifest_rejects_paths_equal_under_nfc_and_casefold(
    pair: tuple[str, str],
) -> None:
    """Two entries whose paths coincide once NFC-normalized and case-folded are refused."""
    first, second = pair

    with pytest.raises(PathCollision):
        validate_manifest(_entries([first, second]))


@given(path_segments=_pairwise_distinct_paths(size=3))
@_property
def test_validate_manifest_accepts_paths_pairwise_distinct_under_nfc_and_casefold(
    path_segments: list[str],
) -> None:
    """Entries whose paths stay pairwise distinct once NFC-normalized and case-folded all pass."""
    entries = _entries(path_segments)

    manifest = validate_manifest(entries)

    assert len(manifest.files) == len(entries)


def _json_scalars() -> st.SearchStrategy[object]:
    """Return a strategy for JSON scalars within the JCS-exact integer range.

    Returns:
        Strings, booleans, floats and integers no larger in magnitude than
        :data:`MAX_SAFE_INT`.
    """
    return st.one_of(
        st.text(max_size=8),
        st.booleans(),
        st.integers(min_value=-MAX_SAFE_INT, max_value=MAX_SAFE_INT),
        st.floats(allow_nan=False, allow_infinity=False, width=32),
    )


def _json_values(depth: int) -> st.SearchStrategy[object]:
    """Return a strategy for JSON-compatible values nested up to `depth` levels deeper.

    Args:
        depth: How many further levels of list or mapping nesting to allow.

    Returns:
        Scalars at ``depth`` 0, otherwise also lists and mappings of
        recursively shallower values.
    """
    if depth <= 0:
        return _json_scalars()
    nested = _json_values(depth - 1)
    return st.one_of(
        _json_scalars(),
        st.lists(nested, max_size=4),
        st.dictionaries(st.text(min_size=1, max_size=6), nested, max_size=4),
    )


_documents = st.dictionaries(
    st.text(min_size=1, max_size=6), _json_values(2), min_size=1, max_size=5
)


def _reordered(value: object) -> object:
    """Rebuild every mapping inside `value` with its keys in reverse order.

    Args:
        value: A JSON-compatible value, possibly nested.

    Returns:
        An equal value in which every ``dict``'s iteration order is reversed
        from the original, recursively.
    """
    if isinstance(value, dict):
        return {key: _reordered(value[key]) for key in reversed(list(value))}
    if isinstance(value, list):
        return [_reordered(item) for item in value]
    return value


@given(document=_documents)
@_property
def test_canonical_bytes_does_not_depend_on_mapping_key_order(
    document: dict[str, object],
) -> None:
    """Reversing every nested mapping's key order leaves the canonical bytes unchanged."""
    assert canonical_bytes(document) == canonical_bytes(_reordered(document))


@given(document=_documents)
@example(document={"n": MAX_SAFE_INT})
@example(document={"n": -MAX_SAFE_INT})
@_property
def test_canonical_bytes_accepts_every_integer_within_the_safe_range(
    document: dict[str, object],
) -> None:
    """Every integer within the JCS-safe magnitude, at any depth, serializes without error."""
    canonical_bytes(document)


@st.composite
def _document_with_one_unsafe_integer(draw: st.DrawFn) -> dict[str, object]:
    """Embed one integer beyond the JCS-safe magnitude somewhere in a generated document.

    Args:
        draw: The Hypothesis draw function.

    Returns:
        A document built from :data:`_documents` with one extra key whose
        value is, is a list containing, or is a nested mapping containing,
        an integer whose magnitude exceeds :data:`MAX_SAFE_INT`.
    """
    base = draw(_documents)
    magnitude = MAX_SAFE_INT + 1 + draw(st.integers(min_value=0, max_value=10**6))
    unsafe = magnitude if draw(st.booleans()) else -magnitude
    placement = draw(st.sampled_from(["top_level", "inside_a_list", "inside_a_mapping"]))
    document = dict(base)
    if placement == "top_level":
        document["unsafe"] = unsafe
    elif placement == "inside_a_list":
        document["unsafe"] = [unsafe]
    else:
        document["unsafe"] = {"nested": unsafe}
    return document


@given(document=_document_with_one_unsafe_integer())
@example(document={"unsafe": MAX_SAFE_INT + 1})
@example(document={"unsafe": -(MAX_SAFE_INT + 1)})
@_property
def test_canonical_bytes_refuses_any_integer_beyond_the_safe_range(
    document: dict[str, object],
) -> None:
    """An integer beyond the JCS-safe magnitude, at any depth, is refused."""
    with pytest.raises(ValueError, match="JCS safe range"):
        canonical_bytes(document)


@given(call_count=st.integers(min_value=2, max_value=50))
@_property
def test_uuid7_calls_carry_the_correct_bits_and_their_timestamps_never_go_backwards(
    call_count: int,
) -> None:
    """Every uuid7() is version 7 with RFC 9562 variant bits, and its timestamp never regresses.

    Two ids minted within the same millisecond carry independently-random
    bits below the timestamp, so only the 48-bit timestamp itself — not the
    full 128-bit integer — is guaranteed to hold still or advance from one
    call to the next.
    """
    ids = [uuid7() for _ in range(call_count)]

    for value in ids:
        assert value.version == 7
        assert (value.int >> 62) & 0b11 == 0b10

    timestamps = [value.int >> 80 for value in ids]
    assert all(earlier <= later for earlier, later in itertools.pairwise(timestamps))


_NAMED_OPERATIONS: tuple[str, ...] = (*INGEST_OPERATION_TARGETS, "renew", "expire")
_FENCED_UNCONDITIONALLY = frozenset({"open", "verify"})


def _predict_named_operation(
    session: IngestSession, operation: str, *, now: datetime
) -> IngestState | type[Exception]:
    """Predict ``operation``'s outcome from the transition table and the documented lease rule.

    Args:
        session: The session ``operation`` would run against.
        operation: One of :data:`_NAMED_OPERATIONS`.
        now: The instant the call would judge the lease against.

    Returns:
        The state the session should land on, or the exception type the
        call should raise instead.
    """
    state = session.state
    if operation == "renew":
        if state in TERMINAL_STATES or now >= session.lease.expires_at:
            return IngestSessionExpired
        return state
    if operation == "expire":
        if now < session.lease.expires_at:
            return ValueError
        if IngestState.ABORTED not in TRANSITIONS[state]:
            return IllegalIngestTransition
        return IngestState.ABORTED
    target = INGEST_OPERATION_TARGETS[operation]
    fences = operation in _FENCED_UNCONDITIONALLY or (
        operation == "begin_commit" and state is not IngestState.COMMITTING
    )
    if fences and state not in TERMINAL_STATES and now >= session.lease.expires_at:
        return IngestSessionExpired
    if target not in TRANSITIONS[state]:
        return IllegalIngestTransition
    return target


def _predict_require(
    session: IngestSession, required: IngestState, *, now: datetime
) -> type[Exception] | None:
    """Predict ``require``'s outcome from its documented lease and state-equality guards.

    Args:
        session: The session ``require`` would run against.
        required: The state the call demands the session be in.
        now: The instant the call would judge the lease against.

    Returns:
        The exception type the call should raise, or None if it should
        succeed and leave the session unchanged.
    """
    if session.state not in TERMINAL_STATES and now >= session.lease.expires_at:
        return IngestSessionExpired
    if session.state is not required:
        return IllegalIngestTransition
    return None


@given(
    initial_state=st.sampled_from(list(IngestState)),
    steps=st.lists(
        st.tuples(
            st.sampled_from(_NAMED_OPERATIONS),
            st.integers(min_value=-7200, max_value=7200),
            st.sampled_from(list(IngestState)),
        ),
        min_size=1,
        max_size=8,
    ),
)
@_property
def test_ingest_operations_never_leave_the_transition_table(
    initial_state: IngestState, steps: list[tuple[str, int, IngestState]]
) -> None:
    """Every operation and ``require`` land on a table edge or raise the documented error."""
    session = ingest_session(initial_state, expires_in=timedelta(hours=1))

    for operation, offset_seconds, required_state in steps:
        now = session.lease.expires_at + timedelta(seconds=offset_seconds)

        require_prediction = _predict_require(session, required_state, now=now)
        if require_prediction is None:
            assert session.require(required_state, now=now) is None
        else:
            with pytest.raises(require_prediction):
                session.require(required_state, now=now)

        prediction = _predict_named_operation(session, operation, now=now)

        if isinstance(prediction, type):
            with pytest.raises(prediction):
                run_ingest_operation(session, operation, now=now)
            continue

        before = session
        session = run_ingest_operation(session, operation, now=now)
        assert session.state is prediction
        if operation == "renew":
            assert session.etag == before.etag
            assert session.lease.expires_at == now + LEASE_TTL
        else:
            assert session.etag == before.etag + 1


@given(
    part_count=st.integers(min_value=1, max_value=20),
    guesses=st.lists(st.integers(min_value=-2, max_value=22), max_size=30),
)
@_property
def test_ingest_file_parts_are_a_subset_of_the_plan_and_complete_only_when_full(
    part_count: int, guesses: list[int]
) -> None:
    """Recorded parts never exceed the plan, and completion succeeds only once every part is in."""
    file = ingest_file(size=part_count, part_count=part_count)
    full = frozenset(range(1, part_count + 1))

    for guess in guesses:
        if 1 <= guess <= part_count:
            file = file.part_received(guess)
        else:
            with pytest.raises(ValueError):
                file.part_received(guess)

        assert file.completed_parts <= full
        assert file.received == (file.completed_parts == full)

    if file.received:
        completed = file.completed(observed_size=file.size, observed_sha256=file.expected_sha256)
        assert completed.state is FileState.COMPLETE
    else:
        with pytest.raises(IllegalIngestTransition):
            file.completed(observed_size=file.size, observed_sha256=file.expected_sha256)


_UPLOAD_PLAN_PATHS = tuple(f"payload/f{i}" for i in range(6))
_UPLOAD_PLAN_SIZES = (0, 1, 2, 3)
_UPLOAD_PLAN_DIGESTS = ("a" * 64, "b" * 64, "c" * 64)
_HASH_ALGORITHMS = ("sha256", "sha512")


@st.composite
def _upload_plan_manifest(draw: st.DrawFn) -> Manifest:
    """Build a manifest whose entries are drawn from a small shared pool of paths.

    Args:
        draw: The Hypothesis draw function.

    Returns:
        A manifest over a random subset of :data:`_UPLOAD_PLAN_PATHS`, each
        entry's size and digest drawn from small pools so that two
        independently drawn manifests collide with some regularity.
    """
    paths = draw(
        st.lists(
            st.sampled_from(_UPLOAD_PLAN_PATHS),
            min_size=1,
            max_size=len(_UPLOAD_PLAN_PATHS),
            unique=True,
        )
    )
    entries = tuple(
        ManifestEntry(
            path=path,
            size=draw(st.sampled_from(_UPLOAD_PLAN_SIZES)),
            sha256=draw(st.sampled_from(_UPLOAD_PLAN_DIGESTS)),
        )
        for path in paths
    )
    return Manifest(entries, hash_algorithm=draw(st.sampled_from(_HASH_ALGORITHMS)))


@given(manifest=_upload_plan_manifest(), parent=st.none() | _upload_plan_manifest())
@_property
def test_upload_plan_is_one_entry_per_file_in_manifest_order_and_links_only_identical_entries(
    manifest: Manifest, parent: Manifest | None
) -> None:
    """The plan has one entry per manifest file, in order, linking only identical parent files."""
    plan = compute_upload_plan(manifest, parent)

    assert [entry.file for entry in plan] == list(manifest.files)

    parent_by_path = (
        {entry.path: entry for entry in parent.files}
        if parent is not None and parent.hash_algorithm == manifest.hash_algorithm
        else {}
    )
    for entry in plan:
        counterpart = parent_by_path.get(entry.file.path)
        should_hardlink = (
            counterpart is not None
            and counterpart.size == entry.file.size
            and counterpart.sha256 == entry.file.sha256
        )
        assert (entry.action is UploadAction.HARDLINK) == should_hardlink


@given(
    size=st.integers(min_value=0, max_value=10**12),
    part_bytes=st.integers(min_value=1, max_value=10**9),
)
@example(size=0, part_bytes=PART_BYTES)
@example(size=1, part_bytes=PART_BYTES)
@example(size=PART_BYTES, part_bytes=PART_BYTES)
@example(size=PART_BYTES + 1, part_bytes=PART_BYTES)
@example(size=9 * 1024**3, part_bytes=PART_BYTES)
@_property
def test_upload_plan_part_counts_cover_every_byte_exactly_once(size: int, part_bytes: int) -> None:
    """Every upload's parts, at any part size, cover the file's bytes exactly once with no gap.

    The bound holds for sizes up to a terabyte and part sizes down to one
    byte, so the part count itself can reach the trillions; the proof stays
    arithmetic rather than counting or summing individual parts, which
    would allocate proportionally to that count.
    """
    manifest = Manifest((ManifestEntry(path="payload/a.bin", size=size, sha256="a" * 64),))

    plan = compute_upload_plan(manifest, part_bytes=part_bytes)

    part_count = plan[0].part_count
    covered = max(size, 1)
    assert (part_count - 1) * part_bytes < covered <= part_count * part_bytes

    last_part_length = covered - (part_count - 1) * part_bytes
    assert 0 < last_part_length <= part_bytes

    if size == 0:
        assert part_count == 1


_PRECOMPOSED_LETTERS = "áéíóúñÁÉÍÓÚÑàèìòùÀÈÌÒÙâêîôûÂÊÎÔÛäëïöüÄËÏÖÜçÇ"
_PATH_SEGMENT_ALPHABET = string.ascii_lowercase + string.digits + "_-."


@st.composite
def _non_nfc_manifest_paths(draw: st.DrawFn) -> str:
    """Build a payload path containing one canonically decomposed accented letter.

    Args:
        draw: The Hypothesis draw function.

    Returns:
        A path beginning with ``payload/`` whose NFC form differs from
        itself, because it embeds a base letter followed by a combining
        mark instead of the precomposed character.
    """
    prefix = draw(st.text(alphabet=_PATH_SEGMENT_ALPHABET, max_size=8))
    suffix = draw(st.text(alphabet=_PATH_SEGMENT_ALPHABET, max_size=8))
    decomposed = unicodedata.normalize("NFD", draw(st.sampled_from(_PRECOMPOSED_LETTERS)))
    return f"payload/{prefix}{decomposed}{suffix}"


@given(path=_non_nfc_manifest_paths())
@_property
def test_validate_manifest_refuses_every_non_nfc_path(path: str) -> None:
    """A manifest path whose NFC form differs from itself is refused as PATH_NOT_NFC."""
    with pytest.raises(PathRuleViolation) as excinfo:
        validate_manifest([ManifestEntry(path=path, size=0, sha256="0" * 64)])

    assert excinfo.value.code == "PATH_NOT_NFC"
    assert excinfo.value.context == {"path": path}
