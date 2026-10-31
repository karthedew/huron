import { describe, expect, it } from 'vitest';
import { ORGANIZATION_COOKIE_MAX_AGE, organizationCookie } from './organization-cookie';

describe('organizationCookie', () => {
	it('remembers an organization for a year on plain http', () => {
		expect(organizationCookie('helio', false)).toBe(
			'huron_org=helio; Path=/; SameSite=Lax; Max-Age=31536000'
		);
		expect(ORGANIZATION_COOKIE_MAX_AGE).toBe(365 * 24 * 60 * 60);
	});

	it('is Secure and __Host- prefixed on https', () => {
		expect(organizationCookie('geo', true)).toBe(
			'__Host-huron_org=geo; Path=/; SameSite=Lax; Max-Age=31536000; Secure'
		);
	});

	it('encodes the value', () => {
		expect(organizationCookie('a;b c', false)).toMatch(/^huron_org=a%3Bb%20c; /);
	});
});
