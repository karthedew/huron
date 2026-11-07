# API error codes

Every error is an RFC 9457 `application/problem+json` document. The document has the fields
`type`, `title`, `status`, `detail`, `code` and `context`. The CLI maps each code to an exit code
(see the user guide).

| Code | Status | Meaning |
| --- | --- | --- |
| `ACL_FAILED` | 500 | The CLI tried to read or write a POSIX ACL and failed. Only the CLI reports this code. |
| `BASE_VERSION_CONFLICT` | 409 | The base version of the commit is older than the current version of the collection. Run `huron pull`. `context.current_version` names the current version. |
| `CATALOG_NOT_EMPTY` | 409 | The catalog still has namespaces. |
| `COLLECTIONS_NOT_ALLOWED` | 409 | The namespace does not allow collections. |
| `COLLECTION_NOT_EMPTY` | 409 | The collection still has recorded files. |
| `COMMIT_INVALID` | 422 | The commit body is not valid. It breaks the commit schema or a path rule, or it has the same path twice. |
| `COMMIT_TOO_LARGE` | 413 | The commit has more than 10,000 entries. |
| `DEPENDENCY_UNAVAILABLE` | 503 | A dependency is unreachable, for example the database or the identity provider. |
| `FILE_NOT_RECORDED` | 422 | A path in the `removes` list of the commit is not a recorded file. |
| `FORBIDDEN` | 403 | The caller does not have the necessary privilege. `context.privilege` names the privilege. |
| `GROUP_DIRECTORY_UNAVAILABLE` | 503 | The LDAP group directory could not answer during the token exchange. |
| `INTERNAL` | 500 | An unexpected error occurred. `context.request_id` matches the service log. |
| `INVALID_CURSOR` | 400 | This listing did not produce the paging cursor. |
| `LAKE_UNAVAILABLE` | 503 | The API cannot write the lake. `lake_path` is not a directory, or the API cannot write it. Or the marker that guards the organization is missing or names a different instance or organization. `context` names the path. |
| `METADATA_INVALID` | 422 | The metadata does not satisfy the schema of the collection, or it has a value that JSON cannot hold (rule `json`). NaN, infinity and a lone surrogate are such values. `context.problems` lists each problem. |
| `NAMESPACE_NOT_EMPTY` | 409 | The namespace still has child namespaces or collections. Draft collections count. |
| `NAME_INVALID` | 422 | A name breaks a naming rule. `context.rule` names the rule. |
| `NAME_TAKEN` | 409 | Another organization, catalog, sibling namespace or collection uses the name. |
| `NOT_FOUND` | 404 | The object does not exist, or the caller cannot see it. |
| `ORGANIZATIONS_MANAGED` | 409 | The service configuration declares the organizations, so the API cannot create an organization. Use `huron adm provision-orgs` to prepare the declared organizations. |
| `ORGANIZATION_DECLARED` | 409 | The service configuration declares the organization. The API cannot delete it. Its role groups at organization scope (`org_admin`, `catalog_admin`, `contributor` and `reader`) are the `groups` in its declaration. Delete its declaration from the service configuration, or change `groups.<role>` in the service configuration. |
| `ORGANIZATION_NOT_EMPTY` | 409 | The organization still has catalogs. |
| `OUTSIDE_LAKE` | 422 | The path of the request is outside `lake_path`, or it is on a different filesystem below `lake_path`. The API makes no change on disk there. `context.path` names the path. |
| `PRECONDITION_REQUIRED` | 428 | A request that writes to a collection needs an `If-Match` header with the quoted version of the collection. |
| `REQUEST_INVALID` | 422 | The request is not valid, or it names something that Huron does not accept. `context` tells what is wrong. |
| `SCHEMA_INCOMPATIBLE` | 422 | A schema contradicts the schema that it extends. It changes the type of a required property, or it has no base schema. |
| `SCHEMA_INVALID` | 422 | A schema document is outside the allowed subset of JSON Schema, or it has a value that JSON cannot hold (rule `json`). |
| `SCHEMA_SCOPE` | 422 | A catalog or a schema uses a schema of a different organization. |
| `STATE_CONFLICT` | 409 | The state of the object does not allow the operation. `context.state` and `context.allowed` tell why. |
| `STORAGE_FAILED` | 500 | An operation on the share failed. The API reports it for its disk work, and the CLI reports it when it cannot use the share. The share is missing, has no marker or a marker for a different instance or organization, or is not writable, or an ACL operation failed. `context.path` names the path. |
| `TOKEN_INVALID` | 401 | The bearer token or the company token is not valid, or it expired. |
| `UNAUTHENTICATED` | 401 | The request has no bearer token. |
| `UPLOADS_DISABLED` | 404 | The service has no `lake_path`, so it serves no upload route. The upload routes are `POST /api/v1/uploads/hooks`, `GET /api/v1/uploads/auth` and `GET /api/v1/uploads/{id}`. |
| `UPLOAD_NOT_FOUND` | 404 | The upload does not exist, or the caller did not start it. |
| `UPLOAD_RECEIPT_MISSING` | 422 | The commit adds a file that has no upload receipt. A receipt is good only for the same user, path, size and sha256, and only until `upload_ttl` ends. A later upload to the same path, by any user, cancels the receipt. `context.rel_path` names the file. |
| `UPLOAD_SIZE_MISMATCH` | 422 | The uploaded file does not have the size that the upload declared. `context.declared` and `context.received` give the two sizes. |
| `UPLOAD_STATE_CONFLICT` | 409 | The state of the upload does not allow the operation. `context.state` and `context.allowed` tell why. |
| `UPLOAD_TOO_LARGE` | 413 | The upload declares more bytes than `upload_max_size`. `context.maximum` gives the limit. |
| `VERSION_CONFLICT` | 412 | `If-Match` names an older version. `context.current_version` names the current version. |

## Warnings

A warning is not an error. The request succeeded, but a change on disk is not complete. The
create and set catalog responses list their warnings in `warnings`. Each warning has the fields
`code`, `group` and `detail`.

| Code | Meaning |
| --- | --- |
| `SHARE_GROUP_PENDING` | The catalog directory does not have the group `group`. The API could not set the group, and `detail` tells why. When the request sets a share group, `group` is the share group. When the request clears the share group, `group` is the gid of the service group. The storage administrator sets the group on disk. |
