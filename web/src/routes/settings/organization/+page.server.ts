import { error } from '@sveltejs/kit';
import type { Actions, PageServerLoad } from './$types';
import { getAuthenticatedPolaris } from '$lib/server/huron-auth';
import { organizationStore } from '$lib/server/huron-organizations';
import { field, required, PolarisInputError } from '$lib/server/polaris-forms';
import { polarisActionFailure } from '$lib/server/polaris-route-actions';

export const load: PageServerLoad = async (event) => {
	getAuthenticatedPolaris(event);
	const layout = await event.parent();
	const user = event.locals.user;
	if (!user) error(401, 'Sign in required.');
	const organization = layout.organization;
	const canManage = organization?.role === 'admin';
	return {
		organization,
		canManage,
		members:
			organization && canManage ? await organizationStore().members(user, organization.slug) : []
	};
};

export const actions = {
	updateOrganization: async (event) => {
		getAuthenticatedPolaris(event);
		event.setHeaders({ 'Cache-Control': 'private, no-store' });
		try {
			if (!event.locals.user) error(401, 'Sign in required.');
			const form = await event.request.formData();
			await organizationStore().update(event.locals.user, required(form, 'organization'), {
				name: required(form, 'name'),
				description: field(form, 'description')
			});
			return {
				action: 'updateOrganization',
				success: true,
				message: 'Organization details saved.'
			};
		} catch (failure) {
			return polarisActionFailure('updateOrganization', failure);
		}
	},
	setOrganizationMembership: async (event) => {
		getAuthenticatedPolaris(event);
		event.setHeaders({ 'Cache-Control': 'private, no-store' });
		try {
			if (!event.locals.user) error(401, 'Sign in required.');
			const form = await event.request.formData();
			const role = field(form, 'role');
			if (role !== 'member' && role !== 'admin' && role !== 'none')
				throw new PolarisInputError('Choose an organization role.');
			await organizationStore().setMembership(
				event.locals.user,
				required(form, 'organization'),
				required(form, 'username'),
				role
			);
			return {
				action: 'setOrganizationMembership',
				success: true,
				message: 'Organization membership saved. Catalog grants are managed separately in Polaris.'
			};
		} catch (failure) {
			return polarisActionFailure('setOrganizationMembership', failure);
		}
	}
} satisfies Actions;
