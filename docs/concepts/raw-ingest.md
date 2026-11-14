# How raw ingest works

The files of a collection stay on the share, in one directory for each collection. The service
writes the share, apart from the provision commands of a storage admin. These prepare the
organization directories and give the catalog directories their share groups. The CLI uploads your staged files through an
upload proxy to tusd, and the service seals each upload. Then one commit names the sealed uploads,
and the service puts the files into the directory of the collection. The service records the size
and the SHA-256 hash of each file, and the share holds the bytes. This page tells how each step
works and what Huron checks before it writes.

## The layout of the share

Each organization has one directory, `<root>/<org>`. The root comes from the service configuration.
An organization without a root is directly below the lake path of the service. On your machine,
the CLI finds it below its `mount_prefix`, which is `/projects/huron` by default. Below the directory of the organization, each catalog, namespace and collection has its own
directory:

```text
<root>/<org>/<catalog>/<namespace>/.../<collection>/

/data1/huron/                     root of the organization
  helio/                          organization, with its .huron marker
    heliophysics/                 catalog
      solar-wind/                 namespace
        ace/                      namespace that allows collections
          run7/                   collection
            metadata.json         sidecar that the service writes
            kp/q1.txt             a recorded file
```

The API gives each path relative to the root, and the path starts with the name of the
organization, as in `helio/heliophysics/solar-wind/ace/run7`. The CLI finds the root of the
organization from the first segment of that path. A path with an empty segment, `.` or `..` is
outside the share, and Huron refuses it.

Inside a collection, a file has a relative path, such as `kp/q1.txt`. Huron ignores case when it
checks path uniqueness. Thus it cannot record `Data.h5` and `data.h5` as separate files. This rule
does not change how the filesystem treats names. Keep the recorded spelling when you replace a file.

Some names belong to Huron: `metadata.json` at
the top of the collection, any segment that starts with `.huron`, and any segment that ends with
`.huron-part`. Other names belong to the storage and to NFS clients: a segment named `.snapshot`
and any segment that starts with `.nfs`. You cannot stage a file with one of these names. In a
directory, `huron add --recursive` does not stage an entry named `.snapshot` or `.nfs*`, and does
not look into it. It gives a warning for each one.

A relative path has at most 1,024 UTF-8 bytes, with at most 206 bytes in each segment. It uses `/`
between segments and has no leading or trailing `/`. Huron refuses empty segments, `.` and `..`,
backslashes and control characters. Unicode names must use NFC normalization, a standard form for
equivalent characters.

[Where your files are](../user-guide.md#where-your-files-are) tells how to find the directory of
an organization on your machine.

## The marker

The marker is the `.huron` file in the directory of an organization. It is a small JSON document
with the fields `huron`, `api_url`, `instance_id` and `organization`. A storage admin writes it
with `huron adm provision-orgs`. An organization without a root that the configuration does not
declare uses the marker at the lake path. That marker names only the instance.

Before the service does a disk action in a directory of an organization, it reads the marker that
guards it. The CLI does the same before it reads the share. Each refuses the operation unless these
conditions are true:

- The directory exists, and its marker exists and is readable.
- Its `instance_id` is the instance id of the service, which `GET /healthz` gives.
- The marker of an organization names that organization. The marker at the lake path names no
  organization.

The check stops two mistakes. A service or a CLI that points at a test service cannot use the
directories of the production service. An export that is mounted at the root of another
organization cannot get files of the wrong organization. The service answers such a refusal with
503 `LAKE_UNAVAILABLE`. Each command of the CLI that reads the share reports a refusal in its own
way:

- `huron status` says that the share is not mounted on this machine, and it does not look for
  unrecorded files. It does so for each refusal.
- `huron adm verify-mounts` shows the state `missing`, `no marker`, `wrong instance` or
  `wrong org`, and exits with code 1. A symbolic link, or a marker that the account cannot read,
  has no state. The command then stops with that error (`SYMLINK_IN_LAKE` or `STORAGE_FAILED`)
  and exit code 8. For a symbolic link at an organization with its own marker, the exit code is
  1.
- `huron adm check`, for an organization with its own marker, reports `org_dir_missing`,
  `org_marker_missing` or `org_marker_mismatch` and skips its catalogs. A symbolic link at the
  organization directory or at its marker gives `symbolic_link`, and the check skips its catalogs
  too. A marker that the account cannot read gives `unreadable`, and the check still checks the
  catalogs. With findings, the check exits with code 1. When the marker at the lake path refuses,
  the check stops with exit code 2.

[Adding an organization](../operator.md#adding-an-organization) tells how a storage admin prepares
the directory and the marker. [The mount prefix](../operator.md#the-mount-prefix-for-organizations-without-a-root)
tells how to mark the lake path.

## Creating and activating a collection

`huron create collection` makes the collection and its directory in this sequence:

1. The service reserves the name. The collection is a draft at version 1.
2. The CLI asks for the metadata, or it reads `--metadata file.json`.
3. The CLI asks the service to activate the collection. The request carries the version of the
   collection. The service activates the collection only when its metadata satisfies the schema.
4. After the activation, the service creates the directory of the collection in the directory of
   its namespace. The directory gets mode `2750` and inherits the group of its parent.
5. The service writes the `metadata.json` document into the directory.
6. The CLI records a working copy and selects it as the current collection.

With `--draft`, the CLI stops after step 2. The draft becomes the current collection.
`huron activate collection` does steps 3 to 6 later.

The service commits the activation before it creates the directory. When the disk work then
fails, the collection stays active, and the command stops with the error, for example
`STORAGE_FAILED`. The hint names `huron adm repair`, which makes the directory and writes
`metadata.json`. The error can say that the directory exists and is not empty. Then look at that
directory first: the repair takes the directory with the files in it.

The service user owns the collection directory. The directory inherits its group through setgid,
not through ACLs or API grants. Workstations mount the share read-only.
See [Directory modes and share groups](access-and-roles.md#directory-modes-and-share-groups) for the access rules.

## The working copy and the stage

The CLI keeps its own state under `$XDG_STATE_HOME/huron`, which is `~/.local/state/huron` by
default. Each working copy has a directory there, `collections/<collection id>/`, with these files:

| File | Contents |
| --- | --- |
| `working.json` | A format version, the id and identifier of the collection, the path of its directory, the version that the working copy holds, and the stage. Each staged add has the path in the collection, the absolute path of the local file, its size, its `sha256` and its upload attempt. |
| `metadata.draft.json` | Your metadata draft, when you have one. |
| `push.lock` | The lock that a push holds. |

To change `working.json` or `metadata.draft.json`, the CLI writes a new temporary file first. It
syncs that file, renames it over the old file and syncs the directory.
The files have mode 0600. The CLI creates the directories with mode 0700. The current collection
is in the CLI configuration, `$XDG_CONFIG_HOME/huron/config.yaml`.

The working copy holds no copy of your files. It holds the version of the collection, the stage
and your metadata draft. `huron checkout` records a working copy and keeps the stage of each working
copy.

## Staging files

`huron add` and `huron rm` change only the stage. They do not touch the share.

`huron add <file>` stages the file at its own name in the collection. `--as <path>` gives one file
another path. `huron add <directory> --recursive` stages each file in the directory, at its path
relative to that directory. The CLI makes these checks:

- It refuses a symbolic link that you name. It does not stage a symbolic link inside a directory.
- It refuses a path that breaks a path rule, such as a reserved name.
- When you stage a path again, the new add replaces the old one and unstages a removal of that path.

The CLI reads each file when you stage it, and records its size, its modification time and its
SHA-256 hash.

`huron rm <path>` unstages an add or a removal of that path. When nothing is staged for a recorded
file, `huron rm` stages its removal. The CLI asks the service which files it records. A path that
is neither recorded nor staged is an error.

[Staging and pushing files](../user-guide.md#staging-and-pushing-files) shows the commands with
examples.

## The push, step by step

`huron push` uploads the staged files through the upload proxy and tusd, and records them in one
commit:

```text
huron push
  |
  |-- read the collection ---- other version? --> stop, BASE_VERSION_CONFLICT
  |-- dry-run commit --------- refused? --------> stop, nothing uploaded
  |-- for each add:  check the local file, create a tus upload,
  |                  send the bytes in chunks of at most 64 MiB,
  |                  wait until the service sealed the upload
  |-- save the commit, then send it (request_id, base_version, adds, removes, host)
  |-- 202? read the state of the request until it ends
  '-- clear the stage, record the new version
```

These are the steps:

1. The CLI takes the push lock of the working copy. When another push of the same working copy
   holds the lock, the push stops.
2. The CLI reads the collection from the service. When its version is not the version of the
   working copy, the push stops with `BASE_VERSION_CONFLICT`. When the collection is a draft, the
   push stops too.
3. The CLI sends the commit to the service as a dry run. Each add carries its path, its size and
   the `sha256` that `huron add` recorded. An add whose upload an earlier push sealed also carries
   its upload ID.
4. For each staged add, the CLI checks the size and the modification time of the local file. A
   changed file stops the push with exit code 2.
5. The CLI records a new upload attempt in the stage. Then it creates a tus upload at the
   `uploads_url` of the service, and sends the bytes. Each request carries the Huron token of the
   user, and the upload proxy asks the service to authorize it.
6. The service seals the upload. It copies the bytes into the object area of the organization,
   syncs the copy, and measures its size and its SHA-256 hash.
7. The CLI saves the commit in the working copy, with a new request ID. Then it sends the commit:
   `request_id`, `base_version`, `adds`, `removes`, `host` and the optional `message`. Each add has
   `rel_path`, `size`, `sha256` and `upload_id`.
8. The service accepts the commit and puts each file on the share. The answer is 200, or 202 when
   the commit does not end within 5 seconds. After a 202, the CLI reads the state of the request
   every 5 seconds, for at most 600 seconds.
9. The CLI clears the stage and records the new version in the working copy.

The dry run does all the checks of a real commit, and it changes nothing. The service checks your
right to write files, the state of the collection, the paths, the removed files, the base version
and the file tree. When the service refuses the dry run, the push stops before it sends one byte.
The share and the stage do not change.

The dry run reserves no version and holds no lock during the upload. Another client can change the
collection before the real commit. The service checks the version again when that commit arrives.
The uploads of a refused commit stay `ready`, and the stage keeps them for the next push.

The service never trusts the hash of the CLI alone. It compares the SHA-256 that it measured at
the seal with the `sha256` of the add. When the two are not equal, it refuses the commit with
`UPLOAD_INELIGIBLE`. The service refuses a commit with more than 10,000 entries, adds and removals
together.

**How the service puts the files on the share.** No file in the directory of the collection changes
before the service accepts a commit. Then the service does one step for each entry, in a fixed order:

- A new or replaced file: a hard link from the sealed object to a temporary name
  `.<name>.<upload ID>.huron-part`, then a rename over `<name>`. A reader sees the old file or the
  new file, never a part of it.
- A removed file: an unlink.
- A directory that the commit needs or makes empty: a `mkdir` or a removal.

After the last step, one database transaction records the files and the new version. Until then,
the service shows the files of the last commit that succeeded. The directory on the share can then
hold a mix of old and new files.
[Publication of a commit](../operator.md#publication-of-a-commit) tells more.

## When a push stops

A push can stop at different points. The result is different for each point:

- **Before the upload.** The checks of steps 2 to 4 change nothing. Correct the cause and push
  again.
- **During an upload.** The stage records each upload attempt. The next push asks the service for
  the state of each upload. It sends only the bytes that the service does not have, and it does not
  send a file again when the service sealed it.
- **When the service refuses the commit.** Nothing on the share changed. The uploads stay `ready`,
  and the stage keeps them. The CLI shows the error of the refusal. Correct the cause and push
  again. The next push uses a new request ID.
- **When the commit gets no answer.** The commit stays saved in the working copy, with its request
  ID. The next `huron push` asks the service for the result of that request. The CLI never guesses
  the result.
- **When a step of the commit is blocked.** The service found an entry on the share that the commit
  does not expect, and it changed nothing there. The push waits up to 10 minutes for the request,
  then stops with exit code 6 and `PUBLICATION_BLOCKED`. A platform admin must resolve the commit
  request.

[Continuing an interrupted push](../user-guide.md#continuing-an-interrupted-push) tells what the
CLI keeps and what to do in each case.

## Base version conflicts and huron pull

Each commit carries the version of your working copy as its `base_version`. The service locks the
collection row and compares the base version with the current version. When they are not equal,
it refuses the commit with `BASE_VERSION_CONFLICT`, status 409. The CLI exits with code 6 and the
hint ``run `huron pull` ``. Each commit and each metadata change increases the version, also when
another person makes it.

`huron pull` reads the current version of the collection from the service and records it in the
working copy. It keeps your staged adds. It unstages each staged removal of a file that the service
no longer records, and it prints a warning for each. `huron pull` does not copy files to your
machine. Then run `huron push` again.

The lock belongs to one local working copy. It does not lock the collection for other users or
machines. `huron pull` updates your base version but does not merge file contents. Check the
current files before you repeat a push that replaces an existing path.

[When someone else changed the collection](../user-guide.md#when-someone-else-changed-the-collection)
shows the error and the commands.

## What the service records

The service accepts a commit in one database transaction, or it refuses all of it. After the
steps on the share, one more transaction records the commit. That transaction does these
changes:

- It records one row for each added file: the path, the size, the SHA-256 hash, the time, the user,
  the commit and the sealed object. An add of a path that is already recorded replaces the row of
  that path.
- It removes the row of each removed file.
- It increases the version of the collection by 1 and sets its file count.
- It records the commit: the base version, the new version, the number of adds and removals, the
  host, the message and the user.
- It writes an audit entry for the commit. `huron get log` shows the audit entries of a collection.

Thus the service has one row for each current file. Huron keeps no older copies of file contents.
The share holds only the current files. When a push replaces a file, the old bytes are gone from
the share, and Huron cannot recover them. The snapshot policy of your storage team recovers files.
Refer to [Backups and recovery](../operator.md#backups-and-recovery).

## The metadata.json sidecar

The metadata is in PostgreSQL, and the service is its source of truth. The service also writes a
copy, `metadata.json`, into the directory of each collection that is not a draft. Thus the
information stays next to the files, also without the service.

The document holds the identifier, the organization, the catalog, the schema, the schema override,
the metadata, the creator and the time of creation. It does not hold the version or the file
count, so a push does not make it stale.

The service writes the sidecar at activation. It writes the sidecar again after each change of the
metadata or the schema override, such as `huron publish meta` or `huron set override`. A schema
assignment of the catalog also writes it. `huron adm check` reports `sidecar_stale` when the file is
missing or does not agree with the document of the service. `huron adm repair` writes it again.

## Drift detection

`huron adm check` compares what the service records with what the share holds. It first checks the
directory and the marker of each organization. It does not check ACLs: Huron uses none.
Then it checks each catalog that you can read, or only the catalog of `--catalog`.

A declared organization and an organization with its own root need a marker in their own
directory. The check skips the catalogs of such an organization when its directory is missing or
is a symbolic link. It also skips them when that marker is missing, is a symbolic link or is wrong.
Other findings in the organization directory do not stop the check of its catalogs.

These findings concern raw ingest:

| Finding | Meaning |
| --- | --- |
| `file_missing` | The service records a file that is not on the share. The check does not report a recorded file below a directory that it cannot read. |
| `file_changed` | The size of the file is not the recorded size. With `--hash`, also: the SHA-256 hash is not the recorded hash. |
| `file_unrecorded` | A file in the directory of a collection that no commit records, or a file directly in a catalog or namespace directory. |
| `stale_part` | Information: a `.huron-part` file in a collection, older than one hour. It is the temporary name of a stopped publication, or the part file of a stopped write of `metadata.json`. |
| `sidecar_stale` | `metadata.json` is missing or does not agree with the service. |
| `pending_commit` | Information: a commit request holds the collection. Until the request ends, the directory can hold old and new files, so the check does not compare the files. |
| `nfs_file` | Information: a `.nfs*` file, which an NFS client keeps for a removed file that a process holds open. A collection cannot record a `.nfs*` name, so the check does not compare this file with a record. |
| `snapshot_dir` | Information: a `.snapshot` directory, in which the storage can show its snapshots. A collection cannot record a path with a `.snapshot` segment, so the check does not read this directory. |

Without `--hash`, the check compares only the size of each file. Thus it does not find a change
that keeps the size. `huron adm check --hash` reads each file and calculates its hash. The command
exits with code 1 when it has findings. It exits with code 2 when it cannot use the share, for
example when the share is not mounted.

The check only reads the share. It does not remove or change an entry that it reports, or any
other entry. An entry that the account cannot read is an `unreadable` finding, and the check
continues. The object area `.huron-objects` of an organization is the exception: its mode is
`0700`, so only the service user can list it. As the service user, the check reports its probe
files, links and entries that it cannot stat. For every other account, the check skips the object
area with no finding.

The check does not repair directories. API grants and the catalog's filesystem share group are separate.
A grant change does not change directory permissions. The API repair endpoints use database rows to plan directory work, not a filesystem scan.
Missing setgid bits or wrong groups below a catalog need the storage administrator.

[`huron adm repair`](/docs/reference/cli/adm/#huron-adm-repair) calls the API repair endpoints.
[`huron adm provision-catalogs`](/docs/reference/cli/adm/#huron-adm-provision-catalogs) is the step of the storage administrator for the setgid bits and the groups.
See [Grant changes and directory repair](access-and-roles.md#grant-changes-and-directory-repair) before requesting repair.

[Reading huron adm check](../operator.md#reading-huron-adm-check) tells what to do for each
finding.

## The trust model

Huron contains and detects mistakes. It does not prevent all of them. Workstations mount the share read-only,
and API privileges control writes through Huron. Directory modes and share groups control filesystem reads.
AUTH_SYS trusts client user IDs, so these permissions do not protect against root on an authorized client.

The service measures the size and the SHA-256 hash of each upload itself, when it seals the
upload. A commit names the sealed uploads, and the service refuses an add whose hash is not the
hash of its upload. After the commit, `huron adm check` finds a changed file when its size changed.
Only `huron adm check --hash` compares the contents.

Huron uses no ACLs. Directory modes and share groups control filesystem read access independently of API grants.
The CLI reports drift but does not change those directory permissions.

## Related pages

- [User guide](../user-guide.md): staging, pushing and pulling, with examples.
- [Glossary](../user-guide.md#glossary): the Huron terms on this page.
- [`huron push`](/docs/reference/cli/push/), [`huron add`](/docs/reference/cli/add/),
  [`huron rm`](/docs/reference/cli/rm/) and [`huron pull`](/docs/reference/cli/pull/).
- [`huron adm check`](/docs/reference/cli/adm/#huron-adm-check): report drift without changing the share.
- [Reading huron adm check](../operator.md#reading-huron-adm-check): what to do for each finding.
- [API error codes](../api-errors.md): `BASE_VERSION_CONFLICT`, `COMMIT_INVALID` and others.
- [How Huron works](how-huron-works.md): the parts of Huron and the collection lifecycle.
- [Directory modes and share groups](access-and-roles.md#directory-modes-and-share-groups): the
  permissions of each directory.
