"""Pure role-binding authorization with classification-aware discovery."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from uuid import UUID


class Decision(StrEnum):
    ALLOW = "ALLOW"
    DENY = "DENY"


class Effect(StrEnum):
    ALLOW = "ALLOW"
    DENY = "DENY"


class ScopeType(StrEnum):
    SYSTEM = "SYSTEM"
    ORGANIZATION = "ORGANIZATION"
    PROJECT = "PROJECT"
    DATASET = "DATASET"


@dataclass(frozen=True, slots=True)
class Principal:
    subject: str
    groups: frozenset[str] = frozenset()
    #: "user" or "service_account"; service accounts bind as "sa:{subject}".
    kind: str = "user"

    @property
    def identifiers(self) -> frozenset[str]:
        prefix = "sa" if self.kind == "service_account" else "user"
        return frozenset({f"{prefix}:{self.subject}", *(f"group:{group}" for group in self.groups)})


@dataclass(frozen=True, slots=True)
class Scope:
    scope_type: ScopeType
    scope_id: UUID | None = None
    organization_id: UUID | None = None
    project_id: UUID | None = None
    dataset_id: UUID | None = None

    @classmethod
    def system(cls) -> Scope:
        return cls(ScopeType.SYSTEM)


@dataclass(frozen=True, slots=True)
class Binding:
    principal: str
    capabilities: frozenset[str]
    scope_type: ScopeType
    scope_id: UUID | None
    effect: Effect = Effect.ALLOW
    expires_at: datetime | None = None
    maximum_classification: str | None = None
    layers: frozenset[str] | None = None

    def matches(self, principal: Principal) -> bool:
        return self.principal in principal.identifiers

    def covers(self, scope: Scope) -> bool:
        if self.scope_type is ScopeType.SYSTEM:
            return True
        if self.scope_id is None:
            return False
        if self.scope_type is ScopeType.ORGANIZATION:
            return self.scope_id == scope.organization_id or (
                scope.scope_type is ScopeType.ORGANIZATION and self.scope_id == scope.scope_id
            )
        if self.scope_type is ScopeType.PROJECT:
            return self.scope_id == scope.project_id or (
                scope.scope_type is ScopeType.PROJECT and self.scope_id == scope.scope_id
            )
        return self.scope_id == scope.dataset_id or (
            scope.scope_type is ScopeType.DATASET and self.scope_id == scope.scope_id
        )

    def is_expired(self, now: datetime) -> bool:
        return self.expires_at is not None and self.expires_at <= now


@dataclass(frozen=True, slots=True)
class Classification:
    code: str
    order: int
    discoverable: bool


@dataclass(frozen=True, slots=True)
class ProjectVisibility:
    project_id: UUID
    organization_id: UUID
    classification: str

    @property
    def scope(self) -> Scope:
        return Scope(
            ScopeType.PROJECT,
            self.project_id,
            organization_id=self.organization_id,
            project_id=self.project_id,
        )


@dataclass(frozen=True, slots=True)
class RoleBindingAuthorizer:
    classifications: tuple[Classification, ...] = field(default_factory=tuple)

    def decide(
        self,
        bindings: tuple[Binding, ...] | list[Binding],
        principal: Principal,
        capability: str,
        scope: Scope,
        *,
        layer: str | None = None,
        now: datetime | None = None,
    ) -> Decision:
        return decide(bindings, principal, capability, scope, layer=layer, now=now)

    def visible_project_ids(
        self,
        principal: Principal,
        projects: tuple[ProjectVisibility, ...] | list[ProjectVisibility],
        bindings: tuple[Binding, ...] | list[Binding],
        *,
        now: datetime | None = None,
    ) -> list[UUID]:
        vocabulary = {item.code: item for item in self.classifications}
        current_time = now or datetime.now(UTC)
        visible: list[UUID] = []
        for project in projects:
            if (
                decide(
                    bindings,
                    principal,
                    "dataset.discover",
                    project.scope,
                    now=current_time,
                )
                is not Decision.ALLOW
            ):
                continue
            classification = vocabulary.get(project.classification)
            if classification is None:
                continue
            if classification.discoverable or _has_clearance(
                bindings,
                principal,
                project.scope,
                classification.order,
                vocabulary,
                current_time,
            ):
                visible.append(project.project_id)
        return visible


def _applicable_bindings(
    bindings: tuple[Binding, ...] | list[Binding],
    principal: Principal,
    capability: str,
    scope: Scope,
    now: datetime,
) -> list[Binding]:
    """Bindings matching the principal, covering the scope, unexpired, granting the capability."""
    return [
        binding
        for binding in bindings
        if binding.matches(principal)
        and binding.covers(scope)
        and not binding.is_expired(now)
        and capability in binding.capabilities
    ]


def _permits_layer(binding: Binding, layer: str | None) -> bool:
    """A binding scoped to specific layers only grants capabilities within them."""
    return layer is None or binding.layers is None or layer in binding.layers


def decide(
    bindings: tuple[Binding, ...] | list[Binding],
    principal: Principal,
    capability: str,
    scope: Scope,
    *,
    layer: str | None = None,
    now: datetime | None = None,
) -> Decision:
    current_time = now or datetime.now(UTC)
    applicable = _applicable_bindings(bindings, principal, capability, scope, current_time)
    if any(binding.effect is Effect.DENY for binding in applicable):
        return Decision.DENY
    for level in (
        ScopeType.DATASET,
        ScopeType.PROJECT,
        ScopeType.ORGANIZATION,
        ScopeType.SYSTEM,
    ):
        for binding in applicable:
            if (
                binding.scope_type is level
                and binding.effect is Effect.ALLOW
                and _permits_layer(binding, layer)
            ):
                return Decision.ALLOW
    return Decision.DENY


def _has_clearance(
    bindings: tuple[Binding, ...] | list[Binding],
    principal: Principal,
    scope: Scope,
    required_order: int,
    vocabulary: dict[str, Classification],
    now: datetime,
) -> bool:
    for binding in bindings:
        if (
            binding.effect is Effect.ALLOW
            and binding.matches(principal)
            and binding.covers(scope)
            and not binding.is_expired(now)
            and binding.maximum_classification in vocabulary
            and vocabulary[binding.maximum_classification].order >= required_order
        ):
            return True
    return False


__all__ = [
    "Binding",
    "Classification",
    "Decision",
    "Effect",
    "Principal",
    "ProjectVisibility",
    "RoleBindingAuthorizer",
    "Scope",
    "ScopeType",
    "decide",
]
