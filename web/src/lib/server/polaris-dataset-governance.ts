import type {
	HuronUser,
	PolarisApplicablePolicy,
	PolarisDatasetGovernance,
	PolarisDatasetGrant,
	PolarisDatasetPermissions,
	PolarisDatasetPolicies,
	PolarisDatasetTarget,
	PolarisGrant
} from '$api/types';
import { getBootstrapPolarisClient } from './huron-accounts';
import {
	management,
	object,
	PolarisApiError,
	type PolarisClient,
	role,
	strings
} from './polaris-client';

export function grantAppliesToDataset(grant: PolarisGrant, target: PolarisDatasetTarget): boolean {
	if (grant.type === 'catalog') return true;
	const namespace = grant.namespace;
	if (!namespace || namespace.some((part, index) => part !== target.namespace[index])) return false;
	if (grant.type === 'namespace') return namespace.length <= target.namespace.length;
	return (
		grant.type === 'table' &&
		namespace.length === target.namespace.length &&
		grant.tableName === target.table
	);
}

function projection(
	catalogRole: string,
	principalRoles: string[],
	grants: PolarisGrant[],
	target: PolarisDatasetTarget
): PolarisDatasetGrant[] {
	return grants
		.filter((grant) => grantAppliesToDataset(grant, target))
		.map((grant) => ({
			catalogRole,
			principalRoles,
			grant,
			inherited: grant.type !== 'table',
			scopeLabel: [
				target.catalog,
				...(grant.namespace ?? []),
				...(grant.type === 'table' ? [target.table] : [])
			].join(' / ')
		}));
}

/** Capability hints follow the checked-out Polaris RBAC super-privilege rules for tables. */
export function datasetCapabilities(
	grants: PolarisDatasetGrant[]
): PolarisDatasetPermissions['capabilities'] {
	const privileges = new Set(grants.map((entry) => entry.grant.privilege));
	const writeData = privileges.has('TABLE_WRITE_DATA') || privileges.has('CATALOG_MANAGE_CONTENT');
	return {
		readMetadata: true,
		readData: writeData || privileges.has('TABLE_READ_DATA'),
		writeData,
		manageAccess:
			privileges.has('CATALOG_MANAGE_ACCESS') || privileges.has('TABLE_MANAGE_GRANTS_ON_SECURABLE')
	};
}

async function readDataset(client: PolarisClient, target: PolarisDatasetTarget): Promise<void> {
	if (target.format === 'iceberg')
		await client.icebergTable(target.catalog, target.namespace, target.table);
	else if (target.format === 'generic')
		await client.genericTable(target.catalog, target.namespace, target.table);
	else await client.table(target.catalog, target.namespace, target.table);
}

/** A trusted directory projects only this authenticated principal's grants on the disclosed table. */
async function ownPermissions(
	directory: PolarisClient,
	user: HuronUser,
	target: PolarisDatasetTarget
): Promise<PolarisDatasetPermissions> {
	const memberships = await directory.memberships(user.polarisPrincipal);
	const principalRoles = memberships.map((entry) => entry.name);
	const rolePrincipals = new Map<string, string[]>();
	await Promise.all(
		memberships.map(async (membership) => {
			for (const assignment of await directory.assignments(membership.name, target.catalog)) {
				const principals = rolePrincipals.get(assignment.name) ?? [];
				principals.push(membership.name);
				rolePrincipals.set(assignment.name, principals);
			}
		})
	);
	const applicableGrants = (
		await Promise.all(
			[...rolePrincipals].map(async ([name, principals]) =>
				projection(name, principals, await directory.grants(target.catalog, name), target)
			)
		)
	).flat();
	return {
		principal: user.polarisPrincipal,
		principalRoles,
		catalogRoles: [...rolePrincipals.keys()],
		applicableGrants,
		visibility: 'self',
		capabilities: datasetCapabilities(applicableGrants),
		notice:
			'These are your current Polaris role assignments and grants that apply to this dataset. Polaris authorizes every operation again.',
		error: null
	};
}

async function managerGrants(
	client: PolarisClient,
	target: PolarisDatasetTarget
): Promise<{ grants: PolarisDatasetGrant[]; roles: string[] }> {
	const roles = await client.catalogRoles(target.catalog);
	const grants = (
		await Promise.all(
			roles.map(async (entry) => {
				const granted = await client.grants(target.catalog, entry.name);
				const members = object(
					await client.request(
						management('catalogs', target.catalog, 'catalog-roles', entry.name, 'principal-roles')
					)
				).roles;
				if (!Array.isArray(members)) throw new PolarisApiError(502);
				return projection(
					entry.name,
					members.map(role).map((entry) => entry.name),
					granted,
					target
				);
			})
		)
	).flat();
	return { grants, roles: roles.map((entry) => entry.name) };
}

/** Require the user's own table read before and after exposing narrowly scoped authority facts. */
export async function loadDatasetPermissions(
	client: PolarisClient,
	user: HuronUser,
	target: PolarisDatasetTarget,
	directoryFactory: () => Promise<PolarisClient> = () =>
		getBootstrapPolarisClient(client.connection.realm)
): Promise<PolarisDatasetPermissions> {
	await readDataset(client, target);
	let permissions: PolarisDatasetPermissions;
	try {
		permissions = await ownPermissions(await directoryFactory(), user, target);
	} catch (error) {
		await readDataset(client, target);
		return {
			principal: user.polarisPrincipal,
			principalRoles: [],
			catalogRoles: [],
			applicableGrants: [],
			visibility: 'self',
			capabilities: { readMetadata: true, readData: false, writeData: false, manageAccess: false },
			notice:
				'Dataset metadata access was authorized by Polaris. Its configured grant facts are currently unavailable.',
			error:
				error instanceof PolarisApiError
					? error.message
					: 'Unable to read Polaris permission facts.'
		};
	}
	if (permissions.capabilities.manageAccess || user.isAdmin) {
		try {
			const visible = await managerGrants(client, target);
			permissions.applicableGrants = visible.grants;
			permissions.catalogRoles = visible.roles;
			permissions.visibility = 'catalog';
			permissions.notice =
				'Polaris authorized inspection of catalog roles and assignees. Only grants applying to this dataset are shown; parent-scope grants are inherited.';
		} catch (error) {
			if (!(error instanceof PolarisApiError) || ![403, 404].includes(error.status))
				permissions.error =
					error instanceof PolarisApiError
						? error.message
						: 'Unable to inspect catalog permission grants.';
		}
	}
	await readDataset(client, target);
	return permissions;
}

function requiredText(value: unknown): string {
	if (typeof value !== 'string') throw new PolarisApiError(502);
	return value;
}

function policy(value: unknown): PolarisApplicablePolicy {
	const entry = object(value);
	if (
		typeof entry.version !== 'number' ||
		!Number.isSafeInteger(entry.version) ||
		typeof entry.inherited !== 'boolean' ||
		typeof entry.inheritable !== 'boolean'
	)
		throw new PolarisApiError(502);
	return {
		name: requiredText(entry.name),
		namespace: strings(entry.namespace),
		policyType: requiredText(entry['policy-type']),
		version: entry.version,
		inherited: entry.inherited,
		inheritable: entry.inheritable,
		description: typeof entry.description === 'string' ? entry.description : ''
	};
}

/** Polaris's current native policy API resolves table targets as Iceberg exclusively. */
export async function loadDatasetPolicies(
	client: PolarisClient,
	target: PolarisDatasetTarget,
	pageToken = ''
): Promise<PolarisDatasetPolicies> {
	if (target.format !== 'iceberg')
		return {
			supported: false,
			policies: [],
			nextPageToken: null,
			error: null,
			message: `Native Polaris policy bindings and policy inheritance support Iceberg tables. This Polaris checkout does not support those bindings for ${target.format === 'generic' ? 'generic-table assets' : 'Icechunk repositories'}. Polaris access-control grants still apply.`
		};
	const query = new URLSearchParams({
		namespace: target.namespace.join('\x1f'),
		'target-name': target.table,
		pageSize: '100'
	});
	if (pageToken) query.set('pageToken', pageToken);
	try {
		const value = object(
			await client.request(
				`/api/catalog/polaris/v1/${encodeURIComponent(target.catalog)}/applicable-policies?${query}`,
				'GET',
				undefined,
				undefined,
				true
			)
		);
		const entries = value['applicable-policies'];
		if (!Array.isArray(entries)) throw new PolarisApiError(502);
		const next = value['next-page-token'];
		return {
			supported: true,
			policies: entries.map(policy),
			nextPageToken: typeof next === 'string' && next ? next : null,
			error: null,
			message:
				'Polaris returned the policies effective on this Iceberg table, including its native inheritance and override rules. External engines enforce the policy contents.'
		};
	} catch (error) {
		const disabled = error instanceof PolarisApiError && error.status === 406;
		return {
			supported: !disabled,
			policies: [],
			nextPageToken: null,
			message: disabled
				? 'This Polaris deployment has not enabled its native Iceberg policy service.'
				: 'Applicable Iceberg policies could not be read under your current Polaris authority.',
			error: error instanceof PolarisApiError ? error.message : 'Unable to load Polaris policies.'
		};
	}
}

export async function loadDatasetGovernance(
	client: PolarisClient,
	user: HuronUser,
	target: PolarisDatasetTarget,
	directoryFactory: () => Promise<PolarisClient> = () =>
		getBootstrapPolarisClient(client.connection.realm),
	policyPageToken = ''
): Promise<PolarisDatasetGovernance> {
	const permissions = await loadDatasetPermissions(client, user, target, directoryFactory);
	const policies = await loadDatasetPolicies(client, target, policyPageToken);
	return { permissions, policies };
}
