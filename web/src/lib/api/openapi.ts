// Generated from docs/openapi.json by web/scripts/generate-api-types.mjs — do not edit.
// Regenerate with `npm run generate:api` after the API contract changes.

/** The registry entry to assign to a catalog. */
export interface AssignIn {
	/** Format: uuid. */
	schema_id: string;
}

/** The catalog after an assignment and the recompute counts. */
export interface AssignOut {
	assigned: CatalogOut;
	recompute: RecomputeOut;
}

/** One audit entry. */
export interface AuditOut {
	action: string;
	actor: string;
	/** Format: date-time. */
	at: string;
	catalog_id: string | null;
	detail: Record<string, unknown>;
	id: number | null;
	object_id: string | null;
	object_type: string;
	organization_id: string | null;
}

/** A new catalog. */
export interface CatalogIn {
	description?: string;
	display_name?: string;
	name: string;
	/** Format: uuid. */
	schema_id?: string | null;
	/** The POSIX group whose members read the catalog's directory. */
	share_group?: string | null;
}

/** A catalog. */
export interface CatalogOut {
	/** Format: date-time. */
	created_at: string;
	created_by: string;
	description: string;
	display_name: string;
	id: string;
	name: string;
	namespace_count: number;
	organization: string;
	schema: SchemaRefOut;
	/** The POSIX group whose members read the catalog's directory. */
	share_group: string | null;
	/** The configured root of the organization's directory; clients join it with the relative path, or use their own mount prefix when it is null. */
	share_root: string | null;
	version: number;
}

/** A catalog after a create or a change, with the warnings of its disk work. */
export interface CatalogWriteOut {
	/** Format: date-time. */
	created_at: string;
	created_by: string;
	description: string;
	display_name: string;
	id: string;
	name: string;
	namespace_count: number;
	organization: string;
	schema: SchemaRefOut;
	/** The POSIX group whose members read the catalog's directory. */
	share_group: string | null;
	/** The configured root of the organization's directory; clients join it with the relative path, or use their own mount prefix when it is null. */
	share_root: string | null;
	version: number;
	warnings: ShareWarningOut[];
}

/** The id tusd gives the new upload: the id of the API's upload row. */
export interface ChangeFileInfo {
	ID: string;
}

/** A new draft collection. */
export interface CollectionIn {
	metadata?: Record<string, unknown> | null;
	name: string;
}

/** A collection. */
export interface CollectionOut {
	/** Format: date-time. */
	activated_at: string | null;
	catalog: string;
	/** Format: date-time. */
	created_at: string;
	created_by: string;
	file_count: number;
	id: string;
	identifier: string;
	metadata: Record<string, unknown>;
	name: string;
	namespace: string;
	organization: string;
	path: string | null;
	problems: ProblemOut[];
	schema: SchemaRefOut;
	schema_override: Record<string, unknown> | null;
	/** The configured root of the organization's directory; clients join it with the relative path, or use their own mount prefix when it is null. */
	share_root: string | null;
	state: string;
	/** Format: date-time. */
	updated_at: string;
	version: number;
}

/** A metadata merge patch and/or a schema override (``null`` clears the override). */
export interface CollectionPatch {
	metadata?: Record<string, unknown> | null;
	schema_override?: Record<string, unknown> | null;
}

/** An applied commit. */
export interface CommitOut {
	actor: string;
	adds: number;
	base_version: number;
	/** Format: date-time. */
	created_at: string;
	host: string;
	id: string;
	message: string | null;
	new_version: number;
	removes: number;
}

/** What a successful commit answers; a dry run answers what the commit would make. */
export interface CommitResultOut {
	/** The commit's id; null for a dry run. */
	commit_id: string | null;
	file_count: number;
	version: number;
}

/** Groups per role on a catalog, inherited ones included. */
export interface EffectiveGroupsOut {
	catalog_admin: string[];
	contributor: string[];
	org_admin: string[];
	platform_admin: string[];
	reader: string[];
}

/** A company ID token to exchange. */
export interface ExchangeIn {
	company_token: string;
}

/** A Huron token and who it names. */
export interface ExchangeOut {
	/** Format: date-time. */
	expires_at: string;
	groups: string[];
	huron_token: string;
	name: string;
	subject: string;
	token_type?: string;
}

/** Why the API could not place an upload. */
export interface FailureOut {
	code: string;
	message: string;
}

/** A recorded file. */
export interface FileOut {
	commit_id: string;
	/** Format: date-time. */
	recorded_at: string;
	recorded_by: string;
	rel_path: string;
	sha256: string;
	size: number;
}

/** The result of replacing a role's groups. */
export interface GrantChangeOut {
	added: string[];
	ldap_groups: string[];
	removed: string[];
	role: string;
}

/** One group holding one role on a catalog, and the scope the grant was made at. */
export interface GrantSourceOut {
	group: string;
	role: 'platform_admin' | 'org_admin' | 'catalog_admin' | 'contributor' | 'reader';
	scope: 'platform' | 'organization' | 'catalog';
}

/** Every grant holding on a catalog, sorted by role (Platform Admin first), group, scope. */
export interface GrantSourcesOut {
	items: GrantSourceOut[];
}

/** The complete set of LDAP groups for one role. */
export interface GroupsIn {
	ldap_groups: string[];
}

/** The LDAP groups holding one role. */
export interface GroupsOut {
	ldap_groups: string[];
	role: string;
}

/**
 * What tusd merges into its response to the client.
 * 
 * A refusal sets the status, the problem media type and the problem document as text. A
 * finished upload adds the receipt headers and keeps tusd's status.
 */
export interface HTTPResponse {
	Body?: string | null;
	Header?: Record<string, string> | null;
	StatusCode?: number | null;
}

export interface HTTPValidationError {
	detail?: ValidationError[];
}

/**
 * The liveness answer.
 * 
 * ``organizations_managed`` is whether the service configuration declares the organizations:
 * the CLI then looks for an organization's directory only where its declaration puts it.
 * ``uploads_url`` is the public tus endpoint, ``null`` while uploads are off.
 * ``service_user`` is ``null`` without a configured service group. ``upload_hook_timeout`` is
 * how long tusd waits for a hook, in seconds.
 */
export interface Health {
	instance_id: string;
	organizations_managed: boolean;
	service_user: ServiceUser | null;
	status: string;
	upload_hook_timeout: number;
	uploads_url: string | null;
	version: string;
}

/** What happened: the upload and the client's request. */
export interface HookEvent {
	HTTPRequest?: HookHTTPRequest;
	Upload: HookUpload;
}

/** The client's request that made tusd send the hook; ``uri`` names the tus resource. */
export interface HookHTTPRequest {
	URI?: string;
}

/** A hook call from tusd. */
export interface HookRequest {
	Event: HookEvent;
	Type: HookType;
}

/**
 * The API's answer to a hook.
 * 
 * ``RejectUpload`` refuses a creation and ``RejectTermination`` a termination. A refused
 * ``pre-finish`` has only ``HTTPResponse``: tusd still counts that upload as finished.
 */
export interface HookResponse {
	ChangeFileInfo?: ChangeFileInfo | null;
	HTTPResponse?: HTTPResponse | null;
	RejectTermination?: boolean | null;
	RejectUpload?: boolean | null;
}

/** The blocking hooks tusd sends to the API. */
export type HookType = 'pre-create' | 'pre-finish' | 'pre-terminate';

/** The upload a hook is about. ``id`` is empty before ``pre-create`` names it. */
export interface HookUpload {
	ID?: string;
	IsFinal?: boolean;
	IsPartial?: boolean;
	MetaData?: Record<string, string> | null;
	Size?: number;
	SizeIsDeferred?: boolean;
}

/** Whether the namespace may hold collections. */
export interface NamespaceConfigureIn {
	collections_allowed: boolean;
}

/** A new namespace under ``parent`` (empty for the catalog root). */
export interface NamespaceIn {
	collections_allowed?: boolean;
	name: string;
	parent?: string;
}

/** A namespace. */
export interface NamespaceOut {
	catalog: string;
	collection_count: number;
	collections_allowed: boolean;
	/** Format: date-time. */
	created_at: string;
	created_by: string;
	disk_path: string;
	id: string;
	identifier: string;
	name: string;
	namespace_count: number;
	organization: string;
	parent: string;
	path: string;
	/** The configured root of the organization's directory; clients join it with the relative path, or use their own mount prefix when it is null. */
	share_root: string | null;
	version: number;
}

/**
 * Groups per organization-scope role.
 * 
 * ``catalog_admin``, ``contributor`` and ``reader`` hold their role in every catalog of the
 * organization.
 */
export interface OrganizationGroupsOut {
	catalog_admin: string[];
	contributor: string[];
	org_admin: string[];
	reader: string[];
}

/** A new organization. */
export interface OrganizationIn {
	description?: string;
	display_name?: string;
	name: string;
}

/** An organization. */
export interface OrganizationOut {
	catalog_count: number;
	/** Format: date-time. */
	created_at: string;
	created_by: string;
	/** Whether the service configuration declares it. */
	declared: boolean;
	description: string;
	display_name: string;
	/** The NFS export the configuration names, if any. */
	export: string | null;
	id: string;
	name: string;
	/** The organization's directory, root/name. */
	path: string | null;
	/** The configured parent of the organization's directory. */
	root: string | null;
	version: number;
}

/** One page of a keyset-paginated list; `next_cursor` is absent or null on the last page. */
export interface Page<T> {
	items: T[];
	next_cursor?: string | null;
}

/** One validation problem. */
export interface ProblemOut {
	message: string;
	path: string;
	rule: string;
}

/** How a schema assignment moved the catalog's collections. */
export interface RecomputeOut {
	active: number;
	changed: number;
	incomplete: number;
}

/** One role the caller holds. */
export interface RoleOut {
	role: string;
	scope: string;
	scope_id: string | null;
}

/** A new version of a named schema. */
export interface SchemaIn {
	document: Record<string, unknown>;
	/** Format: uuid. */
	extends_id?: string | null;
	name: string;
}

/** A registry entry. */
export interface SchemaOut {
	/** Format: date-time. */
	created_at: string;
	created_by: string;
	document: Record<string, unknown>;
	extends_id: string | null;
	id: string;
	name: string;
	organization_id: string | null;
	scope: string;
	version: number;
}

/** A short reference to a registry entry. */
export interface SchemaRefOut {
	id: string;
	name: string;
	version: number;
}

/** The identity that owns the lake: the service's UID, primary GID and service group. */
export interface ServiceUser {
	gid: number;
	group: string;
	uid: number;
}

/** A catalog's new share group; ``null`` clears it. */
export interface ShareGroupIn {
	/** The POSIX group whose members read the catalog's directory. */
	share_group: string | null;
}

/** A change on disk that the storage administrator must still make. */
export interface ShareWarningOut {
	/** SHARE_GROUP_PENDING: the directory does not have the group. */
	code: string;
	detail: string;
	/** The share group, or the gid of the service group when the share group is cleared. */
	group: string;
}

/** A signing key without its private part. */
export interface SigningKeyOut {
	/** Format: date-time. */
	created_at: string;
	kid: string;
	public_jwk: Record<string, unknown>;
	/** Format: date-time. */
	retired_at: string | null;
}

/** The direction of both the primary field and its name tie-breaker. */
export type SortDirection = 'asc' | 'desc';

/** Recorded fields available for browsing in a consistent order. */
export type SortField = 'name' | 'created_by' | 'created_at';

/** The lifecycle state of a collection. */
export type State = 'draft' | 'active' | 'incomplete';

/** An upload and its receipt, for its creator. */
export interface UploadOut {
	collection_id: string;
	failure: FailureOut | null;
	id: string;
	rel_path: string;
	sha256: string | null;
	size: number;
	/** pending, placed, failed, terminated or committed. */
	state: string;
}

export interface ValidationError {
	ctx?: Record<string, unknown>;
	input?: unknown;
	loc: (string | number)[];
	msg: string;
	type: string;
}

/** The caller, their groups and their effective roles. */
export interface WhoAmI {
	groups: string[];
	name: string;
	roles: RoleOut[];
	subject: string;
}
