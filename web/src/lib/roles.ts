import {
	ROLES,
	isRole,
	type Catalog,
	type Organization,
	type Role,
	type RoleGrant
} from '$api/types';
import { shortId } from './format';
import { displayName } from './names';

/** Human names of the roles. */
export const ROLE_NAMES: Readonly<Record<Role, string>> = {
	platform_admin: 'Platform administrator',
	org_admin: 'Organization administrator',
	catalog_admin: 'Catalog administrator',
	contributor: 'Contributor',
	reader: 'Reader'
};

/**
 * What each role allows, as the rest of a sentence that starts with "can". Every role also holds
 * the roles below it. The bundles are `src/huron/core/security/rbac/roles.py`; the API enforces
 * them, this text only explains them.
 */
export const ROLE_ABILITIES: Readonly<Record<Role, string>> = {
	platform_admin:
		'create organizations, publish platform schemas and administer every organization and catalog',
	org_admin:
		'create and delete catalogs, grant catalog administrators, publish organization schemas and administer every catalog of the organization',
	catalog_admin:
		'create and configure namespaces, grant contributors and readers, assign the schema and delete any collection',
	contributor:
		'create collections, edit their metadata, push files and delete the collections they created',
	reader: 'browse namespaces, collections, files and activity'
};

/** Where a role applies. */
export type RoleTarget =
	| { kind: 'platform' }
	| {
			kind: 'organization' | 'catalog';
			name: string;
			label: string;
			/** For a catalog: the display name of its organization, when visible. */
			context: string | null;
	  }
	/** A scope the visible organizations and catalogs do not name. */
	| { kind: 'unresolved'; label: string };

/** One role of the signed-in user as a sentence: `lead`, then the target, then `abilities`. */
export interface RoleSentence {
	/** Unique within one user's roles. */
	key: string;
	/** "You are a contributor to"; for the platform the sentence ends here. */
	lead: string;
	target: RoleTarget;
	/** "You can …."; empty for a role this web does not know. */
	abilities: string;
}

/** The organizations and catalogs the user can see, to name the scopes of roles. */
export interface RoleScopes {
	organizations: readonly Organization[];
	catalogs: readonly Catalog[];
}

const LEADS: Readonly<Record<Role, string>> = {
	platform_admin: 'You are a platform administrator',
	org_admin: 'You are an organization administrator of',
	catalog_admin: 'You are a catalog administrator of',
	contributor: 'You are a contributor to',
	reader: 'You are a reader of'
};

const SCOPE_ORDER = ['platform', 'organization', 'catalog'];

/**
 * The user's roles (`whoami`) as sentences, widest scope first: the platform, then
 * organizations, then catalogs, each by name.
 */
export function describeRoles(roles: readonly RoleGrant[], scopes: RoleScopes): RoleSentence[] {
	return [...roles]
		.sort((a, b) => rank(a) - rank(b))
		.map((grant) => describe(grant, scopes))
		.sort((a, b) => scopeRank(a.target) - scopeRank(b.target) || compare(a, b));
}

function describe(grant: RoleGrant, scopes: RoleScopes): RoleSentence {
	const key = `${grant.scope}:${grant.scope_id ?? ''}:${grant.role}`;
	const target = targetOf(grant, scopes);
	if (!isRole(grant.role)) {
		return { key, lead: `You hold the role ${grant.role} on`, target, abilities: '' };
	}
	return {
		key,
		lead: LEADS[grant.role],
		target,
		abilities: `You can ${ROLE_ABILITIES[grant.role]}.`
	};
}

function targetOf(grant: RoleGrant, { organizations, catalogs }: RoleScopes): RoleTarget {
	if (grant.scope === 'platform') return { kind: 'platform' };
	const id = grant.scope_id;
	if (grant.scope === 'organization') {
		const organization = organizations.find((candidate) => candidate.id === id);
		if (organization !== undefined) {
			return {
				kind: 'organization',
				name: organization.name,
				label: displayName(organization),
				context: null
			};
		}
	}
	if (grant.scope === 'catalog') {
		const catalog = catalogs.find((candidate) => candidate.id === id);
		if (catalog !== undefined) {
			const owner = organizations.find(({ name }) => name === catalog.organization);
			return {
				kind: 'catalog',
				name: catalog.name,
				label: displayName(catalog),
				context: owner === undefined ? null : displayName(owner)
			};
		}
	}
	return { kind: 'unresolved', label: id === null ? grant.scope : `${grant.scope} ${shortId(id)}` };
}

function rank(grant: RoleGrant): number {
	const index = ROLES.findIndex((role) => role === grant.role);
	return index === -1 ? ROLES.length : index;
}

function scopeRank(target: RoleTarget): number {
	return target.kind === 'unresolved' ? SCOPE_ORDER.length : SCOPE_ORDER.indexOf(target.kind);
}

/** By label, ignoring case; a fixed comparison, so server and browser agree. */
function compare(a: RoleSentence, b: RoleSentence): number {
	const left = 'label' in a.target ? a.target.label.toLowerCase() : '';
	const right = 'label' in b.target ? b.target.label.toLowerCase() : '';
	if (left === right) return 0;
	return left < right ? -1 : 1;
}
