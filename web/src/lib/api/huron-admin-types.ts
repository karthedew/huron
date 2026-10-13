import type { HuronUser } from './huron-types';

export type HuronCatalogMembershipRole = 'reader' | 'writer' | 'admin';

export interface HuronCatalogMember {
	user: HuronUser;
	roles: HuronCatalogMembershipRole[];
}

export interface HuronCatalogUserSummary extends HuronUser {
	catalogMemberships: { catalog: string; roles: HuronCatalogMembershipRole[] }[];
}
