import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Cookies } from '@sveltejs/kit';
import type { HuronUser } from '$api/types';
import {
	clearHuronSession,
	createHuronSession,
	getHuronSession,
	HURON_SESSION_COOKIE,
	safeReturnTo
} from './auth';
import { getAuthenticatedPolaris, requireAdmin } from './huron-auth';
import { PolarisClient } from './polaris-client';
import {
	consumePolarisNotice,
	getPolarisClient,
	polarisSessionIdentity,
	queuePolarisNotice
} from './polaris-session';

function user(username: string, isAdmin = false): HuronUser {
	return {
		id: username,
		username,
		displayName: username,
		isAdmin,
		disabled: false,
		polarisPrincipal: `huron-${username}`,
		polarisPrincipalRole: `huron-role-${username}`,
		createdAt: '2026-10-12T00:00:00Z'
	};
}

function account(username: string) {
	return {
		user: user(username),
		authVersion: 1,
		clientId: `polaris-${username}`,
		client: new PolarisClient({
			url: 'http://localhost:8181',
			realm: 'POLARIS',
			clientId: username,
			clientSecret: `${username}-secret`
		})
	};
}

function cookieJar() {
	const values = new Map<string, string>();
	const set = vi.fn<Cookies['set']>((name, value) => {
		values.set(name, value);
	});
	const cookies: Cookies = {
		get: (name) => values.get(name),
		getAll: () => [...values].map(([name, value]) => ({ name, value })),
		set,
		delete: (name) => {
			values.delete(name);
		},
		serialize: () => ''
	};
	return { cookies, set };
}

afterEach(() => {
	vi.useRealTimers();
});

describe('Huron authenticated sessions', () => {
	it('isolates real account identities and Polaris clients behind random HttpOnly cookies', () => {
		const alice = cookieJar();
		const bob = cookieJar();
		createHuronSession(alice.cookies, account('alice'), false);
		createHuronSession(bob.cookies, account('bob'), true);
		expect(alice.cookies.get(HURON_SESSION_COOKIE)).toMatch(/^[A-Za-z0-9_-]{43}$/);
		expect(alice.cookies.get(HURON_SESSION_COOKIE)).not.toBe(bob.cookies.get(HURON_SESSION_COOKIE));
		expect(alice.set).toHaveBeenCalledWith(
			HURON_SESSION_COOKIE,
			expect.any(String),
			expect.objectContaining({ httpOnly: true, sameSite: 'lax', secure: false })
		);
		expect(bob.set).toHaveBeenCalledWith(
			HURON_SESSION_COOKIE,
			expect.any(String),
			expect.objectContaining({ secure: true })
		);
		expect(getHuronSession(alice.cookies)?.user.username).toBe('alice');
		expect(polarisSessionIdentity(alice.cookies)).toEqual({ clientId: 'polaris-alice' });
		expect(getPolarisClient(alice.cookies)).not.toBe(getPolarisClient(bob.cookies));
		queuePolarisNotice(alice.cookies, 'Saved in Polaris.');
		expect(consumePolarisNotice(bob.cookies)).toBeNull();
		expect(consumePolarisNotice(alice.cookies)).toBe('Saved in Polaris.');
		expect(consumePolarisNotice(alice.cookies)).toBeNull();
		clearHuronSession(alice.cookies);
		expect(getHuronSession(alice.cookies)).toBeUndefined();
		expect(getHuronSession(bob.cookies)?.user.username).toBe('bob');
		clearHuronSession(bob.cookies);
	});

	it('rejects forged and former preview cookies, rotates session identities and expires sessions', () => {
		vi.useFakeTimers();
		const { cookies } = cookieJar();
		cookies.set('huron_preview_session', 'previous-signed-preview', { path: '/' });
		cookies.set('huron_polaris_session', 'previous-principal', { path: '/' });
		cookies.set(HURON_SESSION_COOKIE, 'forged', { path: '/' });
		expect(getHuronSession(cookies)).toBeUndefined();
		expect(() => getPolarisClient(cookies)).toThrow('Sign in to Huron');
		createHuronSession(cookies, account('alice'), false);
		const former = cookies.get(HURON_SESSION_COOKIE);
		createHuronSession(cookies, account('bob'), false);
		expect(cookies.get(HURON_SESSION_COOKIE)).not.toBe(former);
		expect(cookies.get('huron_preview_session')).toBeUndefined();
		vi.advanceTimersByTime(8 * 60 * 60 * 1000 + 1);
		expect(getHuronSession(cookies)).toBeUndefined();
	});

	it('requires authentication for user operations and administrator authority for account management', () => {
		const url = new URL('http://localhost/admin');
		expect(() =>
			getAuthenticatedPolaris({ locals: { organization: null, user: null, polaris: null }, url })
		).toThrow();
		const scientist = account('alice');
		const event = {
			locals: { organization: null, user: scientist.user, polaris: scientist.client },
			url
		};
		expect(getAuthenticatedPolaris(event)).toBe(scientist.client);
		expect(() => requireAdmin(event)).toThrow();
		expect(() =>
			getAuthenticatedPolaris({
				...event,
				locals: { ...event.locals, user: { ...scientist.user, disabled: true } }
			})
		).toThrow();
		expect(
			requireAdmin({ ...event, locals: { ...event.locals, user: user('admin', true) } }).username
		).toBe('admin');
	});
});

describe('safeReturnTo', () => {
	it('keeps same-origin paths and their query strings', () => {
		expect(safeReturnTo('/browse?project=example-study')).toBe('/browse?project=example-study');
	});

	it('rejects absolute and protocol-relative destinations', () => {
		expect(safeReturnTo('https://example.com')).toBe('/');
		expect(safeReturnTo('//example.com')).toBe('/');
		expect(safeReturnTo('/\\\\evil.example')).toBe('/');
		expect(safeReturnTo('/\t/evil.example')).toBe('/');
		expect(safeReturnTo('/\n/evil.example')).toBe('/');
		expect(safeReturnTo(null)).toBe('/');
	});
});
