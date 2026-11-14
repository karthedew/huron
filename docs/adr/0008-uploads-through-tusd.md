# Uploads through tusd, placed by the Huron API with hard links

Status: accepted (2026-11-06). Supersedes [0001](0001-nfs-only-storage.md). Superseded in part
(2026-11-13): the design of safe publication in `M11_PLAN_2_SAFE_PUBLICATION.md` replaces the
placement, the receipts and the removals of this record. The note below names each replaced part.
The text after the note is the record of 2026-11-06, kept as it was.

## Supersession note (2026-11-13)

A discovery run on 2026-11-10 found defects in the placement design of this record. A refused or
abandoned overwrite could lose committed bytes. The newest placement won by its time. An upload
that timed out could complete late and change public bytes. A lost answer was resolved by
inference from the version. The built system replaces these parts:

| Part of this record | Replaced by |
| --- | --- |
| `pre-finish` places the upload at its final name, and placed bytes are visible before the commit. | A seal copies the complete upload into the object area `<root>/<org>/.huron-objects/`, syncs it and measures its size and SHA-256. No public byte changes before the service accepts a commit. |
| The hook waits while the API hashes the file, up to `upload_hook_timeout`. | `pre-finish` starts or joins the seal and waits at most 20 seconds. Then it answers with `Huron-Upload-State: sealing`, and the client reads `GET /api/v1/upload-attempts/{attempt_id}`. The API also seals a complete upload whose hook never ran. |
| An upload row from `pending` to `placed` and `committed`, with a receipt. The latest placement of a path counts. | An upload attempt with the states `receiving`, `sealing`, `ready` and `consumed`, or the end states `failed`, `cancelled` and `expired`. A commit names each upload by its ID, and the service compares its own hash with the hash of the add. |
| The commit records the rows in one transaction, and the committing request unlinks the removed files. | A commit request is accepted in one transaction. Then the API does one filesystem step for each entry, a removal included, and marks each entry done. A final transaction records the files and the version. A step that finds an unexpected entry blocks the request until a platform administrator retries or abandons it. |
| A background task drains removal rows and sweeps abandoned uploads out of `.tus-uploads`. | The periodic loop continues accepted requests and runs the cleanup. The cleanup selects each object and each file of tusd by its database ID, never by age or by name. |
| `pre-terminate` is a hook event, and tusd terminates uploads. | tusd termination is disabled. A cancel goes through `POST /api/v1/uploads/{id}/cancel`. |
| Two API replicas may place one path at the same time, and a window stays an accepted risk. | One API replica holds a PostgreSQL session advisory lock and is the one writer. A second process serves reads only. A writer that loses its lock stops. The deployment never runs two writable pods. |
| Every organization root is on one filesystem, because a hard link cannot cross filesystems. | Publication links only from the object area of an organization into the same organization directory. `.tus-uploads` can be on another filesystem, because the seal copies across filesystems. |
| A lost answer is resolved from the version of the collection. | The service saves the outcome of each commit request under its request ID. The client asks for that outcome. |
| `GET /api/v1/uploads/{id}` gives the state of an upload. | `GET /api/v1/upload-attempts/{attempt_id}` gives the state and the current upload ID of an attempt. |

These parts of the record stay:

- tus through an unmodified tusd behind nginx with `auth_request`, and the token on every tus
  request.
- The API as the only writer of the share, apart from tusd's own files and the provision commands
  of the storage administrator.
- `LakePath` with no-follow traversal, and no symbolic links in the lake.
- Share groups and modes in place of ACLs.
- The directory verbs, which commit their rows before their disk work.
- The start from an empty lake.

[The operator guide](../operator.md) describes the built system.

## Context

Version 1 copied bytes over the NFS mount from the CLI (ADR 0001, D-18, D-23). Every person who
pushed needed the mount on their machine, and the service trusted the hashes the CLI reported
(D-22). Huron is deployed on OpenShift, where a pod can mount the lake volume, and pushes must work
from machines without the mount. ADR 0001 named HTTP ingest behind the same storage boundary as the
upgrade path.

## Decision

Files are uploaded with the tus resumable-upload protocol to an unmodified
[tusd](https://github.com/tus/tusd) (`tusproject/tusd`). tusd runs in an upload pod of one
replica, behind nginx. nginx is the only container a Service reaches. tusd listens on 127.0.0.1
and keeps its filestore in `${HURON_LAKE_PATH}/.tus-uploads`.

The API holds the writable mount. The API pod and the upload pod mount the lake volume read-write
at `HURON_LAKE_PATH`, both as one fixed UID `U` with the GID `G` of the service group. The API is
the only process that writes the share, apart from tusd's own filestore. There is no sidecar. There
is no task queue for changes on disk.

Huron stays the only authority. nginx sends an OPTIONS request straight to tusd, because tusd's
OPTIONS reads no upload state. nginx sends every other request to tusd only after a header-only
subrequest (`auth_request`) to the API allows it. The API allows a request on an upload only when
the bearer token's user created that upload. nginx keeps an allow for 30 seconds. The cache key
holds the method, the upload id and the `Authorization` value. A request without `Authorization`
never uses the cache. The body streams through nginx to tusd and never through Python. tusd sends
its blocking hooks (`pre-create`, `pre-finish`, `pre-terminate`) with the user's forwarded
`Authorization` header straight to the API. The hooks route needs no shared secret. It
authenticates the token like any other route, and each hook changes only what that user may
change. A NetworkPolicy cannot select an HTTP path, so no NetworkPolicy limits the hooks route.

When an upload finishes, the API places it inside `pre-finish`. First it reads the upload row. A
row that is already `placed` or `committed` gets the stored receipt back, with no work on disk. For
a `pending` row, the API opens `.tus-uploads/<id>`, reads the size and the inode from the open
descriptor, hashes the file, and sets the mode `0644`. The hash runs outside every lock. Then,
under the in-process lock on the destination path, the API hard-links the file to its destination
in the collection directory. A new name gets a link. An overwrite gets a link to a temporary name
and a rename over the old file. The API removes `.tus-uploads/<id>` and `<id>.info` and records a
receipt (size, sha256, inode), still under the lock. When the receipt fails because the collection
was deleted or the upload was terminated during the hash, the API unlinks the file it placed and
refuses the upload. A commit then records only adds that match a receipt of the same user, so the
service verifies hashes instead of trusting them. Only the latest placement of a path counts,
because a later upload replaces the bytes on disk.

The share is read-only for every machine except those of the API pod and the upload pod. The
export does not support POSIX ACLs. So read access on disk comes from plain ownership and modes.
`U` owns everything. Every directory is setgid. Each catalog directory carries one LDAP POSIX
group, its share group, and every directory below it inherits that group from the server when `U`
makes it. A placed file keeps the group `G` of its inode in `.tus-uploads`. Its mode `0644` and the
`2750` directories above it decide who reads it. The storage administrator sets the group of a
catalog directory once, because `U` cannot change a group it is not a member of. The inheritance
of the setgid bit and the group on the ONTAP export is not measured yet. The operator measures it
before the production deployment (Milestone 11, task M11.13), and the API checks each new
directory with a `stat` after `mkdir`.

One rule keeps every disk operation inside the lake (decided 2026-11-08). A place on the disk is a
`LakePath`: a tuple of names below the storage root, each checked by
`schema.naming.check_lake_name`. No absolute path below the lake reaches the API's disk code.
`PosixStorage` opens the root once, opens each parent name with `O_NOFOLLOW` from the descriptor
of the one above, and runs the last step with no follow. The kernel refuses a symbolic link at any
step. The API then answers 409 `SYMLINK_IN_LAKE` and changes nothing. There is no device check,
no mount-point check and no resolve of a path: the mount point never changes, and Huron adds only
organizations, catalogs, namespaces, collections and files. Startup refuses an organization root
that is not the lake path or below it. That is the only check on absolute paths.

The lake contains no symbolic links. Huron makes none: placement uses hard links and `rename`
only. Huron follows none, on writes and on reads. A walk reports a link and never enters it, and
`huron adm check` reports it as an error. The storage administrator removes it. Huron never does.

The directory verbs of the API (create, activate, publish, delete, schema assignment, share
group) write their rows, commit, and then make their change on disk in the same request, through
the one disk-access module `core.storage.Storage`. A failure on disk after the commit keeps the
rows and is repaired with `huron adm repair`. Repair acts only on the directories that the rows
plan, one step per directory, and lists no directory. It makes missing directories and sets
permission bits. It cannot set a setgid bit or a directory group that `U` may not set: that is a
storage-administrator step (`huron adm provision-catalogs`).

A deleted collection's directory is not purged. Its removal removes only what Huron put there
(recorded files, placed uploads, `metadata.json`, partial files, empty subdirectories). Any other
entry leaves the directory in place for the storage administrator.

Every operation that touches more than one row locks in one order. First comes the catalog
advisory lock when the operation takes one, then the collection row, then upload rows, then
removal rows. So the start of an upload, a receipt, a commit and a collection delete run one
after another. A lost race is a not-found error, never a database error. The committing request
unlinks the files it removed. An unlink that fails for a reason other than a missing file leaves
its row for the background task. A background task in the API drains what a request left behind
and sweeps abandoned uploads out of `.tus-uploads`, since tusd never does. A removal unlinks a file
only when its inode is the recorded one. So on one replica, a removal cannot delete a file that a
later placement put at the same path. Across replicas a narrow window remains between the `stat`
and the unlink.

Every organization root is `HURON_LAKE_PATH` or lies below it, on one filesystem, because a hard
link cannot cross filesystems.

Production starts from scratch. There are no directories or files of the old NFS-copy design to
convert. The storage administrator makes each organization root. Huron never makes a root. The
storage administrator then provisions the lake path and each `<root>/<org>` once, with no
recursive owner change, through `huron adm provision-orgs` in direct mode or its printed
script. On that machine the CLI's `mount_prefix` is the lake path. Every later entry is made by
`U` through the API. Apart from the provision commands, the CLI writes nothing to the lake: the
old NFS-copy write path and the ACL code are removed, not kept for compatibility.

## Consequences

Pushing needs only HTTPS. Uploads resume after a broken connection. The service side computes the
hashes. No user can write the share, except root on the nodes of the API pod and the upload pod,
so the share holds only what Huron put there. The export uses AUTH_SYS, which trusts the client's
UIDs: root on any client can read every file. Drift comes only from the storage administrator or
from a disk failure after a commit, which `huron adm check` reports and `huron adm repair` fixes.

Read access on disk is one group per catalog. A catalog without a share group is readable by
nobody but `U`. Finer access than one group per catalog needs a catalog of its own. The group on
disk is a storage-administrator step (`huron adm provision-catalogs`), unless the API pod lists
the catalog groups as supplementary groups (about 14 fit) and resolves their names. The read model
depends on the server-side setgid inheritance that the operator measures.

The API pod mounts the lake and runs with a fixed UID that the export trusts, inside the
namespace's UID range of the restricted SCC. The API now imports the storage code, and only the
storage code imports the filesystem primitives. The install starts from an empty lake: the
storage administrator runs the printed root scripts once. They give the lake path and the
organization roots to `U` and the numeric GID of the service group, set their modes and write the
markers, and no line is recursive. Later they set the group of each catalog's directories. A
complete `huron adm check` needs `U` or an account in `G` and in every share group.
Any other account gets an `unreadable` finding for each entry it cannot read.

The API is now necessary for any change on disk, and it was already necessary for any change at
all. While the upload pod is down, uploads fail and nothing else waits. tusd locks an upload with
a hard-linked lock file that holds tusd's PID. The test that this PID is alive works only inside
one PID namespace. So the upload Deployment runs one replica with `Recreate`, and an init
container deletes old lock files before tusd starts. Two API replicas may place the same path at
the same time. The window between the link and the receipt stays an accepted risk, and
`huron adm check --hash` detects it. The lake is a `hard` NFS mount, so an NFS outage blocks disk
calls without end. The readiness probe has a time limit, so the API pods leave the Service and
browsing stops too.

The upload URL is no longer a credential. The bearer token is, as for every API call. tusd calls
no blocking hook for PATCH or HEAD, so without nginx a leaked upload URL would let anyone append to
or probe an unfinished upload. The upload Route is reachable from the whole company network, and it
can later be exposed to the internet for a consortium project. For this reason, Huron checks the
token on every tus request and does not use tus's default model, where the URL is the credential.
The OpenShift router cannot do this check. An allow stays cached for 30 seconds, and the cache
holds the token value for at most 60 seconds after the last request of that upload and token. A creation reaches tusd before it is authorized, and
`pre-create` refuses it before tusd stores any byte. The final PATCH waits while the API hashes
the file, so the Route timeout (3600 s) and the hook timeout (`upload_hook_timeout`, at most 55
minutes) are long. tusd waits at most `upload_hook_timeout` for a hook, retries included. After a
timeout the API call continues and can still record the receipt. A refused `pre-finish` reaches
the client with the hook's status. A hook that answers 5xx after tusd's retries, or that times
out, reaches the client as a bare 500. The client then reads the state and the reason from
`GET /api/v1/uploads/{id}`. Placed bytes are visible at their final name before the commit, as
with the version 1 push.

A symbolic link in the lake stops the disk work through it. A placement through a link fails
definitively, a directory verb answers 409 with its rows kept, and a repair step reports the link
and the other steps run. Nothing in Huron removes or replaces the link, so the storage
administrator must remove it before the work can succeed. In return, a link planted by root or by
a read-write client cannot steer a write outside the lake or into another catalog, and no
time-of-check to time-of-use gap remains, because the kernel refuses the link at the open. Every
disk operation goes through one module on `LakePath`, so a route cannot build a path of its own.
The descriptor traversal costs one `openat` per name of the path. The design has no data
migration and no compatibility code for the old NFS-copy push, `metadata.json` written by the
CLI, or ACLs.
