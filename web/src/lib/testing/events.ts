import type { Cookies, RequestEvent, ServerLoadEvent } from '@sveltejs/kit';
import type { LayoutParams, RouteId } from '$app/types';
import type { SessionUser } from '$lib/server/sessions';
import { FakeCookies } from './fake-cookies';

export interface FakeEventInit<Params, Id> {
	url: string;
	routeId: Id;
	params: Params;
	cookies?: Cookies;
	user?: SessionUser | null;
	request?: RequestInit;
	isDataRequest?: boolean;
}

/** A complete `RequestEvent` for tests; `event.fetch` refuses to be used. */
export function fakeRequestEvent<Params extends LayoutParams<'/'>, Id extends RouteId | null>(
	init: FakeEventInit<Params, Id>
): RequestEvent<Params, Id> {
	return {
		cookies: init.cookies ?? new FakeCookies(),
		fetch: () => Promise.reject(new Error('event.fetch must not be used')),
		getClientAddress: () => '127.0.0.1',
		locals: { user: init.user ?? null },
		params: init.params,
		platform: undefined,
		request: new Request(init.url, init.request),
		route: { id: init.routeId },
		setHeaders: () => undefined,
		url: new URL(init.url),
		isDataRequest: init.isDataRequest ?? false,
		isSubRequest: false,
		isRemoteRequest: false,
		tracing: { enabled: false, root: {}, current: {} }
	};
}

/** A complete server `load` event for tests; `parent()` refuses to be used. */
export function fakeServerLoadEvent<Params extends LayoutParams<'/'>, Id extends RouteId | null>(
	init: FakeEventInit<Params, Id>
): ServerLoadEvent<Params, never, Id> {
	return {
		...fakeRequestEvent(init),
		parent: () => Promise.reject(new Error('parent() must not be used')),
		depends: () => undefined,
		untrack: (run) => run()
	};
}

/** A signed-in user as the hooks put it in `locals`. */
export function fakeUser(overrides: Partial<SessionUser> = {}): SessionUser {
	return {
		subject: 'sub-erin',
		name: 'Erin Example',
		groups: ['helio-readers'],
		expiresAt: '2026-10-29T18:00:00.000Z',
		signedInAt: '2026-10-29T10:00:00.000Z',
		...overrides
	};
}
