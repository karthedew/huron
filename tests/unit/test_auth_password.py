"""Argon2id password hashing: round-trip verification, length policy, and the
constant-shape dummy-hash path used for unknown principals."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from huron.pkg.auth import password

pytestmark = pytest.mark.unit


def test_hash_and_verify_password_round_trips() -> None:
    record = password.make_credential(uuid4(), "correct horse battery", updated_by="admin")
    assert password.verify_password(record, "correct horse battery") is True


def test_verify_password_rejects_a_wrong_password() -> None:
    record = password.make_credential(uuid4(), "correct horse battery", updated_by="admin")
    assert password.verify_password(record, "wrong password entirely") is False


def test_hash_password_rejects_passwords_under_the_minimum_length() -> None:
    short = "a" * (password.MIN_PASSWORD_LENGTH - 1)
    with pytest.raises(password.PasswordRejected):
        password.hash_password(short)


def test_hash_password_accepts_passwords_at_the_minimum_length() -> None:
    exact = "a" * password.MIN_PASSWORD_LENGTH
    assert password.hash_password(exact)


def test_make_credential_rejects_short_passwords_before_hashing() -> None:
    with pytest.raises(password.PasswordRejected):
        password.make_credential(uuid4(), "short", updated_by="admin")


def test_verify_password_returns_false_for_a_missing_record_but_still_hashes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No account means no record to verify against, but the caller must not
    be able to tell that from timing: the hasher still runs, against a fixed
    dummy hash generated at import time."""
    seen_hashes: list[str] = []
    real_hasher = password._HASHER

    class SpyHasher:
        def verify(self, hash_: str, candidate: str) -> None:
            seen_hashes.append(hash_)
            real_hasher.verify(hash_, candidate)

    monkeypatch.setattr(password, "_HASHER", SpyHasher())

    assert password.verify_password(None, "whatever the caller typed") is False
    assert seen_hashes == [password._DUMMY_HASH]


def test_verify_password_returns_false_for_a_corrupt_stored_hash() -> None:
    """A stored hash that isn't a valid argon2 string is a failed login, not
    a 500 - InvalidHashError must be caught alongside the mismatch errors."""
    record = password.CredentialRecord(
        principal_id=uuid4(),
        password_hash="not-an-argon2-hash",
        updated_at=datetime.now(UTC),
        updated_by="admin",
    )
    assert password.verify_password(record, "whatever the caller typed") is False


def test_needs_rehash_is_false_for_a_freshly_made_credential() -> None:
    record = password.make_credential(uuid4(), "correct horse battery", updated_by="admin")
    assert password.needs_rehash(record) is False


def test_make_credential_stamps_the_given_time_and_author() -> None:
    principal_id = uuid4()
    moment = datetime(2026, 1, 1, tzinfo=UTC)
    record = password.make_credential(
        principal_id, "correct horse battery", updated_by="root", now=moment
    )
    assert record.principal_id == principal_id
    assert record.updated_at == moment
    assert record.updated_by == "root"


async def test_memory_credential_store_round_trips_by_principal_id() -> None:
    store = password.MemoryCredentialStore()
    principal_id = uuid4()
    record = password.make_credential(principal_id, "correct horse battery", updated_by="admin")

    assert await store.get(principal_id) is None
    await store.upsert(record)
    assert await store.get(principal_id) == record
