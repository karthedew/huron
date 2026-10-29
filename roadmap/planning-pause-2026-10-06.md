# User scope and decision history

## Current authority — production-code pause lifted; custom LDAP requirement

The user explicitly reverted the no-code stance and accepted the proposed Keycloak
direction, with the requirement: "there will be a custom ldap service running that
we will want to swap in for rbac creds". The extra user-imposed pause before writing
production MVP code is therefore lifted. Normal reviewed-plan readiness, scoped
exclusive maximum implementation, full applicable gates and independent qualification
still apply. This is not permission to skip blockers, deploy/promote to production,
delete data, or use sudo. Earlier pause statements below are historical, not current
restrictions. Preserve their evidence rather than rewriting past dispatch provenance.

Keycloak handling Google sign-in and issuing Huron API access tokens is accepted.
The user clarified the LDAP requirement: after login, the user's LDAP groups map
to permissions Huron applies to organizations, collections, datasets, service
accounts and other supported resources. LDAP provides group-membership facts;
Huron owns their mapping to resource-scoped roles/permissions and enforcement.
This is an authorization-directory integration, not a request to replace Google/
Keycloak authentication with LDAP passwords or to use LDAP credentials as API tokens.

Plan a replaceable directory-membership adapter independently of identity and Huron
AccessControl. Do not equate directory administration with Huron resource access,
or assume a service account automatically inherits its creator's memberships.
Service-account management is within the resource-permission scope named by the
user; service-account credential/enrollment behavior remains a separate contract.
Stable OIDC-user-to-directory-subject mapping, stable group identifiers, nested
membership behavior, freshness/revocation and outage handling still need concrete
contracts and qualification against the custom service. A login-time membership
snapshot alone must not silently become permanent authorization. No LDAP API,
schema, deployment or integration has been qualified merely by this clarification.

Fresh deployment and explicit stale-base conflict remain approved. The source/code
implementation state and outstanding prerequisite failures are unchanged by this
authorization; all pending plans and durable records need scoped reconciliation.

## Confirmed product planning decisions — 2026-10-06

The user confirmed that there is no existing Huron data to preserve or migrate and
that the MVP should be planned as a fresh deployment. This removes legacy-data
migration as a delivery requirement; it does NOT authorize deleting existing files,
data, volumes or unrelated services. Preserve the initial dirty worktree ownership.

The user also approved rejecting a push whose pinned base becomes stale: return an
explicit conflict and require an explicit retry against the newer base, with no
silent merge. Plan writers must reconcile publication concurrency and retry identity
against this decision without treating it as implemented behavior.

These decisions supersede the unanswered data-disposition and stale-base questions
in older planning receipts. They do not approve production implementation or clear
other prototype, infrastructure, identity or numeric-policy prerequisites.

## Earlier clarification — prerequisite work authorized (historical)

The user subsequently explicitly authorized "all of the planning and checking
until we get to the production MVP code", confirmed the proposed scope including
isolated prototypes, baselines, independent reviews and prerequisite corrections,
and instructed "perfect. let's go". This supersedes the earlier restriction below
on launching further prototype writers. Planning/prerequisite experiments may
continue with declared isolated ownership and independent checks. Production
application code, live schema/deployment changes and live Starlight migration
remain prohibited until the final planning handoff and explicit implementation
approval. Never promote a prototype automatically.

Both previously active writers are now terminal, observed 2026-10-06 01:41 UTC.
Starlight reports failed search-error acceptance and artifact-triggered roadmap
checker failures; SDK reports bounded self-check success with full qualification
pending. Independent reviews have not yet established either result. Their
cleanup receipts report no remaining owned services/process groups.

## Earlier instruction and observation (historical)

The user's latest instruction is: "once you get everything planned out let's pause
before you write the code". This supersedes the prior automatic implementation
sequence. Complete and review the plans, show remaining blockers honestly, then
pause for explicit approval. Do not dispatch production implementation, fixes,
configuration/test changes or live Starlight migration on the previous authority.
Do not promote isolated prototype files. No new code or prototype writers are to
be launched under this planning-only handoff.

At the instruction, two previously authorized isolated prototype writers were
already active: Starlight ses_ef15e0eceffextkoojLCG4HlDP and SDK packaging
ses_ef14cad03ffeFX66GXaMblUr8z. Both remain busy/nonterminal as observed at
2026-10-06 01:10 UTC. Their source claims are read-only; their write ownership is
isolated prototype/check artifacts. Collect their existing handoffs as planning
evidence only; any unfinished experiment or defect stays an explicit blocker.
The loaded dispatch tools expose start/status, not a pause/message operation;
neither child has been cancelled, manually resumed or told that production work
is authorized. Do not bypass dispatch to control them.

The former Starlight cache read has now completed. Worker progress reports 39
tests and both deployment-base static checks; preview process ownership is being
reconciled before browser use. SDK writer is also advancing. These observations
are not independent qualification or product completion.

Planning handoff must include exact scope, ownership, interfaces/deletions,
dependencies, prototype evidence and limitations, full applicable acceptance gates,
review findings and unresolved user decisions. No claim of READY where blockers
remain. End the handoff with an explicit implementation approval checkpoint.
