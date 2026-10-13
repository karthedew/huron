import { fail, redirect, type ActionFailure, type RequestEvent } from '@sveltejs/kit';
import type { HuronUser, PolarisActionResult } from '$api/types';
import { getAuthenticatedPolaris, requireAdmin } from './huron-auth';
import { accountStore } from './huron-accounts';
import { isManagedCatalogRole } from './huron-catalog-admin';
import {
	executePolarisAction,
	POLARIS_ACTION_NAMES,
	type PolarisActionName
} from './polaris-actions';
import { PolarisApiError } from './polaris-client';
import { field, PolarisInputError } from './polaris-forms';
import { queuePolarisNotice } from './polaris-session';
import { requireOrganizationCatalog } from './huron-organizations';

type PolarisActionEvent = Pick<
	RequestEvent,
	'locals' | 'url' | 'cookies' | 'request' | 'setHeaders'
>;
type WrapperAction = (
	event: PolarisActionEvent
) => Promise<PolarisActionResult | ActionFailure<PolarisActionResult>>;

const GLOBAL_ADMIN_ACTIONS = new Set<PolarisActionName>([
	'createCatalog',
	'deleteCatalog',
	'createPrincipal',
	'updatePrincipal',
	'deletePrincipal',
	'rotatePrincipal',
	'resetPrincipal',
	'createPrincipalRole',
	'updatePrincipalRole',
	'deletePrincipalRole',
	'assignPrincipalRole',
	'revokePrincipalRole',
	'assignCatalogRole',
	'revokeCatalogRole'
]);

const PRINCIPAL_ACTIONS = new Set<PolarisActionName>([
	'createPrincipal',
	'updatePrincipal',
	'deletePrincipal',
	'rotatePrincipal',
	'resetPrincipal'
]);
const PRINCIPAL_ROLE_ACTIONS = new Set<PolarisActionName>([
	'createPrincipalRole',
	'updatePrincipalRole',
	'deletePrincipalRole'
]);
const CATALOG_ROLE_ACTIONS = new Set<PolarisActionName>([
	'createCatalogRole',
	'updateCatalogRole',
	'deleteCatalogRole'
]);

/** Protect Huron account identity and fixed membership contracts from advanced forms. */
export function guardManagedEntities(
	action: PolarisActionName,
	form: FormData,
	users: HuronUser[]
): void {
	const principals = new Set(users.map((user) => user.polarisPrincipal));
	const principalRoles = new Set(users.map((user) => user.polarisPrincipalRole));
	principals.add('root');
	principalRoles.add('service_admin');
	if (PRINCIPAL_ACTIONS.has(action) && principals.has(field(form, 'name')))
		throw new PolarisInputError(
			'Manage Huron accounts through Users. Their Polaris identities are protected.'
		);
	if (PRINCIPAL_ROLE_ACTIONS.has(action) && principalRoles.has(field(form, 'name')))
		throw new PolarisInputError(
			'Huron account principal roles are protected. Manage catalog access through Catalog members.'
		);
	if (
		(action === 'assignPrincipalRole' || action === 'revokePrincipalRole') &&
		(principals.has(field(form, 'principal')) || principalRoles.has(field(form, 'principalRole')))
	)
		throw new PolarisInputError(
			'Huron account principal memberships are protected. Manage catalog access through Catalog members.'
		);
	const catalogRole = CATALOG_ROLE_ACTIONS.has(action)
		? field(form, 'name')
		: field(form, 'catalogRole');
	if (
		(CATALOG_ROLE_ACTIONS.has(action) ||
			action === 'addGrant' ||
			action === 'revokeGrant' ||
			action === 'assignCatalogRole' ||
			action === 'revokeCatalogRole') &&
		isManagedCatalogRole(catalogRole)
	)
		throw new PolarisInputError(
			'Huron catalog roles and grants are fixed. Manage their assignments through Catalog members.'
		);
}

function needsManagedIdentityGuard(action: PolarisActionName): boolean {
	return (
		PRINCIPAL_ACTIONS.has(action) ||
		PRINCIPAL_ROLE_ACTIONS.has(action) ||
		action === 'assignPrincipalRole' ||
		action === 'revokePrincipalRole'
	);
}

export function polarisActionFailure(
	action: string,
	error: unknown
): ActionFailure<PolarisActionResult> {
	const status = error instanceof PolarisApiError ? error.status : 503;
	return fail(status >= 400 && status < 600 ? status : 500, {
		action,
		success: false,
		status,
		message: error instanceof PolarisApiError ? error.message : 'Unable to contact Polaris.'
	});
}

/** Share authenticated form transport while Polaris remains the permission authority. */
export function createPolarisActions(options: {
	path: '/browse' | '/admin' | '/settings/catalog';
	allowedActions?: readonly PolarisActionName[];
	adminOnly?: boolean;
}): Record<string, WrapperAction> {
	const entries: [string, WrapperAction][] = (options.allowedActions ?? POLARIS_ACTION_NAMES).map(
		(action) => [
			action,
			async (event) => {
				const client = getAuthenticatedPolaris(event);
				if (options.adminOnly || GLOBAL_ADMIN_ACTIONS.has(action)) requireAdmin(event);
				event.setHeaders({ 'Cache-Control': 'private, no-store' });
				let result: PolarisActionResult;
				try {
					const form = await event.request.formData();
					const catalog = field(form, 'catalog');
					if (catalog && event.locals.user && !event.locals.user.isAdmin)
						await requireOrganizationCatalog(event.locals.user, client, catalog);
					const users = needsManagedIdentityGuard(action) ? await accountStore().listUsers() : [];
					guardManagedEntities(action, form, users);
					result = await executePolarisAction(client, action, form);
				} catch (error) {
					return polarisActionFailure(action, error);
				}
				if (['deleteTable', 'deleteCatalog', 'deleteNamespace'].includes(action)) {
					queuePolarisNotice(event.cookies, result.message);
					const query = new URLSearchParams(event.url.search);
					for (const key of [...query.keys()]) if (key.startsWith('/')) query.delete(key);
					query.delete('table');
					query.delete('pageToken');
					if (action === 'deleteCatalog') query.delete('catalog');
					if (action === 'deleteNamespace') {
						query.delete('namespace');
						query.delete('namespacePageToken');
					}
					redirect(303, `${options.path}${query.size ? '?' + query : ''}`);
				}
				return result;
			}
		]
	);
	return Object.fromEntries(entries);
}
