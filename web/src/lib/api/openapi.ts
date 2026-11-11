// Generated from docs/openapi.json by web/scripts/generate-api-types.mjs — do not edit.
// Regenerate with `npm run generate:api` after the API contract changes.

/** A file that a commit adds or replaces: the sealed bytes of one upload. */
export interface AddIn {
	rel_path: string;
	/** The sha256 of the file. A commit needs it; a dry run can leave it out. */
	sha256?: string | null;
	size: number;
	/**
	 * The current upload ID of a ready upload attempt. A commit needs it; a dry run can leave it out.
	 * Format: uuid.
	 */
	upload_id?: string | null;
}

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

/** The id tusd gives the new upload: the upload ID that Huron issued for the attempt. */
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
	/** The commit request that holds the collection; null when none holds it. While a request is pending, the files and the version are those of the last commit that succeeded. */
	pending_request: PendingRequestOut | null;
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

/** The body of a commit to one collection: at most 10,000 adds and removes together. */
export interface CommitIn {
	adds: AddIn[];
	base_version: number;
	host: string;
	message?: string | null;
	removes: string[];
	/**
	 * The client's ID of the request. A commit needs it; a dry run can leave it out. The same ID with the same body gets the saved outcome again.
	 * Format: uuid.
	 */
	request_id?: string | null;
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

/** What a commit would make: the answer of a dry run. */
export interface CommitPreviewOut {
	file_count: number;
	version: number;
}

/**
 * The saved state of a commit request.
 * 
 * A ``succeeded`` request has its ``version``, ``file_count`` and ``commit_id``. A ``rejected``
 * or ``blocked`` request has its ``refusal``.
 */
export interface CommitRequestOut {
	/** null when the collection is deleted. */
	collection_id: string | null;
	commit_id: string | null;
	file_count: number | null;
	refusal: RefusalOut | null;
	request_id: string;
	/** rejected, accepted, blocked, succeeded or abandoned. */
	state: string;
	version: number | null;
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

/** Why an upload attempt failed. */
export interface FailureOut {
	code: string;
	message: string;
}

/** Why a repair could not fix a place. */
export type FailureReason = 'mode_drift' | 'symbolic_link' | 'storage_failed';

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
 * finished upload adds the header ``Huron-Upload-State`` and keeps tusd's status.
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

/**
 * The client's request that made tusd send the hook.
 * 
 * ``uri`` names the tus resource. ``header`` holds the client's headers, each name with its
 * values.
 */
export interface HookHTTPRequest {
	Header?: Record<string, string[]>;
	Method?: string;
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
 * ``RejectUpload`` refuses a creation. A refused ``pre-finish`` has only ``HTTPResponse``:
 * tusd still counts that upload as finished.
 */
export interface HookResponse {
	ChangeFileInfo?: ChangeFileInfo | null;
	HTTPResponse?: HTTPResponse | null;
	RejectUpload?: boolean | null;
}

/** The blocking hooks tusd sends to the API. */
export type HookType = 'pre-create' | 'pre-finish';

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

/** The commit request that holds a collection. */
export interface PendingRequestOut {
	/** Format: date-time. */
	since: string;
	/** accepted, or blocked until an operator resolves it. */
	state: string;
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

/** The problem that refused or blocked a commit request. */
export interface RefusalOut {
	code: string;
	context: Record<string, unknown>;
	detail: string;
}

/** A place that the repair could not fix. */
export interface RepairFailureOut {
	/** Why the repair failed, as text for people. It names the same place as path. */
	detail: string;
	/** The place where the repair failed, in the form of a view's path. For mode_drift, path is the directory of the step. For symbolic_link, path is the link. The link can be at the directory of the step or at a directory above it. It can also be at the metadata.json of the step or at its part file (metadata.json.huron-part). Or it can be at the .huron marker that guards the organization. For an organization with its own root, this marker is in the directory of the organization (path <organization>/.huron). For any other organization, it is the marker at the root of the lake (path .huron). For storage_failed, path is the place that the storage error names. This place is the directory of the step, the catalog directory, the metadata.json of the step or its part file. When the directory refuses to make or to delete the part file, or the rename of the part file fails, path is metadata.json. A place at or above the root of the organization keeps its path in the lake, for example roots. */
	path: string;
	/** mode_drift: only the storage administrator can set the mode or the group of the directory. The catalog directory or a directory below it does not have the setgid bit. Or a directory below the catalog directory does not have the group of the catalog directory. Or the permission bits are wrong, and the API is not in the group of the directory. Or the mode is still wrong after the API changed it. Or a new directory did not get the setgid bit and the group of its parent, or the mode 2750. The API deleted that directory again. The storage administrator runs huron adm provision-catalogs. symbolic_link: path is a symbolic link. The repair does not change the link. The storage administrator deletes it. storage_failed: a different storage error occurred. For example, the path of the step is not a directory. Or a directory is at metadata.json or at its part file. Or the API cannot read or write path. */
	reason: FailureReason;
}

/** What a catalog repair covers. */
export interface RepairIn {
	/** Also repair every namespace and settled collection below the target. */
	recursive?: boolean;
	/** The catalog's name, or the identifier of one of its namespaces or settled collections. */
	target: string;
}

/** What a repair changed, the share groups still pending, and what it could not fix. */
export interface RepairOut {
	/** The paths that the repair made or changed. */
	changed: string[];
	failed: RepairFailureOut[];
	warnings: ShareWarningOut[];
}

/**
 * What a platform administrator does with a blocked request.
 * 
 * ``retry`` runs the entries that are not done again. ``abandon`` ends a request of which no
 * entry is done, frees its collection and returns its uploads to ``ready``.
 */
export type Resolution = 'retry' | 'abandon';

/** What a platform administrator does with the blocked commit request of a collection. */
export interface ResolutionIn {
	/** retry: run the entries that are not done again. abandon: end a request of which no entry is done, free the collection and make its uploads ready again. */
	resolution: Resolution;
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

/** An upload attempt and its current upload ID, for its owner. */
export interface UploadAttemptOut {
	attempt_id: string;
	/** null when the collection is deleted. */
	collection_id: string | null;
	failure: FailureOut | null;
	rel_path: string;
	size: number;
	/** receiving, sealing, ready, consumed, failed, cancelled or expired. */
	state: string;
	/** The current upload ID: the only ID that tusd takes bytes for. */
	upload_id: string;
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
