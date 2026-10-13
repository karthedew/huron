import { fail, redirect } from '@sveltejs/kit';
import { createHuronSession, safeReturnTo } from '$lib/server/auth';
import { accountStore, HuronAccountError, registrationAllowed } from '$lib/server/huron-accounts';
import { PolarisApiError } from '$lib/server/polaris-client';
import type { Actions, PageServerLoad } from './$types';

export const load: PageServerLoad = ({ url }) => ({
	returnTo: safeReturnTo(url.searchParams.get('returnTo')),
	registrationAllowed: registrationAllowed()
});

export const actions: Actions = {
	default: async ({ cookies, request, url }) => {
		if (!registrationAllowed())
			return fail(403, {
				username: '',
				displayName: '',
				message: 'Ask your Huron administrator to create an account and add you to a catalog.'
			});
		const data = await request.formData();
		const displayName = String(data.get('displayName') ?? '').trim();
		const username = String(data.get('username') ?? '').trim();
		const password = String(data.get('password') ?? '');
		const confirmation = String(data.get('confirmation') ?? '');
		const returnTo = safeReturnTo(String(data.get('returnTo') ?? '/'));
		const input = { displayName, username };
		if (password !== confirmation)
			return fail(400, { ...input, message: 'The passwords do not match.' });
		try {
			await accountStore().createUser({ displayName, username, password });
			const account = await accountStore().authenticate(username, password);
			if (!account)
				return fail(503, { ...input, message: 'Your account was created. Sign in to continue.' });
			createHuronSession(cookies, account, url.protocol === 'https:');
		} catch (error) {
			if (error instanceof HuronAccountError)
				return fail(400, { ...input, message: error.message });
			if (error instanceof PolarisApiError)
				return fail(503, {
					...input,
					message:
						'Polaris could not provision your account. Ask your administrator to check the connection.'
				});
			throw error;
		}
		redirect(303, returnTo);
	}
};
