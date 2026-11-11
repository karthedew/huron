# API error codes

Every error is an RFC 9457 `application/problem+json` document. The document has the fields
`type`, `title`, `status`, `detail`, `code` and `context`. The CLI maps each code to an exit code
(see the user guide).

| Code | Status | Meaning |
| --- | --- | --- |
| `BASE_VERSION_CONFLICT` | 409 | The base version of the commit is older than the current version of the collection. Run `huron pull`. `context.current_version` names the current version. |
| `CAPACITY_EXCEEDED` | 429 | The service does not have the space for the upload now. `context.limit` names the limit that stops the upload. `context.requested` and `context.available` give the numbers of bytes. Send the upload again later. |
| `CATALOG_NOT_EMPTY` | 409 | The catalog still has namespaces. |
| `COLLECTIONS_NOT_ALLOWED` | 409 | The namespace does not allow collections. |
| `COLLECTION_BUSY` | 409 | The collection has a pending commit. A collection accepts one commit at a time. Send the commit again when the pending commit ends. |
| `COLLECTION_NOT_EMPTY` | 409 | The collection still has recorded files. |
| `COMMIT_INVALID` | 422 | The commit body is not valid. It breaks the commit schema or a path rule, or it has the same path twice. |
| `COMMIT_REQUEST_NOT_FOUND` | 404 | The commit request does not exist, or a different user sent it. `context.request_id` names the request. |
| `COMMIT_TOO_LARGE` | 413 | The commit has more than 10,000 entries. |
| `DEPENDENCY_UNAVAILABLE` | 503 | A dependency is unreachable, for example the database or the identity provider. |
| `FILE_NOT_RECORDED` | 422 | A path in the `removes` list of the commit is not a recorded file. |
| `FORBIDDEN` | 403 | The caller does not have the necessary privilege. `context.privilege` names the privilege. |
| `GROUP_DIRECTORY_UNAVAILABLE` | 503 | The LDAP group directory could not answer during the token exchange. |
| `INTERNAL` | 500 | An unexpected error occurred. `context.request_id` matches the service log. |
| `INVALID_CURSOR` | 400 | This listing did not produce the paging cursor. |
| `LAKE_UNAVAILABLE` | 503 | The API cannot write the lake. `lake_path` does not open as a directory, or the API cannot write it. Or the marker that guards the organization is missing or names a different instance or organization. `context` names the path. A repair route of a service without `lake_path` also answers it. |
| `METADATA_INVALID` | 422 | The metadata does not satisfy the schema of the collection, or it has a value that JSON cannot hold (rule `json`). NaN, infinity and a lone surrogate are such values. `context.problems` lists each problem. |
| `NAMESPACE_NOT_EMPTY` | 409 | The namespace still has child namespaces or collections. Draft collections count. |
| `NAME_INVALID` | 422 | A name breaks a naming rule. `context.rule` names the rule. |
| `NAME_TAKEN` | 409 | Another organization, catalog, sibling namespace or collection uses the name. |
| `NOT_FOUND` | 404 | The object does not exist, or the caller cannot see it. |
| `ORGANIZATIONS_MANAGED` | 409 | The service configuration declares the organizations, so the API cannot create an organization. Use `huron adm provision-orgs` to prepare the declared organizations. |
| `ORGANIZATION_DECLARED` | 409 | The service configuration declares the organization. The API cannot delete it. Its role groups at organization scope (`org_admin`, `catalog_admin`, `contributor` and `reader`) are the `groups` in its declaration. Delete its declaration from the service configuration, or change `groups.<role>` in the service configuration. |
| `ORGANIZATION_NOT_EMPTY` | 409 | The organization still has catalogs. |
| `PRECONDITION_REQUIRED` | 428 | A request that writes to a collection needs an `If-Match` header with the quoted version of the collection. |
| `REQUEST_ID_CONFLICT` | 409 | The commit has the request ID of an earlier commit, but a different body. Use a new request ID for a new commit. `context.request_id` names the request. |
| `REQUEST_INVALID` | 422 | The request is not valid, or it names something that Huron does not accept. `context` tells what is wrong. |
| `SCHEMA_INCOMPATIBLE` | 422 | A schema contradicts the schema that it extends. It changes the type of a required property, or it has no base schema. |
| `SCHEMA_INVALID` | 422 | A schema document is outside the allowed subset of JSON Schema, or it has a value that JSON cannot hold (rule `json`). |
| `SCHEMA_SCOPE` | 422 | A catalog or a schema uses a schema of a different organization. |
| `STATE_CONFLICT` | 409 | The state of the object does not allow the operation. `context.state` and `context.allowed` tell why. |
| `STORAGE_FAILED` | 500 | An operation on the share failed. The API reports it for its disk work, and the CLI reports it when it cannot use the share. The share is missing, has no marker or a marker for a different instance or organization, or is not writable. `context.path` names the path. |
| `SYMLINK_IN_LAKE` | 409 | A name on the path of a disk operation is a symbolic link. The lake must not contain symbolic links. The API does not change the disk, and it does not delete the link. The storage administrator deletes it. `context.path` is the lake path of the link. |
| `TOKEN_INVALID` | 401 | The bearer token or the company token is not valid, or it expired. |
| `UNAUTHENTICATED` | 401 | The request has no bearer token. |
| `UPLOADS_DISABLED` | 404 | The service has no `lake_path`, so it serves no upload route. The upload routes are `POST /api/v1/uploads/hooks`, `GET /api/v1/uploads/auth` and `GET /api/v1/uploads/{id}`. |
| `UPLOAD_INELIGIBLE` | 409 | The commit names an upload that is not ready. A commit can publish only a ready upload. `context.upload_id` names the upload, and `context.state` gives its state. Read the upload attempt, then send the commit again. |
| `UPLOAD_NOT_FOUND` | 404 | The upload does not exist, or the caller did not start it. |
| `UPLOAD_RECEIPT_MISSING` | 422 | The commit adds a file that has no upload receipt. A receipt is good only for the same user, path, size and sha256, and only until `upload_ttl` ends. A later upload to the same path, by any user, cancels the receipt. `context.rel_path` names the file. |
| `UPLOAD_SIZE_MISMATCH` | 422 | The uploaded file does not have the size that the upload declared. `context.declared` and `context.received` give the two sizes. |
| `UPLOAD_STATE_CONFLICT` | 409 | The state of the upload does not allow the operation. `context.state` and `context.allowed` tell why. A creation that names an upload attempt with an upload also gets this code. Then `context.attempt_id` names the attempt and `context.state` gives its state. If the attempt did not end, `context.upload_id` names its current upload. |
| `UPLOAD_TOO_LARGE` | 413 | The upload declares more bytes than `upload_max_size`. `context.maximum` gives the limit. |
| `VERSION_CONFLICT` | 412 | `If-Match` names an older version. `context.current_version` names the current version. |

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
