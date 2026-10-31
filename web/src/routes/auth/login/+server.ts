import { redirect } from '@sveltejs/kit';
import { authDependencies, startSignIn } from '$lib/server/oidc';
import type { RequestHandler } from './$types';

export const GET: RequestHandler = async ({ cookies, locals, url }) => {
	const location = await startSignIn(
		{ cookies, url, signedIn: locals.user !== null },
		authDependencies()
	);
	redirect(303, location);
};
