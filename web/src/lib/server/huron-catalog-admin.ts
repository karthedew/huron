import type {
	HuronCatalogMember,
	HuronCatalogMembershipRole,
	HuronUser,
	PolarisActionResult,
	PolarisGrant,
	PolarisRole
} from '$api/types';
import { executePolarisAction } from './polaris-actions';
import { management, object, PolarisApiError, type PolarisClient, role } from './polaris-client';
import {
	formProperties,
	formStorageConfig,
	field,
	confirm,
	PolarisInputError,
	required
} from './polaris-forms';

export const CATALOG_MEMBERSHIP_ROLES = {
	reader: {
		name: 'huron_reader',
		privileges: [
			'CATALOG_READ_PROPERTIES',
			'NAMESPACE_LIST',
			'NAMESPACE_READ_PROPERTIES',
			'TABLE_LIST',
			'TABLE_READ_PROPERTIES',
			'TABLE_READ_DATA'
		]
	},
	writer: {
		name: 'huron_writer',
		privileges: [
			'CATALOG_READ_PROPERTIES',
			'NAMESPACE_LIST',
			'NAMESPACE_READ_PROPERTIES',
			'NAMESPACE_CREATE',
			'TABLE_LIST',
			'TABLE_READ_PROPERTIES',
			'TABLE_READ_DATA',
			'TABLE_WRITE_DATA',
			'TABLE_CREATE',
			'TABLE_DROP'
		]
	},
	admin: {
		name: 'huron_catalog_admin',
		privileges: ['CATALOG_MANAGE_ACCESS', 'CATALOG_MANAGE_METADATA', 'CATALOG_MANAGE_CONTENT']
	}
} satisfies Record<HuronCatalogMembershipRole, { name: string; privileges: string[] }>;

const membershipRoles: HuronCatalogMembershipRole[] = ['reader', 'writer', 'admin'];
const membershipUpdates = new Map<string, Promise<void>>();

export function membershipRole(value: string): HuronCatalogMembershipRole | 'none' {
	if (value === 'none' || value === 'reader' || value === 'writer' || value === 'admin')
		return value;
	throw new PolarisInputError('Choose Reader, Writer, Catalog admin or Remove access.');
}

export function isManagedCatalogRole(name: string): boolean {
	return membershipRoles.some((entry) => CATALOG_MEMBERSHIP_ROLES[entry].name === name);
}

async function assignees(
	client: PolarisClient,
	catalog: string,
	catalogRole: string
): Promise<PolarisRole[]> {
	const entries = object(
		await client.request(
			management('catalogs', catalog, 'catalog-roles', catalogRole, 'principal-roles')
		)
	).roles;
	if (!Array.isArray(entries)) throw new PolarisApiError(502);
	return entries.map(role);
}

/** Reads catalog membership from Polaris grants, never a local membership ledger. */
export async function catalogMembers(
	client: PolarisClient,
	catalog: string,
	users: HuronUser[]
): Promise<HuronCatalogMember[]> {
	const available = await client.catalogRoles(catalog);
	const assignments = await Promise.all(
		membershipRoles.map(async (entry) => ({
			role: entry,
			members: available.some(
				(candidate) => candidate.name === CATALOG_MEMBERSHIP_ROLES[entry].name
			)
				? await assignees(client, catalog, CATALOG_MEMBERSHIP_ROLES[entry].name)
				: []
		}))
	);
	return users.map((user) => ({
		user,
		roles: assignments
			.filter((assignment) =>
				assignment.members.some((candidate) => candidate.name === user.polarisPrincipalRole)
			)
			.map((assignment) => assignment.role)
	}));
}

function grantKey(grant: PolarisGrant): string {
	return JSON.stringify([
		grant.type,
		grant.privilege,
		grant.namespace ?? [],
		grant.tableName ?? '',
		grant.viewName ?? '',
		grant.policyName ?? '',
		grant.semanticModelName ?? ''
	]);
}

/** Materializes the fixed catalog-scoped roles using retryable Polaris operations. */
export async function ensureCatalogRoles(client: PolarisClient, catalog: string): Promise<void> {
	let available = await client.catalogRoles(catalog);
	for (const entry of membershipRoles) {
		const definition = CATALOG_MEMBERSHIP_ROLES[entry];
		let existing = available.find((candidate) => candidate.name === definition.name);
		if (!existing) {
			try {
				await client.request(management('catalogs', catalog, 'catalog-roles'), 'POST', {
					catalogRole: { name: definition.name, properties: { 'huron.managed-role': entry } }
				});
			} catch (error) {
				if (!(error instanceof PolarisApiError) || error.status !== 409) throw error;
			}
			available = await client.catalogRoles(catalog);
			existing = available.find((candidate) => candidate.name === definition.name);
		}
		if (!existing || existing.properties['huron.managed-role'] !== entry)
			throw new PolarisApiError(
				409,
				`Catalog role ${definition.name} already exists without the Huron managed-role marker. Rename that role in Polaris before assigning Huron membership.`
			);
		const desired: PolarisGrant[] = definition.privileges.map((privilege) => ({
			type: 'catalog',
			privilege
		}));
		const existingGrants = await client.grants(catalog, definition.name);
		const path = management('catalogs', catalog, 'catalog-roles', definition.name, 'grants');
		for (const grant of existingGrants) {
			if (!desired.some((candidate) => grantKey(candidate) === grantKey(grant)))
				await client.request(`${path}?cascade=true`, 'POST', { grant });
		}
		for (const grant of desired) await client.request(path, 'PUT', { grant });
	}
}

/** Serializes local membership changes so concurrent removals preserve an administrator. */
export async function setCatalogMembership(
	client: PolarisClient,
	users: HuronUser[],
	catalog: string,
	userId: string,
	selectedRole: HuronCatalogMembershipRole | 'none'
): Promise<void> {
	const previous = membershipUpdates.get(catalog) ?? Promise.resolve();
	let release = () => {};
	const pending = new Promise<void>((resolve) => {
		release = resolve;
	});
	membershipUpdates.set(catalog, pending);
	await previous;
	try {
		await updateCatalogMembership(client, users, catalog, userId, selectedRole);
	} finally {
		release();
		if (membershipUpdates.get(catalog) === pending) membershipUpdates.delete(catalog);
	}
}

/** Replaces only the user's Huron-managed roles in one selected Polaris catalog. */
async function updateCatalogMembership(
	client: PolarisClient,
	users: HuronUser[],
	catalog: string,
	userId: string,
	selectedRole: HuronCatalogMembershipRole | 'none'
): Promise<void> {
	const members = await catalogMembers(client, catalog, users);
	const user = users.find((candidate) => candidate.id === userId);
	if (!user) throw new PolarisInputError('Choose an existing Huron user.');
	if (user.disabled && selectedRole !== 'none')
		throw new PolarisInputError('Enable this Huron user before granting catalog access.');
	if (user.isAdmin && selectedRole !== 'admin')
		throw new PolarisInputError(
			'The default Huron administrator must retain catalog admin access.'
		);
	const current = members.find((member) => member.user.id === userId)?.roles ?? [];
	if (
		current.includes('admin') &&
		selectedRole !== 'admin' &&
		!members.some(
			(member) =>
				member.user.id !== userId && !member.user.disabled && member.roles.includes('admin')
		)
	)
		throw new PolarisInputError(
			'Keep at least one active catalog administrator. Add another administrator before removing this access.'
		);
	try {
		if (selectedRole !== 'none') await ensureCatalogRoles(client, catalog);
		const base = management('principal-roles', user.polarisPrincipalRole, 'catalog-roles', catalog);
		// Revoke first: interrupted downgrades cannot retain the stronger managed role.
		for (const entry of current)
			if (entry !== selectedRole)
				await client.request(
					`${base}/${encodeURIComponent(CATALOG_MEMBERSHIP_ROLES[entry].name)}`,
					'DELETE'
				);
		if (selectedRole !== 'none')
			await client.request(base, 'PUT', {
				catalogRole: { name: CATALOG_MEMBERSHIP_ROLES[selectedRole].name }
			});
	} catch (error) {
		if (error instanceof PolarisApiError)
			throw new PolarisApiError(
				error.status,
				`${error.message} Some catalog roles or membership changes may already have persisted. Refresh, then retry the same user and role to complete the change.`
			);
		throw error;
	}
}

function canonical(value: unknown): string {
	if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
	if (typeof value === 'object' && value !== null)
		return `{${Object.entries(value)
			.sort(([left], [right]) => left.localeCompare(right))
			.map(([key, entry]) => `${JSON.stringify(key)}:${canonical(entry)}`)
			.join(',')}}`;
	return JSON.stringify(value) ?? '';
}

/** Retries catalog setup without adopting an existing catalog with different configuration. */
export async function createHuronCatalog(
	client: PolarisClient,
	admin: HuronUser,
	form: FormData
): Promise<PolarisActionResult> {
	if (!admin.isAdmin || admin.disabled)
		throw new PolarisApiError(403, 'Huron administrator access is required to create catalogs.');
	const name = required(form, 'name');
	const properties = formProperties(form);
	const location = field(form, 'defaultBaseLocation') || properties['default-base-location'];
	if (!location) throw new PolarisInputError('defaultBaseLocation is required.');
	properties['default-base-location'] = location;
	const storage = formStorageConfig(form);
	try {
		await executePolarisAction(client, 'createCatalog', form);
	} catch (error) {
		if (!(error instanceof PolarisApiError) || error.status !== 409) throw error;
		const existing = await client.catalog(name);
		if (
			existing.type !== 'INTERNAL' ||
			canonical(existing.properties) !== canonical(properties) ||
			canonical(existing.storageConfigInfo) !== canonical(storage)
		)
			throw new PolarisApiError(
				409,
				'A catalog with that name already exists with different configuration. Use catalog settings or choose another name.'
			);
	}
	try {
		await setCatalogMembership(client, [admin], name, admin.id, 'admin');
	} catch (error) {
		if (error instanceof PolarisApiError)
			throw new PolarisApiError(
				error.status,
				`The catalog exists in Polaris, but administrator access setup was incomplete. ${error.message} Retry creation with exactly the same configuration to finish setup.`
			);
		throw error;
	}
	return {
		action: 'createCatalog',
		success: true,
		message: `Catalog ${name} is ready in Polaris, including administrator metadata, grants and dataset access.`
	};
}

/** Drops an empty catalog after removing the roles Polaris counts as catalog children. */
export async function deleteHuronCatalog(
	client: PolarisClient,
	admin: HuronUser,
	form: FormData
): Promise<PolarisActionResult> {
	if (!admin.isAdmin || admin.disabled)
		throw new PolarisApiError(403, 'Huron administrator access is required to drop catalogs.');
	const catalog = required(form, 'catalog');
	confirm(form, catalog);
	const children = await client.namespaces(catalog);
	if (children.namespaces.length || children.nextPageToken)
		throw new PolarisInputError(
			'Remove all repositories and namespaces before dropping this catalog.'
		);
	const roles = await client.catalogRoles(catalog);
	try {
		for (const role of roles) {
			if (role.name !== 'catalog_admin')
				await client.request(management('catalogs', catalog, 'catalog-roles', role.name), 'DELETE');
		}
		await client.request(management('catalogs', catalog), 'DELETE');
	} catch (error) {
		if (error instanceof PolarisApiError)
			throw new PolarisApiError(
				error.status,
				`${error.message} Catalog roles and their grants may already have been removed. Refresh and retry dropping this empty catalog to complete cleanup.`
			);
		throw error;
	}
	return {
		action: 'deleteCatalog',
		success: true,
		message: `Catalog ${catalog} removed from Polaris. Repository files remain in storage.`
	};
}
