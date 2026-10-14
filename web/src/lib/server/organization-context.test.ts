import { describe, expect, it } from 'vitest';
import type { HuronOrganizationSummary } from '$api/types';
import { selectOrganization } from './organization-context';

const organizations: HuronOrganizationSummary[] = ['alpha', 'beta'].map((slug) => ({
	id: slug,
	slug,
	name: slug,
	realm: slug.toUpperCase(),
	description: '',
	createdAt: '',
	role: 'member',
	catalogNames: ['shared-name']
}));

describe('request organization selection', () => {
	it('keeps an explicitly addressed organization stable when another tab switches the cookie', () => {
		expect(selectOrganization(organizations, 'alpha', 'beta')?.realm).toBe('ALPHA');
	});
	it('conceals an unknown or unauthorized explicit root without falling back to an accessible realm', () => {
		expect(() => selectOrganization(organizations, 'private', 'alpha')).toThrow();
		expect(() => selectOrganization(organizations, '', 'alpha')).toThrow();
	});
	it('falls back only for absent URL context and safely retires a stale membership cookie', () => {
		expect(selectOrganization(organizations, null, 'beta')?.slug).toBe('beta');
		expect(selectOrganization(organizations, null, 'revoked')?.slug).toBe('alpha');
		expect(selectOrganization([], null, 'revoked')).toBeNull();
	});
});
