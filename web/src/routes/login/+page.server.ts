import { fail, redirect } from '@sveltejs/kit';
import { createPreviewSession, safeReturnTo } from '$lib/server/auth';
import type { Actions, PageServerLoad } from './$types';

export const load: PageServerLoad = ({ url }) => ({
	returnTo: safeReturnTo(url.searchParams.get('returnTo')),
	signedOut: url.searchParams.get('status') === 'signed-out'
});

export const actions: Actions = {
	default: async ({ cookies, request, url }) => {
		const data = await request.formData();
		const email = String(data.get('email') ?? '').trim();
		const password = String(data.get('password') ?? '');
		const returnTo = safeReturnTo(String(data.get('returnTo') ?? '/'));

		if (!email || !password) {
			return fail(400, {
				email,
				message: 'Enter both your email address and password.'
			});
		}

		createPreviewSession(cookies, url.protocol === 'https:');
		redirect(303, returnTo);
	}
};
