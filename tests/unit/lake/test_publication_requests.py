"""Commit requests: their rules, the digest of their body, their outcomes and their errors."""

import unicodedata
import uuid
from dataclasses import replace
from typing import Any

import pytest

from huron.core.lake.files.errors import CommitInvalid, CommitTooLarge
from huron.core.lake.publications.errors import (
    CollectionBusy,
    CommitRequestNotFound,
    RequestIdConflict,
)
from huron.core.lake.publications.models import (
    MAX_BASE_VERSION,
    MAX_ENTRIES,
    CommitAdd,
    CommitEntry,
    CommitOutcome,
    CommitRequest,
    CommitState,
    EntryAction,
    EntryTarget,
    Refusal,
    Resolution,
)
from tests.support.clock import START

SHA = "a" * 64
REQUEST_ID = uuid.UUID("0190d5a4-0000-7000-8000-000000000001")
COLLECTION_ID = uuid.UUID("0190d5a4-0000-7000-8000-000000000002")
UPLOAD_ID = uuid.UUID("0190d5a4-0000-7000-8000-000000000003")
OTHER_UPLOAD_ID = uuid.UUID("0190d5a4-0000-7000-8000-000000000004")


def add(rel_path: str, upload_id: uuid.UUID = UPLOAD_ID, size: int = 4) -> CommitAdd:
    return CommitAdd(rel_path, size, SHA, upload_id)


def request(adds: tuple[CommitAdd, ...] = (), removes: tuple[str, ...] = ()) -> CommitRequest:
    return CommitRequest(REQUEST_ID, COLLECTION_ID, 3, adds, removes, "host1", "first run")


BASE = request(
    (add("a.txt"), add("b/c.txt", OTHER_UPLOAD_ID)),
    ("old/one.txt", "old/two.txt"),
)


def test_the_digest_does_not_depend_on_the_order_of_the_entries() -> None:
    reordered = replace(
        BASE,
        adds=tuple(reversed(BASE.adds)),
        removes=tuple(reversed(BASE.removes)),
    )
    assert reordered.digest() == BASE.digest()
    assert len(BASE.digest()) == 64


@pytest.mark.parametrize(
    "changes",
    [
        pytest.param({"request_id": uuid.uuid4()}, id="request_id"),
        pytest.param({"collection_id": uuid.uuid4()}, id="collection_id"),
        pytest.param({"base_version": 4}, id="base_version"),
        pytest.param({"host": "host2"}, id="host"),
        pytest.param({"message": None}, id="message"),
        pytest.param({"removes": ("old/one.txt",)}, id="removes"),
        pytest.param({"removes": ("old/one.txt", "old/Two.txt")}, id="remove spelling"),
        pytest.param({"adds": (add("a.txt"),)}, id="adds"),
        pytest.param({"adds": (add("A.txt"), BASE.adds[1])}, id="add spelling"),
        pytest.param({"adds": (add("a.txt", size=5), BASE.adds[1])}, id="add size"),
        pytest.param(
            {"adds": (replace(add("a.txt"), sha256="b" * 64), BASE.adds[1])}, id="add sha256"
        ),
        pytest.param({"adds": (add("a.txt", OTHER_UPLOAD_ID), add("b/c.txt"))}, id="add upload_id"),
    ],
)
def test_a_changed_field_changes_the_digest(changes: dict[str, Any]) -> None:
    assert replace(BASE, **changes).digest() != BASE.digest()


def test_a_request_of_the_maximum_size_is_accepted() -> None:
    adds = tuple(add(f"d/{n}.txt", uuid.UUID(int=n)) for n in range(MAX_ENTRIES // 2))
    removes = tuple(f"r/{n}.txt" for n in range(MAX_ENTRIES // 2))
    made = request(adds, removes)
    assert len(made.adds) + len(made.removes) == MAX_ENTRIES == 10_000


def test_a_request_with_one_entry_too_many_is_refused() -> None:
    adds = tuple(add(f"d/{n}.txt") for n in range(MAX_ENTRIES // 2))
    removes = tuple(f"r/{n}.txt" for n in range(MAX_ENTRIES // 2 + 1))
    with pytest.raises(CommitTooLarge) as caught:
        request(adds, removes)
    assert caught.value.context == {"entries": 10_001, "maximum": 10_000}


@pytest.mark.parametrize("base_version", [0, MAX_BASE_VERSION])
def test_a_base_version_at_the_bounds_of_the_column_is_accepted(base_version: int) -> None:
    assert replace(BASE, base_version=base_version).base_version == base_version


@pytest.mark.parametrize("base_version", [-1, MAX_BASE_VERSION + 1])
def test_a_base_version_outside_the_column_is_refused(base_version: int) -> None:
    with pytest.raises(CommitInvalid) as caught:
        replace(BASE, base_version=base_version)
    assert caught.value.context == {"base_version": base_version, "maximum": 2**31 - 1}
    assert caught.value.message == "the base_version must be from 0 to 2147483647"


def test_two_adds_that_name_one_upload_are_refused() -> None:
    with pytest.raises(CommitInvalid) as caught:
        request((add("a.txt"), add("b.txt")))
    assert caught.value.context == {
        "rel_path": "b.txt",
        "other": "a.txt",
        "upload_id": str(UPLOAD_ID),
    }


def test_an_entry_target_has_no_old_inode_and_no_source_by_default() -> None:
    target = EntryTarget(CommitEntry(0, EntryAction.MAKE_DIRECTORY, "d"), "helio/c/n/x/d")
    assert (target.old_inode, target.source) == (None, None)


def test_an_operator_can_retry_or_abandon_a_request() -> None:
    assert [str(each) for each in Resolution] == ["retry", "abandon"]


def test_an_empty_request_is_accepted() -> None:
    made = request()
    assert (made.adds, made.removes) == ((), ())


@pytest.mark.parametrize(
    ("adds", "removes"),
    [
        pytest.param(("Straße.txt", "STRASSE.txt"), (), id="adds folded to one key"),
        pytest.param(("Å/x.txt",), ("å/X.txt",), id="add and remove with one key"),
        pytest.param((), ("dir/a.txt", "DIR/A.TXT"), id="removes with one key"),
    ],
)
def test_two_paths_with_one_key_after_nfc_and_case_folding_are_refused(
    adds: tuple[str, ...], removes: tuple[str, ...]
) -> None:
    uploads = (UPLOAD_ID, OTHER_UPLOAD_ID)
    with pytest.raises(CommitInvalid) as caught:
        request(
            tuple(add(path, upload) for path, upload in zip(adds, uploads, strict=False)), removes
        )
    assert caught.value.message == "a path appears twice in the commit"


def test_a_path_that_is_not_in_nfc_is_refused() -> None:
    decomposed = unicodedata.normalize("NFD", "café.txt")
    with pytest.raises(CommitInvalid) as caught:
        request((add(decomposed),))
    assert caught.value.context == {"rel_path": decomposed, "rule": "rel_path_nfc"}


def test_a_remove_that_is_not_a_valid_path_is_refused() -> None:
    with pytest.raises(CommitInvalid) as caught:
        request(removes=("../escape.txt",))
    assert caught.value.context["rule"] == "rel_path_separator"


def test_an_add_with_a_negative_size_is_refused() -> None:
    with pytest.raises(CommitInvalid) as caught:
        request((add("a.txt", size=-1),))
    assert caught.value.context == {"rel_path": "a.txt", "size": -1}


@pytest.mark.parametrize("sha256", ["A" * 64, "a" * 63, "g" * 64, ""])
def test_an_add_without_a_lowercase_hexadecimal_sha256_is_refused(sha256: str) -> None:
    with pytest.raises(CommitInvalid) as caught:
        request((replace(add("a.txt"), sha256=sha256),))
    assert caught.value.context == {"rel_path": "a.txt", "sha256": sha256}


def test_an_add_of_zero_bytes_is_accepted() -> None:
    assert request((add("empty.txt", size=0),)).adds[0].size == 0


def test_an_add_renders_its_fields_as_a_document() -> None:
    assert add("a.txt").canonical() == {
        "rel_path": "a.txt",
        "size": 4,
        "sha256": SHA,
        "upload_id": str(UPLOAD_ID),
    }


def test_an_entry_is_not_done_and_names_no_upload_by_default() -> None:
    entry = CommitEntry(0, EntryAction.MAKE_DIRECTORY, "dir")
    assert (entry.upload_id, entry.done_at) == (None, None)


def test_a_refusal_keeps_the_code_detail_and_context_of_its_error() -> None:
    refusal = Refusal.of(CollectionBusy(COLLECTION_ID))
    assert refusal == Refusal(
        "COLLECTION_BUSY",
        "the collection has a pending commit. Wait until that commit ends."
        " A new commit needs a new request ID",
        {"collection_id": str(COLLECTION_ID)},
    )
    assert refusal.as_dict() == {
        "code": "COLLECTION_BUSY",
        "detail": refusal.detail,
        "context": {"collection_id": str(COLLECTION_ID)},
    }


def outcome(state: CommitState, **fields: Any) -> CommitOutcome:
    return CommitOutcome(
        id=uuid.uuid4(),
        subject="alice",
        request_id=REQUEST_ID,
        collection_id=COLLECTION_ID,
        body_digest=BASE.digest(),
        base_version=3,
        host="host1",
        message=None,
        state=state,
        created_at=START,
        updated_at=START,
        **fields,
    )


@pytest.mark.parametrize(
    ("state", "pending"),
    [
        (CommitState.REJECTED, False),
        (CommitState.ACCEPTED, True),
        (CommitState.BLOCKED, True),
        (CommitState.SUCCEEDED, False),
        (CommitState.ABANDONED, False),
    ],
)
def test_only_an_accepted_or_blocked_request_is_pending(state: CommitState, pending: bool) -> None:
    assert outcome(state).pending is pending


def test_a_succeeded_outcome_renders_its_result() -> None:
    commit_id = uuid.uuid4()
    rendered = outcome(CommitState.SUCCEEDED, version=4, file_count=9, commit_id=commit_id)
    assert rendered.as_dict() == {
        "request_id": str(REQUEST_ID),
        "state": "succeeded",
        "collection_id": str(COLLECTION_ID),
        "version": 4,
        "file_count": 9,
        "commit_id": str(commit_id),
        "refusal": None,
    }


def test_a_rejected_outcome_of_a_deleted_collection_renders_its_refusal() -> None:
    refusal = Refusal("BASE_VERSION_CONFLICT", "stale", {"current_version": 5})
    rendered = replace(outcome(CommitState.REJECTED, refusal=refusal), collection_id=None)
    assert rendered.as_dict() == {
        "request_id": str(REQUEST_ID),
        "state": "rejected",
        "collection_id": None,
        "version": None,
        "file_count": None,
        "commit_id": None,
        "refusal": refusal.as_dict(),
    }


def test_a_request_id_conflict_names_the_request() -> None:
    error = RequestIdConflict(REQUEST_ID)
    assert (error.code, error.status) == ("REQUEST_ID_CONFLICT", 409)
    assert error.context == {"request_id": str(REQUEST_ID)}
    assert str(REQUEST_ID) in error.message


def test_a_missing_commit_request_names_the_request() -> None:
    error = CommitRequestNotFound(REQUEST_ID)
    assert (error.code, error.status) == ("COMMIT_REQUEST_NOT_FOUND", 404)
    assert error.context == {"request_id": str(REQUEST_ID)}


def test_a_busy_collection_names_the_collection_and_not_the_pending_request() -> None:
    error = CollectionBusy(COLLECTION_ID)
    assert (error.code, error.status) == ("COLLECTION_BUSY", 409)
    assert error.context == {"collection_id": str(COLLECTION_ID)}
