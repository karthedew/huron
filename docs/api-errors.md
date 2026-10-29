# API error codes

Every error is an RFC 9457 `application/problem+json` document with `type`, `title`, `status`,
`detail`, `code` and `context`. The CLI maps codes to exit codes (see the user guide).

| Code | Status | Meaning |
| --- | --- | --- |
| `ACL_FAILED` | 500 | Reading or writing a POSIX ACL failed (CLI only). |
| `BASE_VERSION_CONFLICT` | 409 | A commit was prepared against an older collection version; run `huron pull`. `context.current_version` names the current one. |
| `CATALOG_NOT_EMPTY` | 409 | The catalog still has namespaces. |
| `COLLECTIONS_NOT_ALLOWED` | 409 | The namespace does not allow collections. |
| `COLLECTION_NOT_EMPTY` | 409 | The collection still has recorded files. |
| `COMMIT_INVALID` | 422 | The commit body is malformed: schema, path rules or a duplicate path. |
| `COMMIT_TOO_LARGE` | 413 | A commit holds more than 10,000 entries. |
| `DEPENDENCY_UNAVAILABLE` | 503 | A dependency (database, identity provider) is unreachable. |
| `FILE_NOT_RECORDED` | 422 | A commit removes a file that is not recorded. |
| `FORBIDDEN` | 403 | The caller lacks the privilege; `context.privilege` names it. |
| `GROUP_DIRECTORY_UNAVAILABLE` | 503 | The LDAP group directory could not answer during token exchange. |
| `INTERNAL` | 500 | An unexpected error; `context.request_id` matches the service log. |
| `INVALID_CURSOR` | 400 | The paging cursor was not produced by this listing. |
| `METADATA_INVALID` | 422 | Metadata does not satisfy the collection's schema; `context.problems` lists why. |
| `NAMESPACE_NOT_EMPTY` | 409 | The namespace still has child namespaces or collections (drafts included). |
| `NAME_INVALID` | 422 | A name breaks a naming rule; `context.rule` names it. |
| `NAME_TAKEN` | 409 | Another organization, catalog, sibling namespace or collection uses the name. |
| `NOT_FOUND` | 404 | The object does not exist or is not visible to the caller. |
| `ORGANIZATION_NOT_EMPTY` | 409 | The organization still has catalogs. |
| `PRECONDITION_REQUIRED` | 428 | A write to a collection needs an `If-Match` header with its quoted version. |
| `REQUEST_INVALID` | 422 | The request is malformed or names something unacceptable; `context` says what. |
| `SCHEMA_INCOMPATIBLE` | 422 | A schema contradicts the schema it extends (a required property changed type, or no base). |
| `SCHEMA_INVALID` | 422 | A schema document is outside the allowed subset of JSON Schema. |
| `SCHEMA_SCOPE` | 422 | A schema is used outside its organization. |
| `STATE_CONFLICT` | 409 | The object's state does not allow the operation; `context.state` and `context.allowed` say why. |
| `STORAGE_FAILED` | 500 | The share could not be used: missing, unmarked, unwritable, or an ACL failed (CLI only). |
| `TOKEN_INVALID` | 401 | The bearer or company token is not valid, or has expired. |
| `UNAUTHENTICATED` | 401 | No bearer token was sent. |
| `VERSION_CONFLICT` | 412 | `If-Match` names an older version; `context.current_version` names the current one. |
