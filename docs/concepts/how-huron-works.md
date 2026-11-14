# How Huron works

Huron catalogs raw scientific data that is on an NFS share, and it controls who can read and write
that data. A service keeps the catalog, the metadata and the roles in PostgreSQL. The `huron` CLI
uploads your files to the service. The service puts them on the share and records them in a
commit. The web shows the same catalog in a browser and makes no changes. This page gives the big picture. The [user guide](../user-guide.md)
and the [CLI reference](/docs/reference/cli/) give the details, and the
[glossary](../user-guide.md#glossary) defines the Huron terms.

## What Huron is for

Your data stays in directories on the share. Huron gives each set of files a place in a catalog,
with metadata that the schema of the catalog checks. You find data with `huron tree`,
`huron search` or the web. You read the files directly from the share.

Roles belong to LDAP groups, never to people. The service checks your role for each request. On
the share, Huron uses no ACLs. A catalog can have one share group. The members of that group read
the files of the catalog over the mount. Without a share group, only the service user and the
service group read them
([Directory modes and share groups](access-and-roles.md#directory-modes-and-share-groups)).

The service writes the share. It makes the directories, and it puts each file of a commit on the
share. With the provision commands, a storage admin prepares the directory of each organization
and gives each catalog directory its share group. You mount the share read-only. Root on an NFS
client can still change the share outside Huron, and Huron does not prevent this. `huron adm check` reports the files that no
commit recorded and the other places where the share and the catalog do not agree.

A collection has one version number, which counts its changes. When you push a file to a path that
a commit recorded before, the new file replaces the old file. Huron keeps no earlier copy.

## Organizations, catalogs, namespaces and collections

Huron has four levels. This example shows one collection and its directory, for an organization
with the root `/data1/huron`:

```text
organization  helio
└─ catalog    heliophysics          one metadata schema
   └─ namespace  solar-wind
      └─ namespace  ace             allows collections
         └─ collection  run7

identifier:  heliophysics.solar-wind.ace.run7
directory:   /data1/huron/helio/heliophysics/solar-wind/ace/run7/
```

- An **organization** is the top level. It holds catalogs and has its own directory on the share.
- A **catalog** is a tree of namespaces and collections in one organization. It has one metadata
  schema.
- A **namespace** is a level in a catalog. It holds other namespaces. It holds collections only when
  it allows them.
- A **collection** is a set of files in one directory on the share, with its metadata.

Only collections hold data files. A collection belongs to one namespace, and it cannot contain
another collection. A namespace can hold child namespaces and collections together when it allows
collections. A catalog supplies the metadata schema and access rules for every collection below it.

An identifier names a namespace or a collection. It is the catalog, the namespaces and the name,
with dots between them. The organization is not part of the identifier. It shows only in the
directory path.

Catalog names and organization names are unique in the service. A namespace and a collection never
have the same name under one parent. Each name uses lowercase letters, digits, `-` and `_`, and
starts with a letter or a digit. Huron reserves the names `huron` and `metadata`.

Each name has at most 63 bytes, and a full identifier has at most 255 bytes. A display name or a
metadata title can use spaces and uppercase letters. Changing a title does not change the
identifier or the directory. Huron does not move or rename organizations, catalogs, namespaces or
collections.

The CLI reads an identifier relative to the current catalog first. When that identifier names
nothing in the current catalog, the CLI reads it as written. Thus `solar-wind.ace.run7` and
`heliophysics.solar-wind.ace.run7` name the same collection while `heliophysics` is current.
[Finding your way](../user-guide.md#finding-your-way) shows how to select the current catalog.

## The three parts

Huron has three parts. The service writes the share:

```text
 your machine                                 service
+----------------------------+   HTTPS   +-------------------------+
| huron CLI                  | --------> | huron-api               |
| uploads files, commits     |           | upload proxy and tusd   |
+----------------------------+           +-------------------------+
              ^                                 |              |
              | reads, with a                   | writes       |
              | read-only mount                 v              v
+------------------------------------------------+   +------------------+
| share: <root>/<org>/...                        |   | PostgreSQL       |
+------------------------------------------------+   +------------------+

 browser ---> huron-web (read-only, and /docs) ---> huron-api
```

| Part | Runs on | Does |
| --- | --- | --- |
| `huron-api` and PostgreSQL | OpenShift, or a managed PostgreSQL | Keeps organizations, catalogs, namespaces, collections, recorded files, schemas, role grants and the audit log. It takes uploads through an upload proxy and tusd, makes the directories and puts each committed file on the share. |
| `huron` CLI | your machine | Uploads files, records them in commits and asks the service to make directories. On a machine that mounts the share, it also checks the share against the catalog. |
| `huron-web` | a Node.js server | Shows the catalog in a browser and makes no changes. It also serves this documentation at `/docs`, with no sign-in. |

You log in to the CLI with `huron login` and to the web with the same company account. The service
puts your LDAP groups into your Huron token when you log in. Each request maps those groups to
roles through the current grants. Thus a revoked grant applies at once. A change to your LDAP
groups applies at your next login. An object that you cannot see answers as not found.

## Who does what

Operators run the service and the web. They can declare the organizations in the service
configuration (see [Configuration](../operator.md#configuration)). A storage admin prepares the directory of each
organization on the share. The other work belongs to five roles:

| Role | Can do |
| --- | --- |
| Platform Admin | Every privilege. Creates organizations in unmanaged mode and publishes platform schemas. |
| Org Admin | Creates catalogs, grants the Catalog Admin role and publishes organization schemas. |
| Catalog Admin | Creates namespaces, assigns the schema of the catalog, grants the Reader and Contributor roles and deletes any collection. |
| Contributor | Creates collections, edits metadata, pushes files and deletes a collection that the same user created. |
| Reader | Browses, searches, reads files and reads the audit log. |

A group can hold the Catalog Admin, Contributor or Reader role on one catalog or on every catalog
of an organization. `huron whoami` shows your
groups and their roles. [Who has access](../user-guide.md#who-has-access) explains `huron get grants`.

## Organizations and their roots on the share

Operators can declare each organization in the service configuration. The entry gives the name,
the LDAP groups of the organization-wide roles and, as an option, a root. The directory of the
organization is `<root>/<name>`. An organization without a root is directly below the lake path
of the service. On your machine, it is below the `mount_prefix` of the CLI, by default
`/projects/huron`, where your machine mounts the lake path.

```text
service configuration              directory of the organization
  helio  root: /data1/huron  --->  /data1/huron/helio/
  geo    root: /data1/huron  --->  /data1/huron/geo/
  astro  (no root)           --->  <lake_path>/astro/, on your machine <mount_prefix>/astro/
```

The storage admin prepares each declared organization with `huron adm provision-orgs`. The
command creates the directory when it is missing, gives it the service user and the service group,
and writes the marker `.huron`. The marker names the instance of the service and the organization.
`huron adm verify-mounts` shows the state of each organization on your machine.

The service and the CLI check the marker of each declared organization, including one without a
configured root. The marker must name this instance and this organization. Only an organization
that is neither declared nor rooted uses the marker at the lake path. That marker names only the
instance.

An `organizations` key in the service configuration selects managed mode, even when its list is
empty. In managed mode, the service refuses `huron create org`. It also
refuses to delete a declared organization or to change its organization-wide groups. When operators
delete an organization from the configuration, the organization and its catalogs stay.

The service no longer knows the root of that organization. The CLI then looks under the mount
prefix only. To restore access to a directory at another root, operators declare the organization
again with that root. Without an `organizations` key, platform admins create organizations with
`huron create org`, under the mount prefix.
[Declared organizations](../operator.md#declared-organizations) gives the details for operators.

## The collection lifecycle

A collection is in one of three states:

```text
          create            activate
(none) ----------> draft ------------> active <------> incomplete
                     |                   |                 |
                     +----------------- delete ------------+
                                          |
                                          v
                          the record goes, the audit log stays
```

- **draft**: Huron reserved the name. The metadata can be invalid. A draft has no directory, so you
  cannot push files to it. Lists and searches show drafts only to users who can create collections
  in the catalog.
- **active**: the metadata satisfies the schema. The collection has a directory and takes pushes.
- **incomplete**: the collection has a directory, but its metadata does not satisfy the schema any
  more. Pushes still work.

`huron create collection` reserves the name and asks for the metadata fields, or reads them from
`--metadata`. Then it asks the service to activate the collection. The service activates it,
creates its directory and writes `metadata.json` there. The CLI selects the collection as the
current collection.

With `--draft`, it stops before the activation, and the draft becomes the current collection. Later, `huron activate collection` activates the draft. Activation needs metadata that
satisfies the schema. [Creating a collection](../user-guide.md#creating-a-collection) lists each step.

A collection becomes incomplete when an administrator assigns a new schema to the catalog. Huron
then checks each active and incomplete collection against the new schema. A collection that fails
becomes incomplete, and a collection that passes becomes active. When you publish metadata that
satisfies the schema, an incomplete collection becomes active again.

Active and incomplete collections never return to draft. These states describe metadata validity,
not whether files are present or correct. An active collection can be empty. File checks belong to
[`huron adm check`](raw-ingest.md#drift-detection).

The creator of a collection or a Catalog Admin can delete it. `huron delete collection` commits the
removal of the recorded files, then deletes the collection and its directory. A file that no commit
recorded stays, and the directory then stays too. `huron adm check` reports it. The audit log keeps
the history of the collection.

The version number detects changes since a client last read the collection. It does not identify a
saved copy of the files. A commit records file changes, and the audit log records actions. Neither
provides an earlier copy of the data. The storage team's snapshots provide file recovery.

## The working copy

`huron checkout` records a working copy of one collection on your machine. The working copy holds
the version of the collection, the stage and your metadata draft. It holds no files. `huron add`
stages the path of a local file, and `huron push` uploads that file to the service. Each working
copy has its own stage, and `huron checkout` selects which one is the current collection.

Each push carries the version of your working copy. When someone changed the collection after that
version, Huron refuses the push, and the CLI uploads nothing. Then run `huron pull` and push
again. Your staged adds stay staged.
[Staging and pushing files](../user-guide.md#staging-and-pushing-files) explains the stage and the
push.

## A day in the life

This example follows one contributor from login to the web. Do these steps:

1. Log in. The first time, set the address of the service and the issuer (see
   [Logging in](../user-guide.md#logging-in)).
2. Select the organization and the catalog.
3. Find a collection with `huron tree` or `huron search`.
4. Check out the collection.
5. Stage your files and look at the stage.
6. Push the files with a message.
7. Open the collection in the web.

```bash
huron login                              # 1. log in with your company account
huron org helio                          # 2. select the organization
huron catalog heliophysics               #    select the catalog
huron tree                               # 3. the namespaces and collections
huron search -q "parker"                 #    or search the metadata
huron checkout solar-wind.ace.run7       # 4. make it the current collection
huron add data/*.h5                      # 5. stage local files
huron status                             #    what the next push holds
huron push -m "first run"                # 6. upload and commit
```

The push does these steps:

```text
huron push
  1. ask the service if it accepts the commit   (refused: nothing is uploaded)
  2. upload each staged file through the upload proxy
  3. commit: the service puts the files on the share,
     records them and adds 1 to the version
```

For step 7, open the address of the web and sign in with the same company account. Go to the
collection. The web shows its metadata, its files, its commits and its activity. Where you can make
a change, the page shows the `huron` command to run. [In a browser](../user-guide.md#in-a-browser)
tells what else the web shows.

## Related pages

- [User guide](../user-guide.md), with the [glossary](../user-guide.md#glossary)
- [CLI reference](/docs/reference/cli/), for example
  [`huron checkout`](/docs/reference/cli/checkout/) and [`huron push`](/docs/reference/cli/push/)
- [API error codes](../api-errors.md)
- [Configuration](../operator.md#configuration) and
  [Adding an organization](../operator.md#adding-an-organization), for operators
- The other concept pages: [How raw ingest works](raw-ingest.md),
  [How search works](search.md), [Metadata and schemas](metadata-and-schemas.md),
  [Access and roles](access-and-roles.md) and [Architecture](../architecture.md)
