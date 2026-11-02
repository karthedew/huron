// @vitest-environment node
import { describe, expect, it } from 'vitest';
import { loginPath, safeReturnTo } from './return-to';

const ORIGIN = 'http://localhost:4173';

const KEPT: Array<[string, string]> = [
	['/', '/'],
	['/orgs/helio', '/orgs/helio'],
	[
		'/catalogs/heliophysics/search?q=wind&state=active',
		'/catalogs/heliophysics/search?q=wind&state=active'
	],
	['/orgs/helio#section', '/orgs/helio'],
	['/a/./b/../c', '/a/c'],
	['/café?q=ü', '/caf%C3%A9?q=%C3%BC'],
	['/x?q=a b', '/x?q=a%20b'],
	['/%2F%2Fevil.com', '/%2F%2Fevil.com'],
	['/%5Cevil.com', '/%5Cevil.com'],
	['/./%2F/evil.com', '/%2F/evil.com'],
	['/x?next=//evil.com', '/x?next=//evil.com'],
	['/loginx', '/loginx'],
	['/authority', '/authority']
];

const REFUSED = [
	null,
	undefined,
	'',
	'orgs/helio',
	'https://evil.com/',
	'//evil.com',
	'///evil.com',
	'/\\evil.com',
	'\\/evil.com',
	'/\t/evil.com',
	'/\n/evil.com',
	'/x\u0000',
	'/x\u007f',
	'/.//evil.com',
	'/..//evil.com',
	'/x/..//evil.com',
	'/a/b/../..//evil.com',
	'/%2e//evil.com',
	'/%2E//evil.com',
	'/.%2E//evil.com',
	'/%2e%2e//evil.com',
	'/a/%2e%2e//evil.com/x?y=1',
	'/.//',
	'/login',
	'/login/',
	'/login?returnTo=/x',
	'/logout',
	'/auth/login',
	'/auth/callback?state=x',
	'/auth',
	'/./auth/callback',
	'/x/../auth/login',
	'/%2e%2e/auth/login',
	'/%2E%2E/auth/login',
	'/%61uth/login',
	'/%6Cogin',
	'/%E0%A4%A'
];

describe('safeReturnTo', () => {
	it.each(KEPT)('keeps the same-origin path %j as %j', (value, expected) => {
		expect(safeReturnTo(value, ORIGIN)).toBe(expected);
	});

	it.each(REFUSED)('falls back to / for %j', (value) => {
		expect(safeReturnTo(value, ORIGIN)).toBe('/');
	});

	it.each([...KEPT.map(([value]) => value), ...REFUSED])(
		'answers %j with a path that stays relative to any origin and checks again unchanged',
		(value) => {
			const result = safeReturnTo(value, ORIGIN);
			expect(result).toMatch(/^\/(?![/\\])/);
			expect(new URL(result, 'http://other.invalid').host).toBe('other.invalid');
			expect(new URL(result, ORIGIN).origin).toBe(ORIGIN);
			expect(safeReturnTo(result, ORIGIN)).toBe(result);
		}
	);

	it('accepts at most 1024 characters, before and after encoding', () => {
		const longest = `/${'a'.repeat(1023)}`;
		expect(safeReturnTo(longest, ORIGIN)).toBe(longest);
		expect(safeReturnTo(`${longest}a`, ORIGIN)).toBe('/');
		expect(safeReturnTo(`/${'é'.repeat(200)}`, ORIGIN)).toBe('/');
	});

	it('produces ASCII that is safe in a Location header', () => {
		const result = safeReturnTo('/　/evil.com?é=1', ORIGIN);
		expect(result).toBe('/%E3%80%80/evil.com?%C3%A9=1');
		expect(new URL(result, ORIGIN).origin).toBe(ORIGIN);
	});
});

describe('loginPath', () => {
	it('keeps the parameter order and leaves out undefined values', () => {
		expect(loginPath()).toBe('/login');
		expect(loginPath({ returnTo: '/', status: undefined })).toBe('/login?returnTo=%2F');
		expect(loginPath({ returnTo: '/a?b=c', status: 'expired' })).toBe(
			'/login?returnTo=%2Fa%3Fb%3Dc&status=expired'
		);
		expect(loginPath({ status: 'expired', returnTo: '/x' })).toBe(
			'/login?status=expired&returnTo=%2Fx'
		);
	});
});
