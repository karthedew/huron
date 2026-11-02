import { describe, expect, it } from 'vitest';
import { pageTitle } from './title';

describe('pageTitle', () => {
	it('names the page, its context and Huron', () => {
		expect(pageTitle('Catalogs', 'Heliophysics Division')).toBe(
			'Catalogs · Heliophysics Division · Huron'
		);
	});

	it('is just Huron without parts, and skips empty ones', () => {
		expect(pageTitle()).toBe('Huron');
		expect(pageTitle('Account', '')).toBe('Account · Huron');
	});
});
