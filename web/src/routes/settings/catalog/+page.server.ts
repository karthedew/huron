import { error, redirect } from '@sveltejs/kit';
import type { Actions, PageServerLoad } from './$types';
import type { HuronCatalogMember } from '$api/types';
import { accountStore } from '$lib/server/huron-accounts';
import { getAuthenticatedPolaris, requireHuronAdmin } from '$lib/server/huron-auth';
import {
	catalogMembers,
	deleteHuronCatalog,
	membershipRole,
	setCatalogMembership
} from '$lib/server/huron-catalog-admin';
import { PolarisApiError } from '$lib/server/polaris-client';
import { required, field } from '$lib/server/polaris-forms';
import { createPolarisActions, polarisActionFailure } from '$lib/server/polaris-route-actions';
import { consumePolarisNotice, queuePolarisNotice } from '$lib/server/polaris-session';
import { loadPolarisWorkspace } from '$lib/server/polaris-workspace';
import { organizationStore, requireOrganizationCatalog } from '$lib/server/huron-organizations';

export const load: PageServerLoad = async (event) => {
	const client = getAuthenticatedPolaris(event);
	const layout = await event.parent();
	const url = new URL(event.url);
	if (!url.searchParams.has('catalog') && layout.selectedCatalog)
		url.searchParams.set('catalog', layout.selectedCatalog);
	const selectedCatalog = url.searchParams.get('catalog');
	if (selectedCatalog && event.locals.user) {
		try {
			await requireOrganizationCatalog(event.locals.user, client, selectedCatalog);
		} catch (failure) {
			if (failure instanceof PolarisApiError) error(failure.status, failure.message);
			throw failure;
		}
	}
	const data = await loadPolarisWorkspace(
		selectedCatalog ? client : null,
		null,
		url,
		client.connection
	);
	data.catalogs = layout.catalogs;
	if (data.selected.catalog && !data.catalog) error(404, 'Not found');
	data.notice = consumePolarisNotice(event.cookies);
	let members: HuronCatalogMember[] = [];
	let membershipError: string | null = null;
	if (data.catalog && event.locals.user) {
		try {
			members = await catalogMembers(
				client,
				data.catalog.name,
				await organizationStore().catalogUsers(
					event.locals.user,
					data.catalog.name,
					client.connection.realm
				)
			);
		} catch (failure) {
			membershipError =
				failure instanceof PolarisApiError && [403, 404].includes(failure.status)
					? 'Catalog user administration requires Polaris catalog access-management privileges.'
					: 'Unable to load catalog users from Polaris.';
		}
	}
	return {
		...data,
		members,
		membershipError,
		isAdmin: event.locals.user?.isAdmin ?? false,
		activeTab: event.url.searchParams.get('tab') ?? 'users'
	};
};

export const actions = {
	...createPolarisActions({
		path: '/settings/catalog',
		allowedActions: [
			'updateCatalog',
			'deleteCatalog',
			'createCatalogRole',
			'updateCatalogRole',
			'deleteCatalogRole',
			'addGrant',
			'revokeGrant'
		]
	}),
	deleteCatalog: async (event) => {
		const admin = requireHuronAdmin(event);
		event.setHeaders({ 'Cache-Control': 'private, no-store' });
		try {
			const result = await deleteHuronCatalog(
				getAuthenticatedPolaris(event),
				admin,
				await event.request.formData()
			);
			queuePolarisNotice(event.cookies, result.message);
		} catch (error) {
			return polarisActionFailure('deleteCatalog', error);
		}
		redirect(
			303,
			`/admin?${new URLSearchParams({ organization: event.locals.organization?.slug ?? '' })}`
		);
	},
	setMembership: async (event) => {
		const client = getAuthenticatedPolaris(event);
		event.setHeaders({ 'Cache-Control': 'private, no-store' });
		try {
			const form = await event.request.formData();
			if (!event.locals.user) error(401, 'Sign in required.');
			await requireOrganizationCatalog(event.locals.user, client, required(form, 'catalog'));
			if (field(form, 'role') !== 'none')
				await organizationStore().ensureMembershipForCatalog(
					event.locals.user,
					required(form, 'userId'),
					required(form, 'catalog'),
					client.connection.realm
				);
			await setCatalogMembership(
				client,
				await accountStore().listUsers(),
				required(form, 'catalog'),
				required(form, 'userId'),
				membershipRole(field(form, 'role'))
			);
			return {
				action: 'setMembership',
				success: true,
				message: 'Catalog membership saved in Polaris.'
			};
		} catch (error) {
			return polarisActionFailure('setMembership', error);
		}
	}
} satisfies Actions;
