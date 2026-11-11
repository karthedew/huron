# API error codes

Every error is an RFC 9457 `application/problem+json` document. The document has the fields
`type`, `title`, `status`, `detail`, `code` and `context`. The CLI maps each code to an exit code
(see the user guide).

| Code | Status | Meaning |
| --- | --- | --- |
| `ATTEMPT_ID_CONFLICT` | 409 | A creation has the `attempt_id` of an earlier upload attempt, but a different collection, path or size. `context.attempt_id` names the attempt. Use a new `attempt_id` for a new upload. |
| `BASE_VERSION_CONFLICT` | 409 | The base version of the commit is not the current version of the collection. Run `huron pull`. `context.current_version` names the current version. |
| `CAPACITY_EXCEEDED` | 429 | The service does not have the space for the upload now. `context.limit` names the limit that stops the upload. `context.requested` and `context.available` give the numbers of bytes. When tusd's file and its copy are on one filesystem, the upload needs two times its size there, and `context.requested` is that number. Send the upload again later. |
| `CATALOG_NOT_EMPTY` | 409 | The catalog still has namespaces. |
| `COLLECTIONS_NOT_ALLOWED` | 409 | The namespace does not allow collections. |
| `COLLECTION_BUSY` | 409 | The collection has a pending commit. A collection accepts one commit at a time. A delete of the collection also gets this code. Wait until the pending commit ends. Then send the commit again with a new request ID. The request ID of the refused commit keeps this refusal. A refused delete can be sent again. |
| `COLLECTION_NOT_EMPTY` | 409 | The collection still has recorded files. |
| `COMMIT_INVALID` | 422 | The commit body breaks a rule of a commit. It breaks a path rule, it has the same path twice, or two adds name one upload. Or an add is inside a file that the commit adds. Or an add is inside a recorded file that the commit keeps. Or an add has the path of a directory that contains a recorded file that the commit keeps. The commit keeps each recorded file that `removes` does not name and that no add replaces. For these last three causes, `context.rel_path` names the add and `context.other` names the other file. |
| `COMMIT_REQUEST_NOT_FOUND` | 404 | The commit request does not exist, or a different user sent it. `context.request_id` names the request. |
| `COMMIT_TOO_LARGE` | 413 | The commit has more than 10,000 entries. |
| `DEPENDENCY_UNAVAILABLE` | 503 | A dependency is unreachable, for example the database or the identity provider. |
| `FILE_NOT_RECORDED` | 422 | A path in the `removes` list of the commit is not a recorded file. |
| `FORBIDDEN` | 403 | The caller does not have the necessary privilege. `context.privilege` names the privilege. |
| `GROUP_DIRECTORY_UNAVAILABLE` | 503 | The LDAP group directory could not answer during the token exchange. |
| `INTERNAL` | 500 | An unexpected error occurred. `context.request_id` matches the service log. |
| `INVALID_CURSOR` | 400 | This listing did not produce the paging cursor. |
| `LAKE_UNAVAILABLE` | 503 | The API cannot write the lake. `lake_path` does not open as a directory, or the API cannot write it. Or the marker that guards the organization is missing or names a different instance or organization. Or a different API process holds the writer lock, so this process does not write the lake. `context` names the path or the reason. A repair route of a service without `lake_path` also answers it. |
| `METADATA_INVALID` | 422 | The metadata does not satisfy the schema of the collection, or it has a value that JSON cannot hold (rule `json`). NaN, infinity and a lone surrogate are such values. `context.problems` lists each problem. |
| `NAMESPACE_NOT_EMPTY` | 409 | The namespace still has child namespaces or collections. Draft collections count. |
| `NAME_INVALID` | 422 | A name breaks a naming rule. `context.rule` names the rule. |
| `NAME_TAKEN` | 409 | Another organization, catalog, sibling namespace or collection uses the name. |
| `NOT_FOUND` | 404 | The object does not exist, or the caller cannot see it. |
| `ORGANIZATIONS_MANAGED` | 409 | The service configuration declares the organizations, so the API cannot create an organization. Use `huron adm provision-orgs` to prepare the declared organizations. |
| `ORGANIZATION_DECLARED` | 409 | The service configuration declares the organization. The API cannot delete it. Its role groups at organization scope (`org_admin`, `catalog_admin`, `contributor` and `reader`) are the `groups` in its declaration. Delete its declaration from the service configuration, or change `groups.<role>` in the service configuration. |
| `ORGANIZATION_NOT_EMPTY` | 409 | The organization still has catalogs. |
| `PRECONDITION_REQUIRED` | 428 | A request that writes to a collection needs an `If-Match` header with the quoted version of the collection. |
| `PUBLICATION_BLOCKED` | 409 | A step of an accepted commit found an entry on the lake that the commit does not expect. The API did not change that entry. The commit request is blocked until a platform administrator resolves it. The refusal of the request has this code. `context.ordinal` names the entry of the request, `context.path` names the entry on the lake and `context.reason` tells what the step found. The reasons are `foreign_entry`, `directory_missing`, `directory_not_empty`, `object_missing`, `symbolic_link` and `inode_unknown`. The reason `inode_unknown` means that Huron does not know the inode of a file to delete, so it cannot tell that file from a different file. |
| `REQUEST_ID_CONFLICT` | 409 | The commit has the request ID of an earlier commit, but a different body. Use a new request ID for a new commit. `context.request_id` names the request. |
| `REQUEST_INVALID` | 422 | The request is not valid, or it names something that Huron does not accept. `context` tells what is wrong. |
| `SCHEMA_INCOMPATIBLE` | 422 | A schema contradicts the schema that it extends. It changes the type of a required property, or it has no base schema. |
| `SCHEMA_INVALID` | 422 | A schema document is outside the allowed subset of JSON Schema, or it has a value that JSON cannot hold (rule `json`). |
| `SCHEMA_SCOPE` | 422 | A catalog or a schema uses a schema of a different organization. |
| `STATE_CONFLICT` | 409 | The state of the object does not allow the operation. `context.state` and `context.allowed` tell why. A conflict of a commit request names the request in `context.request_id`. A commit sent again for a request that an administrator abandoned gets this code: send the commit again with a new request ID. A refused end of a commit request names its entries instead. `context.open` lists the entries that are not done, and `context.done` lists the entries that are done. Each list has at most 20 entries. |
| `STORAGE_FAILED` | 500 | An operation on the share failed. The API reports it for its disk work, and the CLI reports it when it cannot use the share. The share is missing, has no marker or a marker for a different instance or organization, or is not writable. `context.path` names the path. |
| `SYMLINK_IN_LAKE` | 409 | A name on the path of a disk operation is a symbolic link. The lake must not contain symbolic links. The API does not change the disk, and it does not delete the link. The storage administrator deletes it. `context.path` is the lake path of the link. |
| `TOKEN_INVALID` | 401 | The bearer token or the company token is not valid, or it expired. |
| `UNAUTHENTICATED` | 401 | The request has no bearer token. |
| `UPLOADS_DISABLED` | 404 | The service has no `lake_path`, so it serves no upload route and takes no commit. The upload routes are `POST /api/v1/uploads/hooks`, `GET /api/v1/uploads/auth`, `POST /api/v1/uploads/{id}/cancel` and `GET /api/v1/upload-attempts/{attempt_id}`. The commit route `POST /api/v1/collections/{id}/commits` and the route `POST /api/v1/admin/collections/{id}/pending-request` also need a lake. |
| `UPLOAD_INELIGIBLE` | 409 | A commit or a seal names an upload that it cannot use. `context.upload_id` names the upload, `context.state` gives the state of its attempt and `context.reason` tells why. The reason `state` means that the upload is not ready for the commit, or that the seal cannot start in that state. A commit first runs a seal check of an upload that is not ready. If the attempt ended (`failed`, `cancelled` or `expired`), start a new upload with a new `attempt_id`. The reason `superseded` means that the upload is not the current upload of its attempt. Only a commit gives the reasons `held` and `different_file`. The reason `held` means that a pending commit holds the upload. The reason `different_file` means that the upload is for a different collection or path, or its size or sha256 is not the value of the add. Read the upload attempt. To send a refused commit again, use a new request ID. |
| `UPLOAD_NOT_FOUND` | 404 | Huron did not issue the upload ID, or the caller did not start the upload. `context.upload` names the upload ID. |
| `UPLOAD_SIZE_MISMATCH` | 422 | The uploaded file does not have the size that the upload declared. The attempt is `failed` with this code. The refusal of the pre-finish hook names the upload ID in `context.upload`. |
| `UPLOAD_STATE_CONFLICT` | 409 | A creation names an upload attempt that has an upload, so Huron issues no new upload ID. `context.attempt_id` names the attempt and `context.state` gives its state. If the attempt did not end, `context.upload_id` names its current upload: continue a `receiving` upload, and read the attempt in the other states. If the attempt ended, start a new upload with a new `attempt_id`. |
| `UPLOAD_TOO_LARGE` | 413 | The upload declares more bytes than `max_upload_bytes`, the largest file that the service accepts. The upload can never fit, so do not send it again. `context.size` gives the declared size and `context.maximum` gives the limit. |
| `VERSION_CONFLICT` | 412 | `If-Match` names an older version. `context.current_version` names the current version. |

## Refusals of a commit request

The server keeps the outcome of each commit request under the request ID of its creator. A
refusal after the server found the collection is also kept, with the state `rejected`. These
refusals include `BASE_VERSION_CONFLICT`, `COLLECTION_BUSY`, `COMMIT_INVALID`,
`FILE_NOT_RECORDED`, `FORBIDDEN`, `STATE_CONFLICT`, `UPLOAD_INELIGIBLE` and `UPLOAD_NOT_FOUND`. The
same request ID and the same body get the kept refusal again. Thus a client sends a corrected or
repeated commit with a new request ID.

## Errors after a commit

Some requests change the disk after they change the rows. These requests commit the rows first.
After the commit, the only errors are `STORAGE_FAILED`, `LAKE_UNAVAILABLE`, `SYMLINK_IN_LAKE` and
`NAME_INVALID`. A new directory that did not get the setgid bit and the group of its parent is
`STORAGE_FAILED`. Without a `lake_path`, these requests change only the rows.

The creates, the share group change, the activation, the metadata change and the schema assignment
keep their rows when the disk work fails. A delete request deletes its rows before the disk work
starts. When the disk work of a delete fails, the rows stay deleted. When the directory of a delete
is not empty, the directory stays on the disk and the answer is 204.

## Warnings

A warning is not an error. The request succeeded, but a change on disk is not complete. The
create and set catalog responses and the repair responses list their warnings in `warnings`. Each
warning has the fields `code`, `group` and `detail`.

| Code | Meaning |
| --- | --- |
| `SHARE_GROUP_PENDING` | The catalog directory does not have the group `group`. The API could not set the group, and `detail` tells why. When the request sets a share group, `group` is the share group. When the request clears the share group, `group` is the gid of the service group. The storage administrator sets the group on disk. |

## Repair failures

A repair (`POST /api/v1/catalogs/{catalog}/repair` and `POST /api/v1/organizations/{org}/repair`)
answers 200 also when it cannot fix a place. Each place that it cannot fix is an item in `failed`,
with the fields `path`, `reason` and `detail`. Only `LAKE_UNAVAILABLE` stops a repair. The schema
`RepairFailureOut` in the OpenAPI reference ([`openapi.json`](openapi.json)) gives the rules for
the three fields.
