/**
 * HAND-WRITTEN DOMAIN TYPES — DELETED AT P1.
 *
 * These are a placeholder for the types generated from `openapi/v1.json`
 * (design/frontend.html §1). They are shaped to the design record, not to any
 * running endpoint, because no endpoint exists yet. Do not add convenience fields
 * the API does not promise: a field invented here becomes a field the UI silently
 * depends on and the contract never provides.
 *
 * See ./README.md.
 */

export type Lifecycle = 'ACTIVE' | 'RETIRED';

export type Layer = 'raw' | 'bronze' | 'silver' | 'gold';

export type LayerState =
	| { state: 'present'; detail?: string }
	| { state: 'building'; detail?: string }
	| { state: 'absent'; detail?: string };

export type LayerAvailability = Record<Layer, LayerState>;

export type Watermark =
	{ state: 'healthy'; lagSeconds: number } | { state: 'unavailable'; lagSeconds?: undefined };

/** Opaque, versioned keyset cursor. The UI never parses or constructs one. */
export type Cursor = string;

export interface Page<T> {
	items: T[];
	nextCursor: Cursor | null;
	prevCursor: Cursor | null;
}

export interface Organization {
	slug: string;
	name: string;
	description: string;
	projectCount: number;
}

export interface Project {
	slug: string;
	orgSlug: string;
	name: string;
	description: string;
	datasetCount: number;
	/** Bytes. Raw lives on NFS; derived layers on object storage — reported separately. */
	quota: { rawUsed: number; rawLimit: number; objectUsed: number; objectLimit: number };
}

export interface Dataset {
	slug: string;
	orgSlug: string;
	projectSlug: string;
	name: string;
	description: string;
	lifecycle: Lifecycle;
	classification: string;
	profile: string;
	tags: string[];
	layers: LayerAvailability;
	releaseCount: number;
}

export interface Release {
	slug: string;
	datasetSlug: string;
	projectSlug: string;
	orgSlug: string;
	createdAt: string;
	layers: LayerAvailability;
	revisionCount: number;
	sealed: boolean;
}

export interface Revision {
	number: number;
	reason: string;
	createdAt: string;
	fileCount: number;
	totalBytes: number;
	sealed: boolean;
}

export interface ManifestEntry {
	path: string;
	bytes: number;
	checksum: string;
	retentionCategory: string;
	expiresAt: string | null;
}

export interface SearchHit {
	kind: 'dataset' | 'release' | 'product';
	slugPath: string;
	title: string;
	snippet: string;
	layers: LayerAvailability;
	classification: string;
	stale?: { reason: string };
}

export interface SearchResults {
	hits: SearchHit[];
	watermark: Watermark;
	facets: Record<string, { value: string; count: number }[]>;
	nextCursor: Cursor | null;
	prevCursor: Cursor | null;
}

export interface ApiKey {
	id: string;
	name: string;
	scopes: string[];
	projectRestriction: string | null;
	createdAt: string;
	lastUsedAt: string | null;
	expiresAt: string | null;
}

export interface IngestJob {
	id: string;
	organization: string;
	project: string;
	dataset: string;
	release: string;
	layer: 'raw' | 'bronze';
	status: 'queued' | 'running' | 'succeeded' | 'failed';
	createdAt: string;
}

export interface RoleBinding {
	principal: string;
	role: string;
	scope: string;
}

export interface OrganizationMember {
	id: string;
	displayName: string;
	email: string;
	kind: 'user' | 'group' | 'service_account';
	status: 'active' | 'invited';
	lastActiveAt: string | null;
}

export interface PermissionGrant {
	id: string;
	principal: string;
	displayName: string;
	principalKind: 'user' | 'group';
	role: 'reader' | 'developer' | 'project_admin' | 'organization_admin' | 'platform_owner';
	scope: string;
	inherited: boolean;
	inheritedFrom?: string;
}

export interface WhoAmI {
	subject: string;
	displayName: string;
	bindings: RoleBinding[];
}

/** The API renders 404 for resources the principal cannot discover — never 403. */
export class NotFound extends Error {
	constructor(what: string) {
		super(`${what} not found`);
		this.name = 'NotFound';
	}
}
