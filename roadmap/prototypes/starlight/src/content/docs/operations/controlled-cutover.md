---
title: Controlled legacy verification
---

> **Throwaway prototype — not shipped documentation.** Canonical source: `docs/operations/controlled-cutover.md`. Generated rendering view; original source remains authoritative.

<a id="controlled-legacy-verification"></a>

`lakectl protocol cutover --prepare` verifies a legacy schema-0010 root while an
independent local controller excludes every application writer. It imports trusted
final revisions, records corrupt revisions as DEGRADED, resolves legacy sessions,
and writes a canonical report before its numbered protocol record. It leaves both
old and replacement application database logins disabled. Migration, activation,
protocol initialization and API startup validation remain the following delivery
slice; this command does not make the current release deployable.

## Supported deployment and authority

The provider supports one actual Linux host with a private, root-owned Podman
engine and local named volume. The controller owns application restart admission.
Application users and automation users can access its public Unix socket, but the
kernel UID determines their permitted operations. They cannot access the private
engine socket, its graphroot, other engine endpoints, or host storage grants. The
application container has no daemon socket, host namespace, privilege or bind mount
that could bypass this boundary. Only its configured immutable image, UID, named
volume and isolated network can be started.

Trusted operating-system, engine and database administrators provision this
boundary and are outside the application-writer threat model. Giving an automation
user general `sudo`, engine-group membership, another daemon listener or direct
storage access violates the deployment contract. Plain `docker compose up`, the
repository's owner-credential development stack, remote engines, NFS and arbitrary
host writers are not certified by this provider. An unreachable controller or an
unsupported volume causes refusal, not an inferred shutdown.

The engine adapter inventories all containers, including stopped containers. It
refuses foreign protected-volume holders, mounts exposing the storage or engine
socket in either ancestor or descendant direction, and privileged or host-namespace
containers. Relative or symlink-aliased backing paths are refused because they
cannot reliably identify an already-mounted backing object. Live admission
revalidates the trusted Compose file identity. It persists restart exclusion
before stopping each application writer, verifies process termination and removes
the restartable container identity. Controller restart, every observed loss and
every client-declared abandonment advance the generation; evidence naming an
earlier generation is then refused (see [Verification epoch](/huron-docs/operations/controlled-cutover/#verification-epoch)).
Periodic checks detect fence loss while the private
engine and admission policy enforce exclusion between checks.

## Administrator provisioning

The repository's `deploy/controlled/` directory contains example systemd units,
resolved Compose JSON, controller/maintenance settings and dedicated-role SQL.
These are templates for an administrator-provisioned deployment, not a command
that changes an existing development or production environment.

1. Install the locked Huron runtime at `/opt/huron`, with `lakectl` in its `bin`
   directory. Install the engine unit as `huron-engine.service` and the controller
   unit as `huron-controller.service`. The engine has only its private Unix API
   endpoint. Both graphroot and engine runtime directory are root-owned mode 0700.
2. On SELinux systems, assign the custom graphroot the distribution's container
   storage label before images are extracted. Use the default graphroot's policy
   as the reference; do not disable MAC enforcement. The disposable integration
   fixture uses an equivalent context for its own temporary graphroot and removes
   the entire root afterwards.
3. Through the private engine, provision the isolated network and local Raw named
   volume, set the volume's content ownership to the configured application UID,
   and load the actual legacy image. Set `image` to its real engine content digest
   or a repository digest. The all-zero example digest intentionally cannot launch
   an application. Database/identity-provider networking and any external ingress
   remain administrator-provisioned infrastructure; application users cannot
   recreate those services through the controller.
4. Provision separate database identities. The development/migration owner keeps
   ownership of all tables and schemas. The legacy and replacement application
   roles own no database objects and have no administrative attributes. The
   dedicated cutover identity is privileged maintenance authority; its connection
   material is available only to the root-run operator process. Set passwords
   through the deployment's private secret channel. Enable the legacy and cutover
   logins only after provisioning; keep the replacement login disabled and never
   give its credentials to the legacy artifact.
5. Install actual settings under root-protected `/etc/huron`, with each JSON file
   mode 0600. Choose persistent unique root/controller UUIDs, correct local UIDs,
   role names and the resolved Compose service. The supported service keys are
   `image`, `command`, `environment`, `user`, `volumes`, and `networks`; the service
   has exactly one named volume mounted at `/data` and one isolated network.
   Settings contain secrets and must not be copied into evidence reports.

The Podman API gives its caller full engine authority, which is why the private
socket is a prerequisite. See the official [Podman service documentation](https://docs.podman.io/en/latest/markdown/podman-system-service.1.html)
and [container storage configuration](https://github.com/podman-container-tools/container-libs/blob/main/storage/docs/containers-storage.conf.5.md).

## Operator surface

Before a fence exists, an authorized restart UID can request only the configured
legacy application:

```sh
lakectl restart --socket /run/huron-controller/controller.sock
```

A root operator supplies a stable run UUID and private maintenance configuration:

```sh
lakectl protocol cutover --prepare --config /etc/huron/maintenance.json --run-id RUN_UUID
```

There is no actor-name argument. The core authenticates the controller's grant and
binds it to the actual root before scanning. The command prints only the canonical
bytes of its numbered record; refusal exits 1 without echoing database credentials. Existing
application sessions are terminated independently of writer-process shutdown.
Effective inherited, ownership, column, sequence, security-definer-function,
database-create and public write privileges are checked. Unsafe public or owner
privileges cause refusal rather than broad revocation from unrelated users.

Every acknowledged structural generation and CURRENT pointer must agree with the
database hierarchy. Every revision document and payload file is read completely;
canonical bytes, names, identities, counts, digests, ownership, seals and regular
file link count are checked. Missing or unreadable documents retain explicit
ABSENT/ERROR observations without invented digests. Trusted corrupt revisions
remain visible as DEGRADED; conflicting identity or missing parents block the run.

`protocol/reports/000001.json` contains per-revision observations and structural
document digests; `protocol/000001.json` is the numbered record binding the root,
run, controller generation, maintenance database identity and exact report digest.
Report and record of one `--prepare` share one sequence number; every `--prepare`
appends the next free pair and nothing under `protocol/` is reused or rewritten. A
report without its record is history left by a failed run, not something a later
run resumes. The controller reads its private `maintenance_path` configuration once
at start to check the database fence independently; editing it takes effect only at
restart. The report is fsynced before the record is installed.
Only exact VERIFIED membership certifies a revision; historic commit timestamps
do not confer certification. Portable JSON Schemas validate document structure and
local digest/outcome conditions; runtime validation additionally checks cross-field
identity, uniqueness and report/record binding.

Prepared report and numbered-record files are immutable forensic evidence, not a
certificate. Their presence, or absence of another file, never establishes success.
A permanently named private no-follow lock inode gives one process exclusive
maintenance ownership. The kernel releases ownership on process death; no marker
is removed and no lease expires. Cancellation waits for actual filesystem writers
before releasing ownership. A competing invocation is refused, including the same
run submitted through another process.

## Verification epoch

The controller's durably persisted generation is the verification epoch and its only
authority state
([ADR-0001](/huron-docs/adr/0001-controller-generation-is-the-verification-epoch/)). The
controller mints generation 1 at every start and never issues it. `--prepare` begins
with `establish`, which mints the next generation and returns fence evidence naming
it, the run, the operator and the maintenance database identity
`<system_identifier>/<database_oid>/<datname>`, captured from the database before any
writer is terminated. A database that is not a primary refuses `--prepare`
("maintenance database is not a primary"). Every later database observation compares
the live identity with the fence before any role change and refuses on disagreement
("maintenance database identity differs from the fence").

An epoch ends in exactly three ways, each advancing the generation on disk before
the refusal is reported: the controller observes a loss (volume identity, engine
transport, writer inventory, storage I/O under its claim, the role fence or the
database identity, or cancellation during any of these); the client declares one
through `abandon`, which `--prepare` sends for any failure after `establish`; or the
controller restarts. Restoring the database, volume or engine afterwards revives
nothing, because the generation already moved. A mismatched argument (wrong run,
stored record, report digest, operator or peer) refuses the presented record without
ending the epoch. If the controller cannot persist an advance, its memory still
moves to the new generation, so it keeps refusing the old record; the next start
advances the durable generation again.

After all local writes, monitor shutdown and ownership release succeed, `--prepare`
asks the controller to validate the record. `validate` is stateless: under its own
claim the controller re-reads the record and report, checks the exact
record/report/root/run binding, the live role fence and database identity and its
deployment/writer generation, and admits the record only if the fence names the
live epoch. Because `establish` is the first step of `--prepare` and every failure
after it ends the epoch, an admitted record proves that the scan producing it
completed under that epoch. Every refusal reaches the client as `CONTROLLER_REFUSED`
and the command exits 1 with one fixed message, never the reason. Later
initialization and activation consumers must call the same `validate`; JSON files
alone never establish admission. No M1c activation is implemented here.

:::note[Residual windows]
Three windows are bounded, not closed: a writer loss between two fence checks is
unobserved until the next check; an `abandon` that fails to reach a live
controller, or a client that dies before sending it, leaves the epoch open until
the controller's next observation. Each closes at the next fence check or
observation, and `validate`'s own observations refuse a record whose fence names
an ended epoch.

:::

## Recovering a lost reply

A controller interrupted while handling a request sends no reply; the client reports
"controller closed the connection without a reply" and the command exits 1. The
record may still be admissible. Find `N` as the highest `protocol/NNNNNN.json` and
run:

```sh
lakectl protocol cutover --validate --config /etc/huron/maintenance.json --sequence N
```

Exit 0 prints the admitted record, exactly the bytes the lost `--prepare` would have
printed. Exit 1 while the controller is unreachable is another lost reply; run
`--validate` again once it answers. Exit 1 from an answering controller means the
epoch ended and only a new `--prepare`, with its full scan, can produce an admissible
record. Exit 2 is a usage error. `--validate` never rescans and never changes the
epoch when it admits.

## Verification evidence

The durable integration test builds the real historical application from commit
`db5fc84cd7bfe049692ef2abb16fb32570ccf5a2`, verifies the source archive digest and
records the built image digest. Its old HTTP upload writes after SQL exclusion,
then stops when the real controller terminates the process. The revoked old image
cannot start successfully; the controller refuses restart, foreign volume holders,
stale generations, unauthorized kernel UIDs and unreachable-controller checks.
The fixture removes its owned containers, volumes, network, image and graphroot in
cleanup. This is evidence for the disposable local Linux contract, not a claim
that an unexamined deployment has the same isolation.
