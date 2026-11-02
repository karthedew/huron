# No moves and no file versioning

Status: accepted (2026-10-29)

## Context

Moving collections and keeping file history multiply the failure cases of a share the service cannot see.

## Decision

Collections, namespaces, catalogs and organizations are never renamed or moved, and recorded files have no history. Recovery is the storage snapshot policy.

## Consequences

Paths stay stable for readers and pipelines. A mistake is fixed by creating a new collection or restoring from a snapshot.
