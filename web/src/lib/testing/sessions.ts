import type { LayoutParams, RouteId } from '$app/types';
import { sessionStore, type NewSession } from '$lib/server/sessions';
import { fakeServerLoadEvent } from './events';
import { FakeCookies } from './fake-cookies';

export interface SignedInInit<Params, Id> {
	url: string;
	routeId: Id;
	params: Params;
	/** More cookies the browser sends, by name. */
	cookies?: Record<string, string>;
	session?: Partial<NewSession>;
}

/**
 * A server `load` event of a signed-in user, the way the hooks leave it: a live session in the
 * store, its cookie, and `locals.user`. Tests reset `globalThis.huronWebSessions` afterwards.
 */
export function signedInLoadEvent<Params extends LayoutParams<'/'>, Id extends RouteId | null>(
	init: SignedInInit<Params, Id>
) {
	const { id } = sessionStore().create({
		huronToken: 'huron-token',
		tokenExpiresAt: new Date(Date.now() + 3_600_000).toISOString(),
		subject: 'dave',
		name: 'Dave Diaz',
		groups: ['helio-contributors', 'geo-readers'],
		...init.session
	});
	const cookies = new FakeCookies({ huron_session: id, ...init.cookies });
	const event = fakeServerLoadEvent({
		url: init.url,
		routeId: init.routeId,
		params: init.params,
		cookies,
		user: sessionStore().user(id)
	});
	return { sessionId: id, cookies, event };
}
