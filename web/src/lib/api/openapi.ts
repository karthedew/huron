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
	version: number;
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

/** What a successful commit answers. */
export interface CommitResultOut {
	commit_id: string;
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

/** The complete set of LDAP groups for one role. */
export interface GroupsIn {
	ldap_groups: string[];
}

/** The LDAP groups holding one role. */
export interface GroupsOut {
	ldap_groups: string[];
	role: string;
}

export interface HTTPValidationError {
	detail?: ValidationError[];
}

/** The liveness answer. */
export interface Health {
	instance_id: string;
	status: string;
	version: string;
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
	version: number;
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
	description: string;
	display_name: string;
	id: string;
	name: string;
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

/** A signing key without its private part. */
export interface SigningKeyOut {
	/** Format: date-time. */
	created_at: string;
	kid: string;
	public_jwk: Record<string, unknown>;
	/** Format: date-time. */
	retired_at: string | null;
}

/** The lifecycle state of a collection. */
export type State = 'draft' | 'active' | 'incomplete';

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
