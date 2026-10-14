import type { HuronUser } from './huron-types';
import type { PolarisCatalog } from './polaris-types';

/** A Huron membership root bound to one native Polaris realm. */
export interface HuronOrganization {
	id: string;
	slug: string;
	name: string;
	description: string;
	createdAt: string;
	realm: string;
}

export type HuronOrganizationRole = 'member' | 'admin';

/** Catalog names contain only catalogs visible through the current user's Polaris grants. */
export interface HuronOrganizationSummary extends HuronOrganization {
	role: HuronOrganizationRole;
	catalogNames: string[];
}

export interface HuronOrganizationMember {
	user: HuronUser;
	role: HuronOrganizationRole;
}

export interface HuronOrganizationDirectory {
	organizations: HuronOrganizationSummary[];
	catalogs: PolarisCatalog[];
}
