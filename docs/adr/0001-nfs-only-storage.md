# NFS only, no service-side file access

Status: accepted (2026-10-29)

## Context

Huron version 1 keeps all file bytes on one NFS share and the service never mounts it.

## Decision

The CLI runs on machines that mount the share and copies files over the mount; the service records names, sizes and hashes. No HTTP upload, no resumable-upload protocol, no object storage.

## Consequences

Simple to operate and fast for the people who have the mount. The service cannot verify bytes and cannot repair the share. HTTP ingest behind the same Storage interface is the upgrade path.
