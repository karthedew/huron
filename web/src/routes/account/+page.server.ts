import { fail, redirect } from '@sveltejs/kit';
import type { Actions, PageServerLoad } from './$types';
import { accountStore, HuronAccountError } from '$lib/server/huron-accounts';
import { getAuthenticatedPolaris } from '$lib/server/huron-auth';
import { clearHuronSession } from '$lib/server/auth';

export const load: PageServerLoad = async (event) => {
	getAuthenticatedPolaris(event);
	const layout = await event.parent();
	return { account: event.locals.user, catalogs: layout.catalogs };
};

function password(form: FormData, name: string): string {
	const value = form.get(name);
	if (typeof value !== 'string') throw new HuronAccountError('Both passwords are required.');
	return value;
}

export const actions = {
	changePassword: async (event) => {
		getAuthenticatedPolaris(event);
		const user = event.locals.user;
		if (!user) redirect(303, '/login');
		try {
			const form = await event.request.formData();
			await accountStore().changePassword(
				user.id,
				password(form, 'currentPassword'),
				password(form, 'newPassword')
			);
		} catch (error) {
			return fail(400, {
				success: false,
				message:
					error instanceof HuronAccountError ? error.message : 'Unable to change your password.'
			});
		}
		clearHuronSession(event.cookies);
		redirect(303, '/login?status=password-changed');
	}
} satisfies Actions;
