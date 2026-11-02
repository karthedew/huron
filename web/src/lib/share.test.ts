import { describe, expect, it } from 'vitest';
import { sharePath } from './share';

describe('sharePath', () => {
	it("puts the path under the organization's root when the API names one", () => {
		expect(sharePath('/data1/huron', '/projects/huron', 'helio/heliophysics/solar-wind')).toBe(
			'/data1/huron/helio/heliophysics/solar-wind'
		);
	});

	it('falls back to the mount prefix when the organization has no root', () => {
		expect(sharePath(null, '/projects/huron', 'helio/heliophysics')).toBe(
			'/projects/huron/helio/heliophysics'
		);
	});

	it('joins a root of / or with a trailing slash with one slash', () => {
		expect(sharePath('/', '/projects/huron', 'geo/rocks')).toBe('/geo/rocks');
		expect(sharePath('/data2/huron/', '/projects/huron', 'geo/rocks')).toBe(
			'/data2/huron/geo/rocks'
		);
	});
});
