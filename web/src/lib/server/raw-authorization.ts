import { env } from '$env/dynamic/private';
import type { HuronUser, PolarisGrant, RawTarget } from '$api/types';
import { accountStore, getBootstrapPolarisClient } from './huron-accounts';
import { requireOrganizationCatalog } from './huron-organizations';
import { genericTablePath, PolarisApiError, type PolarisClient } from './polaris-client';

export type { RawTarget } from '$api/types';

export interface RawBoundTarget extends Omit<RawTarget, 'organization'> {
	endpoint: string;
	realm: string;
}

export interface RawPermissions {
	read: boolean;
	write: boolean;
	create: boolean;
}

const PRIVILEGES = {
	read: new Set(['TABLE_READ_DATA', 'TABLE_WRITE_DATA', 'CATALOG_MANAGE_CONTENT']),
	write: new Set(['TABLE_WRITE_DATA', 'CATALOG_MANAGE_CONTENT']),
	create: new Set([
		'TABLE_CREATE',
		'TABLE_FULL_METADATA',
		'CATALOG_MANAGE_METADATA',
		'CATALOG_MANAGE_CONTENT'
	])
};

/** Match the native Polaris RBAC parent hierarchy, never a string-prefix namespace. */
function applies(grant: PolarisGrant, target: RawTarget): boolean {
	if (grant.type === 'catalog')
		return grant.namespace === undefined && grant.tableName === undefined;
	if (!grant.namespace?.length) return false;
	if (grant.namespace.some((part, index) => part !== target.namespace[index])) return false;
	if (grant.type === 'namespace') return grant.tableName === undefined;
	return (
		grant.type === 'table' &&
		grant.namespace.length === target.namespace.length &&
		grant.tableName === target.name
	);
}

/** Only native data privileges confer file access; metadata and admin labels do not. */
export function rawGrantPermissions(grants: PolarisGrant[], target: RawTarget): RawPermissions {
	const result = { read: false, write: false, create: false };
	for (const grant of grants) {
		if (!applies(grant, target)) continue;
		result.read ||= PRIVILEGES.read.has(grant.privilege);
		result.write ||= PRIVILEGES.write.has(grant.privilege);
		result.create ||= grant.type !== 'table' && PRIVILEGES.create.has(grant.privilege);
	}
	return result;
}

interface AuthoritySources {
	mode: () => string | undefined;
	users: () => Promise<HuronUser[]>;
	organization: typeof requireOrganizationCatalog;
	directory: (realm: string) => Promise<PolarisClient>;
}

const sources: AuthoritySources = {
	mode: () => env.HURON_RAW_POLARIS_AUTHORIZATION,
	users: () => accountStore().listUsers(),
	organization: requireOrganizationCatalog,
	directory: getBootstrapPolarisClient
};

/** Read current account, organization and actual principal assignments for every operation. */
export async function requireRawPermissions(
	client: PolarisClient,
	user: HuronUser,
	target: RawTarget,
	required: keyof RawPermissions,
	authority: AuthoritySources = sources
): Promise<RawPermissions> {
	const current = (await authority.users()).find((entry) => entry.id === user.id);
	if (
		!current ||
		current.disabled ||
		current.polarisPrincipal !== user.polarisPrincipal ||
		current.polarisPrincipalRole !== user.polarisPrincipalRole
	)
		throw new PolarisApiError(401, 'Sign in to Huron to continue.');
	const organization = await authority.organization(current, client, target.catalog);
	if (organization.slug !== target.organization) throw new PolarisApiError(404);
	try {
		await client.request(
			genericTablePath(target.catalog, target.namespace, target.name),
			'GET',
			undefined,
			undefined,
			true
		);
	} catch (error) {
		if (!(error instanceof PolarisApiError) || error.status !== 404) throw error;
		await client.namespaceProperties(target.catalog, target.namespace);
	}
	if (authority.mode() !== 'rbac')
		throw new PolarisApiError(
			503,
			'Raw data access requires the configured Polaris RBAC authorizer.'
		);
	const directory = await authority.directory(client.connection.realm);
	const memberships = await directory.memberships(current.polarisPrincipal);
	if (!memberships.some((entry) => entry.name === current.polarisPrincipalRole))
		throw new PolarisApiError(403, 'Your managed Polaris principal membership is unavailable.');
	const assignments = await Promise.all(
		memberships.map((entry) => directory.assignments(entry.name, target.catalog))
	);
	const roleNames = [...new Set(assignments.flat().map((entry) => entry.name))];
	const grants = await Promise.all(roleNames.map((name) => directory.grants(target.catalog, name)));
	const permissions = rawGrantPermissions(grants.flat(), target);
	if (!permissions[required])
		throw new PolarisApiError(403, `Polaris does not grant Raw ${required} access to this target.`);
	return permissions;
}

export function boundRawTarget(
	target: RawTarget,
	connection: { url: string; realm: string }
): RawBoundTarget {
	return {
		endpoint: connection.url,
		realm: connection.realm,
		catalog: target.catalog,
		namespace: target.namespace,
		name: target.name
	};
}

export function parseRawTarget(value: unknown): RawTarget {
	if (typeof value !== 'object' || value === null || Array.isArray(value))
		throw new PolarisApiError(400, 'Choose a catalog, namespace and dataset.');
	const record = Object.fromEntries(Object.entries(value));
	function component(value: unknown): string {
		if (
			typeof value !== 'string' ||
			!value.trim() ||
			value.length > 255 ||
			/[\x00-\x1f\x7f/\\]/.test(value) ||
			value === '.' ||
			value === '..'
		)
			throw new PolarisApiError(400, 'Invalid Raw catalog, namespace or dataset name.');
		return value;
	}
	if (!Array.isArray(record.namespace) || !record.namespace.length || record.namespace.length > 20)
		throw new PolarisApiError(400, 'Choose an existing namespace.');
	return {
		organization: component(record.organization),
		catalog: component(record.catalog),
		namespace: record.namespace.map(component),
		name: component(record.name)
	};
}
