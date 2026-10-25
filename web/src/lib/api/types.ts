/**
 * Legacy scientific-view types remain hand-written against the design record.
 * Live Polaris and organization contracts are re-exported below.
 * See ./README.md for each API seam's delivery status.
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
export type {
	PolarisProperties,
	PolarisNamedEntity,
	PolarisStorageConfig,
	PolarisCatalog,
	PolarisPrincipal,
	PolarisRole,
	PolarisIcechunkTable,
	PolarisGrant,
	PolarisCredentialSummary,
	PolarisWorkspaceData,
	PolarisActionResult
} from './polaris-types';
export type { HuronUser } from './huron-types';
export type {
	HuronOrganization,
	HuronOrganizationRole,
	HuronOrganizationSummary,
	HuronOrganizationMember,
	HuronOrganizationDirectory
} from './organization-types';
export type {
	IcechunkInspection,
	IcechunkReference,
	IcechunkSnapshot,
	IcechunkArraySchema
} from './icechunk-types';
export type { PolarisDatasetTab } from './polaris-dataset-view-types';
export type { PolarisRawTableIdentifier, PolarisRawTable } from './polaris-raw-types';
export type { PolarisBrowseBranch, PolarisBrowseData } from './polaris-browse-types';
export type {
	HuronCatalogMembershipRole,
	HuronCatalogMember,
	HuronCatalogUserSummary
} from './huron-admin-types';
export type {
	PolarisTableFormat,
	PolarisCatalogTable,
	PolarisIcebergField,
	PolarisIcebergFieldType,
	PolarisIcebergSchema,
	PolarisIcebergSnapshot,
	PolarisIcebergRef,
	PolarisIcebergTable,
	PolarisDatasetTarget,
	PolarisDatasetGrant,
	PolarisDatasetPermissions,
	PolarisApplicablePolicy,
	PolarisDatasetPolicies,
	PolarisDatasetGovernance
} from './polaris-governance-types';
