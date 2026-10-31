import { describe, expect, it } from 'vitest';
import { organizationFixture } from '$lib/testing/api-fixtures';
import { homeOrganization, visibleOrganization } from './organizations';

const HELIO = organizationFixture();
const GEO = organizationFixture({ id: 'o-geo', name: 'geo', display_name: 'Earth Science' });

describe('visibleOrganization', () => {
	it('finds a visible organization by name', () => {
		expect(visibleOrganization('geo', [HELIO, GEO])).toBe(GEO);
	});

	it('ignores names the user cannot see, and no name at all', () => {
		expect(visibleOrganization('astro', [HELIO, GEO])).toBeNull();
		expect(visibleOrganization(null, [HELIO])).toBeNull();
		expect(visibleOrganization(undefined, [HELIO])).toBeNull();
		expect(visibleOrganization('', [HELIO])).toBeNull();
		expect(visibleOrganization('helio', [])).toBeNull();
	});
});

describe('homeOrganization', () => {
	it('is the current organization', () => {
		expect(homeOrganization(GEO, [HELIO, GEO])).toBe(GEO);
	});

	it('is the only visible organization without a current one', () => {
		expect(homeOrganization(null, [HELIO])).toBe(HELIO);
	});

	it('is none when there is a choice, or nothing to choose', () => {
		expect(homeOrganization(null, [HELIO, GEO])).toBeNull();
		expect(homeOrganization(null, [])).toBeNull();
	});
});
