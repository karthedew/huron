import { describe, expect, it } from 'vitest';
import { safeReturnTo } from './auth';

describe('safeReturnTo', () => {
	it('keeps same-origin paths and their query strings', () => {
		expect(safeReturnTo('/browse?project=example-study')).toBe('/browse?project=example-study');
	});

	it('rejects absolute and protocol-relative destinations', () => {
		expect(safeReturnTo('https://example.com')).toBe('/');
		expect(safeReturnTo('//example.com')).toBe('/');
		expect(safeReturnTo('/\\\\evil.example')).toBe('/');
		expect(safeReturnTo(null)).toBe('/');
	});
});
