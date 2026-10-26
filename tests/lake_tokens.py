"""Fixed test-only signing material and controllable key-source boundaries."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final

from cryptography.hazmat.primitives.asymmetric import ec

from huron.core.security.broker import (
    PrivateSigningKey,
    PublicSigningKey,
    SigningKeyRecord,
    HuronKeys,
    HuronTokenIssuer,
    Grants,
)
from huron.core.foundation.clock import Clock
from huron.core.security.errors import SigningKeyUnavailable

if TYPE_CHECKING:
    from collections.abc import Mapping

# This publicly known scalar is fixture material only, never a deployment key.
TEST_KEY: Final = ec.derive_private_key(
    0x519B423D715F8B5D549F6B31B23B66C46E68C979340D0EEAB8B8BD15312B7103, ec.SECP256R1()
)
TEST_KEY_REF: Final = "test-es256.pem"
TEST_KID: Final = "zX9iHYbPK8ihN_MFfQPQMIE618CLgYmEFAweXjs1vJo"
TEST_EPOCH: Final = datetime(2026, 1, 1, tzinfo=UTC)
TEST_RECORD: Final = SigningKeyRecord(
    PublicSigningKey.from_private(TEST_KEY), TEST_KEY_REF, TEST_EPOCH, None
)


class InMemorySigningKeySource:
    """Load test keys by reference, with absent entries representing unavailable material."""

    def __init__(self, keys: Mapping[str, PrivateSigningKey]) -> None:
        self.keys = dict(keys)

    def load(self, private_ref: str) -> PrivateSigningKey:
        """Return a registered key or the same missing-reference error as the file source."""
        try:
            return self.keys[private_ref]
        except KeyError:
            raise SigningKeyUnavailable(
                context={"private_ref": private_ref, "reason": "missing"}
            ) from None


class ScriptedSigningKeyReader:
    """Supply mutable test records or an injected store failure, counting all reads."""

    def __init__(self, records: list[SigningKeyRecord], exception: Exception | None = None) -> None:
        self.records = records
        self.exception = exception
        self.calls = 0

    async def unexpired(self, retired_after: datetime) -> tuple[SigningKeyRecord, ...]:
        """Apply the reader's retirement boundary and ordering unless a failure is scripted."""
        self.calls += 1
        if self.exception is not None:
            raise self.exception
        return tuple(
            sorted(
                (
                    row
                    for row in self.records
                    if row.retired_at is None or row.retired_at > retired_after
                ),
                key=lambda row: row.active_from,
            )
        )


class PausedSigningKeyReader(ScriptedSigningKeyReader):
    """Pause persistence reads so tests can observe refresh serialization and cancellation."""

    def __init__(self, records: list[SigningKeyRecord]) -> None:
        super().__init__(records)
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.finished = asyncio.Event()
        self.inflight = 0
        self.max_inflight = 0

    async def unexpired(self, retired_after: datetime) -> tuple[SigningKeyRecord, ...]:
        """Signal entry, await release and acknowledge completion even when cancelled."""
        self.inflight += 1
        self.max_inflight = max(self.max_inflight, self.inflight)
        self.entered.set()
        try:
            await self.release.wait()
            return await super().unexpired(retired_after)
        finally:
            self.inflight -= 1
            self.finished.set()


TEST_ISSUER: Final = "https://huron.test"


async def refreshed_test_keys(clock: Clock) -> HuronKeys:
    """Build a refreshed ring without starting a refresh loop."""
    keys = HuronKeys(
        ScriptedSigningKeyReader([TEST_RECORD]),
        InMemorySigningKeySource({TEST_KEY_REF: TEST_KEY}),
        clock,
    )
    await keys.refresh()
    return keys


def mint(
    keys: HuronKeys,
    clock: Clock,
    *,
    subject: str = "karl",
    groups: frozenset[str] = frozenset({"helio-scientists"}),
    grants: Grants | None = None,
) -> str:
    """Mint real tokens through the production issuer for reusable boundary tests."""
    return (
        HuronTokenIssuer(
            keys, issuer=TEST_ISSUER, audience=("huron-api",), ttl=timedelta(hours=1), clock=clock
        )
        .issue(subject, groups, grants if grants is not None else Grants(subject, ()))
        .token
    )
