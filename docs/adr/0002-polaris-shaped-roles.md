# Polaris-shaped roles granted to LDAP groups

Status: accepted (2026-10-29)

## Context

Access must be enforced both by the service and by directory permissions.

## Decision

Five fixed roles are bundles of named privileges; authorization checks privileges, not role names. Roles are granted to LDAP groups only, so the same groups appear in POSIX ACLs.

## Consequences

A later Polaris projection maps nearly one to one. Group-only grants mean changing who can do what is an LDAP change. Custom roles and namespace-level grants are not in version 1.
