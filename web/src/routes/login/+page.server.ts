import { fail, redirect } from '@sveltejs/kit';
import { createHuronSession, safeReturnTo } from '$lib/server/auth';
import { accountStore, registrationAllowed } from '$lib/server/huron-accounts';
import { PolarisApiError } from '$lib/server/polaris-client';
import type { Actions, PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ url }) => {
	await accountStore().initialize();
	return {
		returnTo: safeReturnTo(url.searchParams.get('returnTo')),
		signedOut: url.searchParams.get('status') === 'signed-out',
		passwordChanged: url.searchParams.get('status') === 'password-changed',
		registrationAllowed: registrationAllowed()
	};
};

export const actions: Actions = {
	default: async ({ cookies, request, url }) => {
		const data = await request.formData();
		const username = String(data.get('username') ?? '').trim();
		const password = String(data.get('password') ?? '');
		const returnTo = safeReturnTo(String(data.get('returnTo') ?? '/'));
		if (!username || !password)
			return fail(400, { username, message: 'Enter your username and password.' });
		let account;
		try {
			account = await accountStore().authenticate(username, password);
		} catch (error) {
			if (error instanceof PolarisApiError)
				return fail(503, {
					username,
					message:
						'Polaris is unavailable or this account’s connection needs administrator attention.'
				});
			throw error;
		}
		if (!account)
			return fail(401, {
				username,
				message: 'The username or password is incorrect, or the account is disabled.'
			});
		createHuronSession(cookies, account, url.protocol === 'https:');
		redirect(303, returnTo);
	}
};
