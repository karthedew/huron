"""Company identity exchanges preserve directory membership and current scoped roles."""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import timedelta
from uuid import UUID

import pytest

from huron.core.foundation.errors import AuthError, DependencyUnavailable
from huron.core.security.broker import MAX_RING_AGE, CatalogRef, Role
from huron.core.security.errors import SigningKeyUnavailable
from tests.fakes.ldap_groups import Identities
from tests.unit.support import FakeClock
from tests.lake_store_contract import MemorySeed
from tests.lake_tokens import TEST_KID
from tests.token_exchange_support import exchange_context

pytestmark = pytest.mark.unit
CATALOG = CatalogRef(UUID(int=1), "heliophysics")


def exchange_records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    """Select only the final structured exchange outcomes."""
    return [record for record in caplog.records if record.msg == "auth.exchange"]


async def test_signed_identity_current_roles_and_safe_success_log(
    identities: Identities, clock: FakeClock, caplog: pytest.LogCaptureFixture
) -> None:
    """The username, directory groups and current scoped mappings determine signed claims."""
    caplog.set_level(logging.INFO)
    async with exchange_context(identities, clock) as ctx:
        seed = MemorySeed(ctx.store)
        await seed.ldap_group("huron-administrators", 101)
        await seed.ldap_group("helio-developers", 102)
        await seed.role_mapping("huron-administrators", None, Role.ADMINISTRATOR)
        await seed.role_mapping("helio-developers", CATALOG, Role.CATALOG_CONTRIBUTOR)
        token = ctx.company.id_token(
            "karl", claims={"groups": ["forged-membership"], "roles": ["forged-role"]}
        )
        issued = await ctx.exchange.exchange(token)
        assert issued.claims.sub == "karl" != identities.user("karl").id
        assert issued.claims.groups == tuple(sorted(identities.user("karl").groups))
        assert [str(role) for role in issued.claims.roles] == [
            "PRINCIPAL_ROLE:administrator",
            "PRINCIPAL_ROLE:heliophysics.catalog_contributor",
        ]
        assert issued.claims.exp == issued.claims.iat + timedelta(minutes=10)
        await seed.remove_role_mapping("huron-administrators", None)
        await seed.remove_role_mapping("helio-developers", CATALOG)
        assert (await ctx.exchange.exchange(token)).claims.roles == ()
        assert ctx.directory.requests == ("karl", "karl")
    first, second = exchange_records(caplog)
    assert (first.subject, first.outcome, first.group_count, first.role_count, first.kid) == (
        "karl",
        "issued",
        2,
        2,
        TEST_KID,
    )
    assert second.role_count == 0
    assert token not in caplog.text and issued.token not in caplog.text


@pytest.mark.parametrize(
    "groups",
    [
        (),
        ("unmapped",),
        tuple(f"group-{i}" for i in range(100)),
        tuple(f"group-{i}" for i in range(101)),
    ],
)
async def test_empty_unmapped_and_large_membership(
    identities: Identities,
    clock: FakeClock,
    caplog: pytest.LogCaptureFixture,
    groups: tuple[str, ...],
) -> None:
    """Every group is signed even without roles, with a single warning above 100 groups."""
    identities = identities.with_user(replace(identities.user("karl"), groups=groups))
    caplog.set_level(logging.INFO)
    async with exchange_context(identities, clock) as ctx:
        issued = await ctx.exchange.exchange(ctx.company.id_token("karl"))
    assert issued.claims.groups == tuple(sorted(groups))
    assert issued.claims.roles == ()
    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert len(warnings) == (1 if len(groups) > 100 else 0)
    assert len(exchange_records(caplog)) == 1


@pytest.mark.parametrize(
    "claim,value",
    [
        ("preferred_username", None),
        ("login", "absent"),
        ("login", "bad/value"),
        ("login", 42),
        ("login", ""),
        ("login", "x" * 129),
        ("login", " name"),
    ],
)
async def test_invalid_or_unknown_subject(
    identities: Identities,
    clock: FakeClock,
    caplog: pytest.LogCaptureFixture,
    claim: str,
    value: object,
) -> None:
    """Unusable claim values never leak into diagnostics or reach the directory."""
    caplog.set_level(logging.INFO)
    async with exchange_context(identities, clock, subject_claim=claim) as ctx:
        token = ctx.company.id_token("karl", claims={claim: value})
        with pytest.raises(AuthError) as caught:
            await ctx.exchange.exchange(token)
        if value == "absent":
            assert str(caught.value) == "absent is unknown to the group directory"
            assert ctx.directory.requests == ("absent",)
        else:
            assert str(caught.value) == f"company token has no usable {claim}"
            assert ctx.directory.requests == ()
    (record,) = exchange_records(caplog)
    assert record.outcome == "INVALID_CREDENTIAL"
    assert record.group_count is None and record.role_count is None and record.kid is None
    assert token not in caplog.text


async def test_missing_configured_claim(identities: Identities, clock: FakeClock) -> None:
    """A missing configured username claim fails before membership lookup."""
    async with exchange_context(identities, clock, subject_claim="login") as ctx:
        with pytest.raises(AuthError, match="company token has no usable login"):
            await ctx.exchange.exchange(ctx.company.id_token("karl"))
        assert ctx.directory.requests == ()


async def test_custom_claim_keeps_case_and_upn(identities: Identities, clock: FakeClock) -> None:
    """Configured username claims retain the exact directory spelling."""
    person = replace(
        identities.user("karl"), id="00000000-0000-4000-8000-000000000000", username="Karl@corp"
    )
    identities = identities.with_user(person)
    async with exchange_context(identities, clock, subject_claim="login") as ctx:
        issued = await ctx.exchange.exchange(
            ctx.company.id_token(person.username, claims={"login": person.username})
        )
        assert issued.claims.sub == person.username
        assert ctx.directory.requests == (person.username,)


@pytest.mark.parametrize("failure", ["company", "directory", "signing"])
async def test_failures_stop_the_exchange_and_log_codes(
    identities: Identities, clock: FakeClock, caplog: pytest.LogCaptureFixture, failure: str | int
) -> None:
    """Verification, directory and signing failures propagate without producing a token."""
    caplog.set_level(logging.INFO)
    async with exchange_context(identities, clock) as ctx:
        if failure == "signing":
            clock.advance(MAX_RING_AGE + timedelta(seconds=1))
        if failure == "directory":
            ctx.directory.inject("timeout")
        token = ctx.company.id_token("karl", forged=failure == "company")
        expected = {
            "company": AuthError,
            "directory": DependencyUnavailable,
            "signing": SigningKeyUnavailable,
        }[failure]
        with pytest.raises(expected) as caught:
            await ctx.exchange.exchange(token)
        assert ctx.directory.requests == (() if failure == "company" else ("karl",))
    (record,) = exchange_records(caplog)
    assert record.outcome == caught.value.code
    assert record.kid is None
    assert token not in caplog.text


@pytest.mark.parametrize(
    "failure",
    [
        DependencyUnavailable(context={"dependency": "database", "reason": "unreachable"}),
        RuntimeError("private connection detail"),
    ],
)
async def test_mapping_failure_propagates_unchanged(
    identities: Identities, clock: FakeClock, caplog: pytest.LogCaptureFixture, failure: Exception
) -> None:
    """A persistence failure cannot become empty grants or leak connection details."""
    caplog.set_level(logging.INFO)
    async with exchange_context(identities, clock) as ctx:
        ctx.mappings.failure = failure
        with pytest.raises(type(failure)) as caught:
            await ctx.exchange.exchange(ctx.company.id_token("karl"))
        assert caught.value is failure
        assert ctx.mappings.calls == [frozenset(identities.user("karl").groups)]
    (record,) = exchange_records(caplog)
    assert record.outcome == getattr(failure, "code", "INTERNAL_ERROR")
    assert record.group_count == 2 and record.role_count is None and record.kid is None
    assert str(failure) not in caplog.text
