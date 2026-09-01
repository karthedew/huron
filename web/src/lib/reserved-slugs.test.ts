import { describe, expect, it } from 'vitest';
import { readdirSync } from 'node:fs';
import { RESERVED_ROOT_SLUGS, isReservedRootSlug } from './reserved-slugs';

describe('reserved root slugs', () => {
	it('lists every static route directory that shadows the [org] parameter', () => {
		const staticRoots = readdirSync('src/routes', { withFileTypes: true })
			.filter((e) => e.isDirectory() && !e.name.startsWith('['))
			.map((e) => e.name)
			.sort();

		// Reserved ahead of the UI routes that will claim them; the API already
		// refuses it as an organization slug. Anything else in RESERVED_ROOT_SLUGS
		// without a route directory is a stale reservation.
		const ROUTELESS_RESERVATIONS = ['auth'];

		// If this fails in either direction, either a new root-level route was added
		// without reserving its slug (silently making an organization of that name
		// unreachable), or a reservation is now stale (its route was renamed or
		// removed and nothing reserves the slug that took its place).
		expect(
			(RESERVED_ROOT_SLUGS as readonly string[])
				.filter((s) => !ROUTELESS_RESERVATIONS.includes(s))
				.sort()
		).toEqual(staticRoots);
	});

	it('identifies reserved slugs', () => {
		expect(isReservedRootSlug('admin')).toBe(true);
		expect(isReservedRootSlug('example-org')).toBe(false);
	});
});
