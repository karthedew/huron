"""Pure role-binding authorization with classification-aware discovery.

This module is the authorization engine itself, not a re-export shim:
:func:`decide` and the value types it reads live here, and
:mod:`huron.pkg.rbac.roles` beside it holds the role vocabulary that
compiles into those values. Nothing here touches a framework, a database
or a clock beyond the ``now`` argument, so a decision is a pure function
of the bindings the caller loaded, the principal asking, the capability,
the scope and the time; the service tier does the loading and asks.

The model is small. A :class:`Principal` answers to a set of identifiers -
its own ``user:`` or ``sa:`` name and its groups. A :class:`Binding` grants
or denies a set of capabilities to one identifier at one scope. A
:class:`Scope` names the organization, project or dataset a question is
about together with its ancestry, so a binding attached higher up covers
everything nested beneath it; that is how a dataset inherits policies
attached at its project or organization. ``decide`` answers
deny-by-default, lets any applicable DENY win, and otherwise allows when a
covering ALLOW binding admits the requested layer.
:class:`RoleBindingAuthorizer` adds the classification vocabulary that
discovery needs: a project is listed only when its classification is
discoverable or the principal is cleared up to it. It also computes a
principal's whole :class:`Visibility` - the organization, project and
dataset ids it may discover, given the projects and
:class:`DatasetVisibility` entries the caller loaded - in the one place
that already evaluates deny-overrides, the scope walk and classification
clearance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    from uuid import UUID


class Decision(StrEnum):
    """The answer to an authorization question: ``ALLOW`` or ``DENY``.

    :func:`decide` answers ``DENY`` unless some binding positively allows,
    so having no bindings at all is a denial, not an error.
    """

    ALLOW = "ALLOW"
    DENY = "DENY"


class Effect(StrEnum):
    """What a binding does when it applies: grant (``ALLOW``) or withhold (``DENY``).

    One applicable ``DENY`` binding overrides every ``ALLOW`` at every scope
    level, which is what makes a denial usable as an exception carved out
    of a broader grant.
    """

    ALLOW = "ALLOW"
    DENY = "DENY"


class ScopeType(StrEnum):
    """The levels a binding can attach at, from the whole platform down to one dataset.

    ``SYSTEM`` contains every organization, an ``ORGANIZATION`` its
    projects, a ``PROJECT`` its datasets; a binding covers the scope it is
    attached to and everything nested inside it (see
    :meth:`Binding.covers`).
    """

    SYSTEM = "SYSTEM"
    ORGANIZATION = "ORGANIZATION"
    PROJECT = "PROJECT"
    DATASET = "DATASET"


@dataclass(frozen=True, slots=True)
class Principal:
    """Who is asking: a subject, the groups it belongs to, and what kind of actor it is.

    The engine never compares principals directly; it compares the
    identifier strings in :attr:`identifiers` against ``Binding.principal``,
    so a binding may address a user, a service account or a whole group.

    Attributes:
        subject: The stable subject identifier the credential resolved to.
        groups: The group names the subject belongs to; each is an
            identifier a binding may address as ``group:{name}``.
        kind: ``user`` or ``service_account``, which decides the prefix of
            the subject's own identifier.
    """

    subject: str
    groups: frozenset[str] = frozenset()
    #: "user" or "service_account"; service accounts bind as "sa:{subject}".
    kind: str = "user"

    @property
    def identifiers(self) -> frozenset[str]:
        """Return every binding-principal string this principal answers to.

        That is ``sa:{subject}`` for a service account, ``user:{subject}``
        for any other kind, plus ``group:{name}`` for each group. A binding
        applies to the principal when its ``principal`` field is one of
        these.

        Returns:
            The identifier strings as a set; never empty.
        """
        prefix = "sa" if self.kind == "service_account" else "user"
        return frozenset({f"{prefix}:{self.subject}", *(f"group:{group}" for group in self.groups)})


@dataclass(frozen=True, slots=True)
class Scope:
    """The place an authorization question is asked about, with its ancestry.

    ``scope_type`` and ``scope_id`` name the scope itself;
    ``organization_id``, ``project_id`` and ``dataset_id`` name the chain
    of containers above and including it, and are what
    :meth:`Binding.covers` reads when it decides whether a binding attached
    higher up reaches this scope. A caller that omits the ancestry gets no
    inheritance: a dataset scope built without its ``project_id`` is not
    covered by a project binding. The ``SYSTEM`` scope carries no ids at
    all.

    Attributes:
        scope_type: The level the question is about.
        scope_id: The id of the organization, project or dataset at that
            level, or None for ``SYSTEM``.
        organization_id: The owning organization, for organization, project
            and dataset scopes.
        project_id: The owning project, for project and dataset scopes.
        dataset_id: The dataset itself, for dataset scopes.
    """

    scope_type: ScopeType
    scope_id: UUID | None = None
    organization_id: UUID | None = None
    project_id: UUID | None = None
    dataset_id: UUID | None = None

    @classmethod
    def system(cls) -> Scope:
        """Return the ``SYSTEM`` scope, which has no id and no ancestry.

        Returns:
            The scope that only ``SYSTEM`` bindings cover.
        """
        return cls(ScopeType.SYSTEM)


@dataclass(frozen=True, slots=True)
class Binding:
    """One grant or denial of a set of capabilities to a principal identifier at a scope.

    A binding is the unit :func:`decide` evaluates. It is addressed to a
    single identifier string (``user:…``, ``sa:…`` or ``group:…``),
    attached at one scope, and applies to a question when it matches the
    principal, covers the scope and has not expired. Roles compile to
    bindings (:func:`huron.pkg.rbac.roles.compile_binding`); the engine
    never sees a role.

    Attributes:
        principal: The identifier the binding addresses, in the form
            :attr:`Principal.identifiers` produces.
        capabilities: The capability codes granted or denied together.
        scope_type: The level the binding is attached at.
        scope_id: The id of the organization, project or dataset it is
            attached to; None only for ``SYSTEM``.
        effect: Whether an applicable binding allows or denies.
        expires_at: The instant from which the binding no longer applies,
            or None for a binding that never expires.
        maximum_classification: The highest classification code the binding
            clears its principal for during discovery, or None when it
            confers no clearance.
        layers: The storage layers a ``data.read``/``data.write`` grant is
            limited to; None means every layer.
    """

    principal: str
    capabilities: frozenset[str]
    scope_type: ScopeType
    scope_id: UUID | None
    effect: Effect = Effect.ALLOW
    expires_at: datetime | None = None
    maximum_classification: str | None = None
    layers: frozenset[str] | None = None

    def matches(self, principal: Principal) -> bool:
        """Return whether this binding is addressed to ``principal``.

        A binding matches when its ``principal`` string is one of the
        identifiers the principal answers to: its own user or
        service-account name, or any of its groups.

        Args:
            principal: The actor whose identifiers are consulted.

        Returns:
            True when the binding addresses the principal directly or
            through a group.
        """
        return self.principal in principal.identifiers

    def covers(self, scope: Scope) -> bool:
        """Return whether the scope this binding is attached at contains ``scope``.

        Coverage is how policies inherit: a binding at an organization
        covers the organization itself and every project and dataset whose
        ancestry names it, a binding at a project covers the project and
        its datasets, and a binding at a dataset covers only that dataset.
        A ``SYSTEM`` binding covers every scope. Containment is read from
        the scope's ancestry fields (``organization_id``, ``project_id``,
        ``dataset_id``) and, for a scope at the binding's own level, from
        ``scope_id`` too, so a scope built without ancestry still matches
        a binding at its own level. A non-``SYSTEM`` binding whose
        ``scope_id`` is None covers nothing: a malformed binding must never
        widen into a grant.

        Args:
            scope: The scope of the question, with its ancestry set.

        Returns:
            True when the binding's attachment point is ``scope`` or an
            ancestor of it.
        """
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
        """Return whether the binding has lapsed at ``now``.

        A binding without ``expires_at`` never expires; one with it is
        expired from that instant onward, the boundary included.

        Args:
            now: The instant to judge against, comparable with
                ``expires_at`` (both timezone-aware).

        Returns:
            True when ``expires_at`` is set and is at or before ``now``.
        """
        return self.expires_at is not None and self.expires_at <= now


@dataclass(frozen=True, slots=True)
class Classification:
    """One level of the classification vocabulary discovery ranks projects by.

    Attributes:
        code: The classification code projects carry.
        order: The level's rank; a higher order is more restricted, and a
            binding's ``maximum_classification`` clears every level whose
            order is at most its own.
        discoverable: Whether projects at this level are listed to anyone
            holding ``dataset.discover`` there, without any clearance.
    """

    code: str
    order: int
    discoverable: bool


@dataclass(frozen=True, slots=True)
class ProjectVisibility:
    """What discovery needs to know about one project: identity, owner and classification.

    Attributes:
        project_id: The project being listed.
        organization_id: The organization that owns it, so bindings at the
            organization cover it.
        classification: The project's classification code, looked up in
            the authorizer's vocabulary.
    """

    project_id: UUID
    organization_id: UUID
    classification: str

    @property
    def scope(self) -> Scope:
        """Return the project's scope with its organization ancestry filled in.

        Returns:
            A ``PROJECT`` scope covered by bindings at the project, at its
            organization, or at ``SYSTEM``.
        """
        return Scope(
            ScopeType.PROJECT,
            self.project_id,
            organization_id=self.organization_id,
            project_id=self.project_id,
        )


@dataclass(frozen=True, slots=True)
class DatasetVisibility:
    """One dataset a DATASET-scope binding names, with the project that owns it.

    :meth:`RoleBindingAuthorizer.visibility` builds the dataset's own scope
    from ``project_id`` together with that project's
    :class:`ProjectVisibility`, so a binding attached above the dataset -
    at its project, its organization, or the whole system - still covers
    it.

    Attributes:
        dataset_id: The dataset being evaluated for discovery.
        project_id: The project that owns it.
    """

    dataset_id: UUID
    project_id: UUID


@dataclass(frozen=True, slots=True)
class Visibility:
    """What one principal may discover, as three id sets plus a shortcut flag.

    :meth:`RoleBindingAuthorizer.visibility` is the only place that
    computes one. ``unrestricted`` short-circuits every other field: it is
    true only for a principal holding ``dataset.discover`` at ``SYSTEM``
    scope, and every resource is then discoverable regardless of the id
    sets. Membership in ``organization_ids`` alone does not extend to that
    organization's projects or datasets - those are exactly what
    ``project_ids`` and ``dataset_ids`` admit.

    Attributes:
        organization_ids: Organizations discoverable through an
            organization-scope binding, independent of what its projects
            or datasets admit.
        project_ids: Projects discoverable by binding and classification.
        dataset_ids: Datasets discoverable through a dataset-scope binding
            whose owning project's classification the principal clears.
        unrestricted: Whether the principal may discover everything.
    """

    organization_ids: frozenset[UUID] = frozenset()
    project_ids: frozenset[UUID] = frozenset()
    dataset_ids: frozenset[UUID] = frozenset()
    unrestricted: bool = False

    #: A dataclass can't reference its own name in a field default, so the
    #: shared "discovers everything" instance is built once, right after
    #: the class exists, and assigned onto the class itself.
    ALL: ClassVar[Visibility]


Visibility.ALL = Visibility(unrestricted=True)


@dataclass(frozen=True, slots=True)
class RoleBindingAuthorizer:
    """The decision engine paired with a classification vocabulary.

    :meth:`decide` is the module-level function unchanged;
    :meth:`visible_project_ids` is the classification-aware discovery that
    needs the vocabulary. The vocabulary is a closed list: a project whose
    classification code is not in it is never visible, so an unknown code
    fails closed rather than open.

    Attributes:
        classifications: The vocabulary discovery ranks projects against.
    """

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
        """Decide whether ``principal`` holds ``capability`` at ``scope``.

        Delegates to :func:`decide`; the vocabulary plays no part in a
        capability decision.

        Args:
            bindings: Every binding loaded for the principal's identifiers.
            principal: The actor asking.
            capability: The capability code in question.
            scope: The scope of the question, with its ancestry set.
            layer: The storage layer for ``data.read``/``data.write``
                questions; None for control-plane capabilities.
            now: The instant expiries are judged at; the current UTC time
                when None.

        Returns:
            ``Decision.ALLOW`` or ``Decision.DENY``.
        """
        return decide(bindings, principal, capability, scope, layer=layer, now=now)

    def visible_project_ids(
        self,
        principal: Principal,
        projects: tuple[ProjectVisibility, ...] | list[ProjectVisibility],
        bindings: tuple[Binding, ...] | list[Binding],
        *,
        now: datetime | None = None,
    ) -> list[UUID]:
        """Return the ids of the projects ``principal`` may see, in the order given.

        A project is visible when all three hold: some binding allows
        ``dataset.discover`` at the project's scope (bindings at its
        organization or at ``SYSTEM`` inherit down); its classification
        code is in the vocabulary; and either that classification is
        discoverable or the principal holds clearance for it - an unexpired
        ``ALLOW`` binding covering the project whose
        ``maximum_classification`` ranks at or above the project's,
        whatever capabilities that binding carries. Expiry is judged once,
        at ``now``, for the whole listing.

        Args:
            principal: The actor listing projects.
            projects: The candidate projects with their owning organization
                and classification.
            bindings: Every binding loaded for the principal's identifiers.
            now: The instant expiries are judged at; the current UTC time
                when None.

        Returns:
            The ``project_id`` of each visible project, preserving the
            input order.
        """
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

    def visibility(
        self,
        principal: Principal,
        bindings: tuple[Binding, ...] | list[Binding],
        projects: tuple[ProjectVisibility, ...] | list[ProjectVisibility],
        datasets: tuple[DatasetVisibility, ...] | list[DatasetVisibility],
        *,
        now: datetime | None = None,
    ) -> Visibility:
        """Return everything ``principal`` may discover, as three id sets and a flag.

        ``unrestricted`` is true only when some binding grants
        ``dataset.discover`` at ``SYSTEM`` scope. ``project_ids`` is
        exactly :meth:`visible_project_ids`. ``organization_ids`` holds
        the id of every unexpired ``ORGANIZATION``-scope binding matching
        ``principal`` whose own organization scope also decides
        ``dataset.discover`` ``ALLOW`` - membership here does not by
        itself admit that organization's projects or datasets.
        ``dataset_ids`` holds the id of every dataset in ``datasets``
        whose own scope decides ``dataset.discover`` ``ALLOW`` and whose
        owning project's classification is in the vocabulary and either
        discoverable or cleared; a dataset whose project is absent from
        ``projects`` is never admitted.

        Args:
            principal: The actor asking.
            bindings: Every binding loaded for the principal's
                identifiers.
            projects: Every project's identity, owning organization and
                classification.
            datasets: The datasets named by DATASET-scope bindings, each
                paired with the id of the project that owns it.
            now: The instant expiries are judged at; the current UTC time
                when None.

        Returns:
            The organization, project and dataset ids the principal may
            discover, and whether it holds unrestricted, platform-wide
            discovery.
        """
        current_time = now or datetime.now(UTC)
        unrestricted = (
            decide(bindings, principal, "dataset.discover", Scope.system(), now=current_time)
            is Decision.ALLOW
        )
        vocabulary = {item.code: item for item in self.classifications}
        return Visibility(
            organization_ids=_organization_ids(bindings, principal, current_time),
            project_ids=frozenset(
                self.visible_project_ids(principal, projects, bindings, now=current_time)
            ),
            dataset_ids=_dataset_ids(
                bindings, principal, projects, datasets, vocabulary, current_time
            ),
            unrestricted=unrestricted,
        )


def _applicable_bindings(
    bindings: tuple[Binding, ...] | list[Binding],
    principal: Principal,
    capability: str,
    scope: Scope,
    now: datetime,
) -> list[Binding]:
    """Return the bindings that bear on one authorization question.

    Bindings matching the principal, covering the scope, unexpired,
    granting the capability. Effect is not a filter: DENY bindings are
    returned alongside ALLOW ones so that :func:`decide` can let a denial
    win.

    Args:
        bindings: Every binding loaded for the principal's identifiers.
        principal: The actor asking.
        capability: The capability code in question.
        scope: The scope of the question, with its ancestry set.
        now: The instant expiries are judged at.

    Returns:
        The applicable bindings, in the order they were given.
    """
    return [
        binding
        for binding in bindings
        if binding.matches(principal)
        and binding.covers(scope)
        and not binding.is_expired(now)
        and capability in binding.capabilities
    ]


def _permits_layer(binding: Binding, layer: str | None) -> bool:
    """Return whether ``binding``'s layer restriction admits ``layer``.

    A binding scoped to specific layers only grants capabilities within
    them. Either side being None lifts the restriction: a question asked
    without a layer is admitted by every binding, and a binding with
    ``layers=None`` reaches every layer.

    Args:
        binding: The binding whose ``layers`` are consulted.
        layer: The storage layer in question, or None for a control-plane
            capability.

    Returns:
        True unless both sides name layers and ``layer`` is not among the
        binding's.
    """
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
    """Decide whether ``principal`` holds ``capability`` at ``scope``.

    The answer is deny-by-default. Only bindings that match the principal,
    cover the scope, are unexpired and name the capability are considered.
    Any considered binding with effect ``DENY`` decides ``DENY`` outright,
    before layers are consulted, so a DENY binding restricted to some
    layers still denies on every layer. Otherwise the answer is ``ALLOW``
    when some considered ``ALLOW`` binding at any covering level -
    dataset, project, organization or ``SYSTEM`` - admits ``layer``; this
    is how a dataset inherits what was granted at its project or
    organization, and how a role that reads every layer can still write
    only some.

    Args:
        bindings: Every binding loaded for the principal's identifiers;
            the engine filters, it never loads.
        principal: The actor asking.
        capability: The capability code in question, such as
            ``dataset.create``.
        scope: The scope of the question, with its ancestry set so bindings
            attached higher up cover it.
        layer: The storage layer for ``data.read``/``data.write``
            questions; None for control-plane capabilities, which no layer
            restriction withholds.
        now: The instant expiries are judged at; the current UTC time when
            None.

    Returns:
        ``Decision.ALLOW`` when a covering ALLOW binding admits the layer
        and no covering DENY binding applies; ``Decision.DENY`` otherwise.
    """
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
    """Return whether the principal is cleared for a classification of ``required_order``.

    Clearance comes from any unexpired ``ALLOW`` binding that matches the
    principal, covers the scope and names a ``maximum_classification`` in
    the vocabulary whose order is at least ``required_order``. The
    binding's capabilities are irrelevant here, and a code outside the
    vocabulary confers nothing.

    Args:
        bindings: Every binding loaded for the principal's identifiers.
        principal: The actor asking.
        scope: The project scope being discovered.
        required_order: The order of the project's classification.
        vocabulary: The classification vocabulary keyed by code.
        now: The instant expiries are judged at.

    Returns:
        True when at least one binding clears the principal to that order.
    """
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


def _organization_visible(
    bindings: tuple[Binding, ...] | list[Binding],
    principal: Principal,
    binding: Binding,
    now: datetime,
) -> bool:
    """Return whether an ORGANIZATION-scope binding also grants discovery of its own scope.

    Args:
        bindings: Every binding loaded for the principal's identifiers.
        principal: The actor asking.
        binding: The organization-scope binding under evaluation.
        now: The instant expiries are judged at.

    Returns:
        True when ``binding`` matches ``principal``, is unexpired, and its
        own organization scope decides ``dataset.discover`` ``ALLOW``.
    """
    return (
        binding.matches(principal)
        and not binding.is_expired(now)
        and decide(
            bindings,
            principal,
            "dataset.discover",
            Scope(ScopeType.ORGANIZATION, binding.scope_id, organization_id=binding.scope_id),
            now=now,
        )
        is Decision.ALLOW
    )


def _organization_ids(
    bindings: tuple[Binding, ...] | list[Binding],
    principal: Principal,
    now: datetime,
) -> frozenset[UUID]:
    """Return the id of every organization an ORGANIZATION-scope binding admits.

    Args:
        bindings: Every binding loaded for the principal's identifiers.
        principal: The actor asking.
        now: The instant expiries are judged at.

    Returns:
        The ``scope_id`` of every ORGANIZATION-scope binding for which
        :func:`_organization_visible` holds.
    """
    return frozenset(
        binding.scope_id
        for binding in bindings
        if binding.scope_type is ScopeType.ORGANIZATION
        and binding.scope_id is not None
        and _organization_visible(bindings, principal, binding, now)
    )


def _dataset_scope(dataset: DatasetVisibility, project: ProjectVisibility) -> Scope:
    """Build the DATASET scope covering ``dataset``, with its full ancestry set.

    Args:
        dataset: The dataset being evaluated for discovery.
        project: The project that owns it, supplying the organization
            ancestry a binding attached above the dataset needs in order
            to cover it.

    Returns:
        A scope covered by bindings attached at the dataset, its project,
        its organization, or ``SYSTEM``.
    """
    return Scope(
        ScopeType.DATASET,
        dataset.dataset_id,
        organization_id=project.organization_id,
        project_id=dataset.project_id,
        dataset_id=dataset.dataset_id,
    )


def _dataset_visible(
    bindings: tuple[Binding, ...] | list[Binding],
    principal: Principal,
    dataset: DatasetVisibility,
    project: ProjectVisibility,
    vocabulary: dict[str, Classification],
    now: datetime,
) -> bool:
    """Return whether ``dataset`` is discoverable, given the project that owns it.

    Args:
        bindings: Every binding loaded for the principal's identifiers.
        principal: The actor asking.
        dataset: The dataset being evaluated.
        project: The project that owns ``dataset``.
        vocabulary: The classification vocabulary keyed by code.
        now: The instant expiries are judged at.

    Returns:
        True when a covering ALLOW binding grants ``dataset.discover`` at
        the dataset's scope and the project's classification is in the
        vocabulary and either discoverable or the principal is cleared
        for it.
    """
    scope = _dataset_scope(dataset, project)
    if decide(bindings, principal, "dataset.discover", scope, now=now) is not Decision.ALLOW:
        return False
    classification = vocabulary.get(project.classification)
    if classification is None:
        return False
    return classification.discoverable or _has_clearance(
        bindings, principal, scope, classification.order, vocabulary, now
    )


def _dataset_ids(
    bindings: tuple[Binding, ...] | list[Binding],
    principal: Principal,
    projects: tuple[ProjectVisibility, ...] | list[ProjectVisibility],
    datasets: tuple[DatasetVisibility, ...] | list[DatasetVisibility],
    vocabulary: dict[str, Classification],
    now: datetime,
) -> frozenset[UUID]:
    """Return the id of every dataset in ``datasets`` that :func:`_dataset_visible` admits.

    A dataset whose ``project_id`` names no entry in ``projects`` is
    skipped rather than evaluated, so an unseeded project never leaks a
    dataset.

    Args:
        bindings: Every binding loaded for the principal's identifiers.
        principal: The actor asking.
        projects: Every project's identity, owning organization and
            classification.
        datasets: The datasets named by DATASET-scope bindings, each
            paired with the id of the project that owns it.
        vocabulary: The classification vocabulary keyed by code.
        now: The instant expiries are judged at.

    Returns:
        The ``dataset_id`` of every admitted dataset.
    """
    projects_by_id = {project.project_id: project for project in projects}
    return frozenset(
        dataset.dataset_id
        for dataset in datasets
        if (project := projects_by_id.get(dataset.project_id)) is not None
        and _dataset_visible(bindings, principal, dataset, project, vocabulary, now)
    )


__all__ = [
    "Binding",
    "Classification",
    "DatasetVisibility",
    "Decision",
    "Effect",
    "Principal",
    "ProjectVisibility",
    "RoleBindingAuthorizer",
    "Scope",
    "ScopeType",
    "Visibility",
    "decide",
]
