// @vitest-environment node
import { describe, expect, it } from 'vitest';
import { FakeCookies } from '$lib/testing/fake-cookies';
import {
	CookieJar,
	TRANSACTION_MAX_AGE_SECONDS,
	cookieName,
	cookieOptions,
	isSecureOrigin,
	transactionCookieBase
} from './cookies';

const HTTP = 'http://127.0.0.1:4173';
const HTTPS = 'https://huron.example.org';

describe('cookie names and options', () => {
	it('prefixes names with __Host- only on https', () => {
		expect(cookieName('huron_session', HTTPS)).toBe('__Host-huron_session');
		expect(cookieName('huron_session', HTTP)).toBe('huron_session');
		expect(isSecureOrigin(HTTPS)).toBe(true);
		expect(isSecureOrigin(HTTP)).toBe(false);
	});

	it('always sets path, httpOnly, sameSite and an explicit secure flag', () => {
		expect(cookieOptions(HTTP)).toEqual({
			path: '/',
			httpOnly: true,
			sameSite: 'lax',
			secure: false
		});
		expect(cookieOptions(HTTPS, { httpOnly: false, maxAge: 60 })).toEqual({
			path: '/',
			httpOnly: false,
			sameSite: 'lax',
			secure: true,
			maxAge: 60
		});
	});

	it('names a transaction cookie after the first eight characters of its state', () => {
		expect(transactionCookieBase('abcdefghijklmnop')).toBe('huron_oidc_abcdefgh');
	});
});

describe('CookieJar', () => {
	it('sets, reads and deletes the session cookie with the same options', () => {
		const cookies = new FakeCookies();
		const jar = new CookieJar(cookies, HTTPS);
		jar.setSession('session-id', 3600);
		expect(cookies.lastWrite('__Host-huron_session')).toEqual({
			name: '__Host-huron_session',
			value: 'session-id',
			options: { path: '/', httpOnly: true, sameSite: 'lax', secure: true, maxAge: 3600 }
		});
		expect(jar.session()).toBe('session-id');
		jar.deleteSession();
		expect(jar.session()).toBeUndefined();
		expect(cookies.lastWrite('__Host-huron_session')).toEqual({
			name: '__Host-huron_session',
			value: null,
			options: { path: '/', httpOnly: true, sameSite: 'lax', secure: true }
		});
	});

	it('serializes the session deletion for an answer SvelteKit adds no cookies to', () => {
		expect(new CookieJar(new FakeCookies(), HTTP).sessionDeletionHeader()).toBe(
			'huron_session=; Max-Age=0; Path=/; HttpOnly; SameSite=Lax'
		);
		expect(new CookieJar(new FakeCookies(), HTTPS).sessionDeletionHeader()).toBe(
			'__Host-huron_session=; Max-Age=0; Path=/; HttpOnly; Secure; SameSite=Lax'
		);
	});

	it('ignores cookies named for the other scheme', () => {
		const jar = new CookieJar(new FakeCookies({ huron_session: 'plain' }), HTTPS);
		expect(jar.session()).toBeUndefined();
	});

	it('lists transaction cookies by their base name', () => {
		const cookies = new FakeCookies({
			'__Host-huron_oidc_aaaaaaaa': 'sealed-a',
			'__Host-huron_oidc_': 'no-suffix',
			huron_oidc_bbbbbbbb: 'other-scheme',
			'__Host-huron_session': 'session'
		});
		const jar = new CookieJar(cookies, HTTPS);
		expect(jar.transactions()).toEqual([{ base: 'huron_oidc_aaaaaaaa', value: 'sealed-a' }]);
		jar.setTransaction('ccccccccdddd', 'sealed-c');
		expect(cookies.lastWrite('__Host-huron_oidc_cccccccc')?.options).toEqual({
			path: '/',
			httpOnly: true,
			sameSite: 'lax',
			secure: true,
			maxAge: TRANSACTION_MAX_AGE_SECONDS
		});
		expect(jar.transactions().map(({ base }) => base)).toEqual([
			'huron_oidc_aaaaaaaa',
			'huron_oidc_cccccccc'
		]);
	});

	it('reads the remembered organization only when it is a valid name', () => {
		expect(
			new CookieJar(new FakeCookies({ huron_org: 'helio' }), HTTP).rememberedOrganization()
		).toBe('helio');
		expect(
			new CookieJar(new FakeCookies({ '__Host-huron_org': 'geo' }), HTTPS).rememberedOrganization()
		).toBe('geo');
		for (const value of ['', 'Helio', '../x', 'a'.repeat(64), 'helio org']) {
			const jar = new CookieJar(new FakeCookies({ huron_org: value }), HTTP);
			expect(jar.rememberedOrganization()).toBeNull();
		}
		expect(new CookieJar(new FakeCookies(), HTTP).rememberedOrganization()).toBeNull();
	});
});
