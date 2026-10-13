import { fail, redirect } from '@sveltejs/kit';
import type { Actions, PageServerLoad } from './$types';
import type { HuronCatalogUserSummary, PolarisActionResult } from '$api/types';
import { accountStore, HuronAccountError } from '$lib/server/huron-accounts';
import { getAuthenticatedPolaris, requireHuronAdmin } from '$lib/server/huron-auth';
import {
	catalogMembers,
	createHuronCatalog,
	deleteHuronCatalog,
	membershipRole,
	setCatalogMembership
} from '$lib/server/huron-catalog-admin';
import { field, required } from '$lib/server/polaris-forms';
import { createPolarisActions, polarisActionFailure } from '$lib/server/polaris-route-actions';
import {
	polarisSettings,
	consumePolarisNotice,
	queuePolarisNotice
} from '$lib/server/polaris-session';
import { loadPolarisWorkspace } from '$lib/server/polaris-workspace';
import { organizationDirectory, organizationStore } from '$lib/server/huron-organizations';
import { PolarisInputError } from '$lib/server/polaris-forms';
import { PolarisApiError } from '$lib/server/polaris-client';

export const load: PageServerLoad = async (event) => {
	const admin = requireHuronAdmin(event);
	const client = getAuthenticatedPolaris(event);
	const data = await loadPolarisWorkspace(client, null, event.url, polarisSettings());
	data.notice = consumePolarisNotice(event.cookies);
	const users = await accountStore().listUsers();
	const catalogUsers: HuronCatalogUserSummary[] = users.map((user) => ({
		...user,
		catalogMemberships: []
	}));
	await Promise.all(
		data.catalogs.map(async (catalog) => {
			try {
				const members = await catalogMembers(client, catalog.name, users);
				for (const member of members) {
					if (member.roles.length)
						catalogUsers
							.find((user) => user.id === member.user.id)
							?.catalogMemberships.push({ catalog: catalog.name, roles: member.roles });
				}
			} catch {
				data.errors[`members:${catalog.name}`] = 'Unable to read catalog memberships from Polaris.';
			}
		})
	);
	return {
		...data,
		organizations: (await organizationDirectory(admin, client)).organizations,
		users: catalogUsers,
		activeTab: event.url.searchParams.get('tab') ?? 'catalogs'
	};
};

function password(form: FormData, name = 'password'): string {
	const value = form.get(name);
	if (typeof value !== 'string') throw new HuronAccountError('A password is required.');
	return value;
}

function accountFailure(action: string, error: unknown) {
	if (error instanceof HuronAccountError)
		return fail(400, { action, success: false, message: error.message });
	return polarisActionFailure(action, error);
}

export const actions = {
	...createPolarisActions({ path: '/admin', adminOnly: true }),
	createOrganization: async (event) => {
		const admin = requireHuronAdmin(event);
		event.setHeaders({ 'Cache-Control': 'private, no-store' });
		try {
			const form = await event.request.formData();
			const organization = await organizationStore().create(admin, {
				slug: required(form, 'slug'),
				name: required(form, 'name'),
				description: field(form, 'description')
			});
			return {
				action: 'createOrganization',
				success: true,
				message: `Organization ${organization.name} created.`
			};
		} catch (error) {
			return polarisActionFailure('createOrganization', error);
		}
	},
	assignCatalogOrganization: async (event) => {
		const admin = requireHuronAdmin(event);
		event.setHeaders({ 'Cache-Control': 'private, no-store' });
		try {
			const form = await event.request.formData();
			await organizationStore().assignCatalog(
				admin,
				required(form, 'organization'),
				required(form, 'catalog')
			);
			return {
				action: 'assignCatalogOrganization',
				success: true,
				message: 'Catalog organization saved. Polaris grants are unchanged.'
			};
		} catch (error) {
			return polarisActionFailure('assignCatalogOrganization', error);
		}
	},
	createCatalog: async (event) => {
		const admin = requireHuronAdmin(event);
		event.setHeaders({ 'Cache-Control': 'private, no-store' });
		try {
			const form = await event.request.formData();
			const organization = required(form, 'organization');
			const client = getAuthenticatedPolaris(event);
			const directory = await organizationDirectory(admin, client);
			if (!directory.organizations.some((entry) => entry.slug === organization))
				throw new PolarisInputError('Choose an existing organization.');
			const owner = directory.organizations.find((entry) =>
				entry.catalogNames.includes(required(form, 'name'))
			);
			if (owner && owner.slug !== organization)
				throw new PolarisApiError(
					409,
					'This catalog already belongs to another organization. Use Assign catalog to move an existing catalog.'
				);
			const result = await createHuronCatalog(client, admin, form);
			try {
				await organizationStore().claimCatalog(admin, organization, required(form, 'name'));
			} catch (failure) {
				if (failure instanceof PolarisApiError && failure.status === 409)
					return polarisActionFailure('createCatalog', failure);
				return fail(503, {
					action: 'createCatalog',
					success: false,
					message:
						'The catalog exists in Polaris, but organization assignment did not finish. Use Assign catalog below to complete setup.'
				});
			}
			return result;
		} catch (error) {
			return polarisActionFailure('createCatalog', error);
		}
	},
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
		redirect(303, '/admin');
	},
	createUser: async (event) => {
		const admin = requireHuronAdmin(event);
		event.setHeaders({ 'Cache-Control': 'private, no-store' });
		const form = await event.request.formData();
		let created = false;
		try {
			const user = await accountStore().createUser({
				username: required(form, 'username'),
				displayName: field(form, 'displayName'),
				password: password(form)
			});
			created = true;
			const catalog = field(form, 'catalog');
			if (catalog) {
				await organizationStore().ensureMembershipForCatalog(admin, user.id, catalog);
				await setCatalogMembership(
					getAuthenticatedPolaris(event),
					await accountStore().listUsers(),
					catalog,
					user.id,
					membershipRole(field(form, 'role') || 'reader')
				);
			}
			return {
				action: 'createUser',
				success: true,
				message: `User ${user.username} created${catalog ? ` with access to ${catalog}` : ''}. They can sign in with their username and the password you supplied.`
			} satisfies PolarisActionResult;
		} catch (error) {
			if (created)
				return fail(503, {
					action: 'createUser',
					success: false,
					message:
						'The Huron user was created, but catalog access setup did not finish. Open catalog settings and retry assigning this existing user to complete setup.'
				});
			return accountFailure('createUser', error);
		}
	},
	resetPassword: async (event) => {
		requireHuronAdmin(event);
		event.setHeaders({ 'Cache-Control': 'private, no-store' });
		try {
			const form = await event.request.formData();
			await accountStore().resetPassword(required(form, 'userId'), password(form));
			return {
				action: 'resetPassword',
				success: true,
				message: 'Password changed. Existing Huron sessions for this user have been invalidated.'
			};
		} catch (error) {
			return accountFailure('resetPassword', error);
		}
	},
	setDisabled: async (event) => {
		requireHuronAdmin(event);
		event.setHeaders({ 'Cache-Control': 'private, no-store' });
		try {
			const form = await event.request.formData();
			const disabled = field(form, 'disabled') === 'true';
			await accountStore().setDisabled(required(form, 'userId'), disabled);
			return {
				action: 'setDisabled',
				success: true,
				message: disabled
					? 'Huron login disabled and existing Huron sessions invalidated. Polaris grants remain visible for review and removal in catalog settings.'
					: 'Huron login enabled.'
			};
		} catch (error) {
			return accountFailure('setDisabled', error);
		}
	}
} satisfies Actions;
