import { redirect, text } from '@sveltejs/kit';
import { publicOrigin } from '$lib/server/config';
import { authDependencies, signOut } from '$lib/server/oidc';
import type { RequestHandler } from './$types';

/**
 * A plain form POST from the web's own pages. SvelteKit checks the origin of form bodies only,
 * and only in builds, so this checks every request: a bodiless POST from another origin of the
 * same site, such as a no-cors fetch or a beacon, carries the Lax session cookie too.
 */
export const POST: RequestHandler = async ({ cookies, locals, request, url }) => {
	const deps = authDependencies();
	if (request.headers.get('origin') !== publicOrigin(deps.config, url)) {
		return text('Cross-site logout requests are forbidden', { status: 403 });
	}
	redirect(303, await signOut({ cookies, url, signedIn: locals.user !== null }, deps));
};
