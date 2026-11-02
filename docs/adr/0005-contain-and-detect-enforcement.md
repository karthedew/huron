# Contain and detect, not prevent

Status: accepted (2026-10-29)

## Context

Scientists own the files they write over NFS, and only a directory's owner can change its ACL.

## Decision

Structural directories are writable only by admins; collection directories by contributors; huron check reports manual writes, changed files and ACL drift.

## Consequences

Cheap and transparent. It does not stop a contributor writing into their own collection by hand; a service-side writer would be needed for that.
