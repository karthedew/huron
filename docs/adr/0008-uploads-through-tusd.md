# Uploads through tusd, placed by the Huron API with hard links

Status: accepted (2026-11-06). Supersedes [0001](0001-nfs-only-storage.md).

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
before the deployment (Milestone 11, task M11.11), and the API checks each new directory with a
`stat` after `mkdir`.

The directory verbs of the API (create, activate, publish, delete) resolve their path inside the
lake before the transaction. Then they write their rows, commit, and make their change on disk in
the same request. A failure on disk after the commit keeps the rows and is repaired with
`huron adm repair`. Repair makes missing directories and sets permission bits. It cannot set a
setgid bit or a directory group that `U` may not set: that is a storage-administrator step
(`huron adm provision-catalogs`).

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

Every organization root that accepts uploads lies below `HURON_LAKE_PATH`, on one filesystem,
because a hard link cannot cross filesystems.

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
namespace's UID range of the restricted SCC. The API now imports the storage code. Directories of
version 1 belong to their users and carry the modes of version 1 (`2770` directories, `0660`
files). The storage administrator runs the printed root scripts once: they give everything to
`U` and the numeric GID of the service group, set the modes, and set the group of each catalog's
directories. A complete `huron adm check` needs `U` or an account in `G` and in every share group.
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
