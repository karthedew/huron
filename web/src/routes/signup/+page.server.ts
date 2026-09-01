import { fail, redirect } from '@sveltejs/kit';
import { createPreviewSession, safeReturnTo } from '$lib/server/auth';
import type { Actions, PageServerLoad } from './$types';

export const load: PageServerLoad = ({ url }) => ({
	returnTo: safeReturnTo(url.searchParams.get('returnTo'))
});

export const actions: Actions = {
	default: async ({ cookies, request, url }) => {
		const data = await request.formData();
		const displayName = String(data.get('displayName') ?? '').trim();
		const email = String(data.get('email') ?? '').trim();
		const password = String(data.get('password') ?? '');
		const confirmation = String(data.get('confirmation') ?? '');
		const acceptedTerms = data.get('terms') === 'on';
		const returnTo = safeReturnTo(String(data.get('returnTo') ?? '/'));

		const input = { displayName, email };
		if (!displayName) return fail(400, { ...input, message: 'Enter your name.' });
		if (!/^\S+@\S+\.\S+$/.test(email)) {
			return fail(400, { ...input, message: 'Enter a valid email address.' });
		}
		if (password.length < 8) {
			return fail(400, { ...input, message: 'Use at least 8 characters for your password.' });
		}
		if (password !== confirmation) {
			return fail(400, { ...input, message: 'The passwords do not match.' });
		}
		if (!acceptedTerms) {
			return fail(400, { ...input, message: 'Accept the terms to create your account.' });
		}

		createPreviewSession(cookies, url.protocol === 'https:');
		redirect(303, returnTo);
	}
};
