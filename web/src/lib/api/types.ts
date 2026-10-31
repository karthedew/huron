/**
 * Domain types for routes and components. Routes and components import API types only from here;
 * `openapi.ts` is generated from the contract and may change shape with it.
 */
import type {
	AuditOut,
	CatalogOut,
	CollectionOut,
	CommitOut,
	EffectiveGroupsOut,
	FileOut,
	NamespaceOut,
	OrganizationOut,
	Page as ApiPage,
	ProblemOut,
	RoleOut,
	SchemaOut,
	SchemaRefOut,
	State,
	WhoAmI as ApiWhoAmI
} from './openapi';

export type Organization = OrganizationOut;
export type Catalog = CatalogOut;
export type Namespace = NamespaceOut;
export type Collection = CollectionOut;
export type CollectionState = State;
export type CollectionProblem = ProblemOut;
export type FileRecord = FileOut;
export type Commit = CommitOut;
export type AuditEntry = AuditOut;
export type SchemaEntry = SchemaOut;
export type SchemaRef = SchemaRefOut;
export type EffectiveGroups = EffectiveGroupsOut;
export type WhoAmI = ApiWhoAmI;
export type RoleGrant = RoleOut;
export type Page<T> = ApiPage<T>;

/**
 * An RFC 9457 problem document, the body of every API error. It is not part of the OpenAPI
 * components, so it is written by hand from `src/huron/applications/api/problems.py`.
 */
export interface Problem {
	type: string;
	title: string;
	status: number;
	detail: string;
	code: string;
	context: Record<string, unknown>;
	instance?: string;
}

/** Any value `JSON.parse` can produce. */
export type JsonValue = null | boolean | number | string | JsonValue[] | JsonObject;

export interface JsonObject {
	[key: string]: JsonValue;
}

/** A resolved JSON Schema document as the API returns it; keywords are read by narrowing. */
export type JsonSchemaDocument = JsonObject;

export const ROLE_SCOPES = ['platform', 'organization', 'catalog'] as const;
export type RoleScope = (typeof ROLE_SCOPES)[number];

export const ROLES = [
	'platform_admin',
	'org_admin',
	'catalog_admin',
	'contributor',
	'reader'
] as const;
export type Role = (typeof ROLES)[number];

/** The closed audit vocabulary of `src/huron/core/lake/audit/models.py`. */
export const AUDIT_ACTIONS = [
	'platform.grant',
	'platform.revoke',
	'organization.create',
	'organization.delete',
	'organization.grant',
	'organization.revoke',
	'catalog.create',
	'catalog.delete',
	'catalog.grant',
	'catalog.revoke',
	'catalog.assign_schema',
	'namespace.create',
	'namespace.delete',
	'namespace.configure',
	'schema.publish',
	'collection.create',
	'collection.update_metadata',
	'collection.set_schema_override',
	'collection.activate',
	'collection.mark_incomplete',
	'collection.mark_active',
	'collection.commit',
	'collection.delete',
	'signing_key.rotate'
] as const;
export type AuditAction = (typeof AUDIT_ACTIONS)[number];

export function isRole(value: string): value is Role {
	return ROLES.some((role) => role === value);
}

export function isAuditAction(value: string): value is AuditAction {
	return AUDIT_ACTIONS.some((action) => action === value);
}
