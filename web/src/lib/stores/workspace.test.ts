import { describe, expect, it } from 'vitest';
import { browseHref } from './workspace';

describe('organization-scoped browse URLs', () => {
	it('keeps organization identity alongside same-named catalogs and exact namespace components', () => {
		const first = new URL(
			browseHref('shared', ['daily.data', 'observations / raw'], 'wind', 'first-root'),
			'http://localhost'
		);
		const second = new URL(
			browseHref('shared', ['daily.data', 'observations / raw'], 'wind', 'second-root'),
			'http://localhost'
		);
		expect(first.searchParams.get('organization')).toBe('first-root');
		expect(second.searchParams.get('organization')).toBe('second-root');
		expect(first.searchParams.get('catalog')).toBe('shared');
		expect(JSON.parse(first.searchParams.get('namespace') ?? '[]')).toEqual([
			'daily.data',
			'observations / raw'
		]);
		expect(first.searchParams.get('table')).toBe('wind');
		expect(first.href).not.toBe(second.href);
	});

	it('links directly to an organization root without selecting a catalog', () => {
		expect(browseHref('', [], '', 'research')).toBe('/browse?organization=research');
	});
});
