import { describe, expect, it } from 'vitest';
import { LIST_PAGE_SIZE, SEARCH_PAGE_SIZE, cursorParam, isCursorParameter } from './paging';

describe('paging', () => {
	it('uses 50 items per list page and 25 per search page', () => {
		expect(LIST_PAGE_SIZE).toBe(50);
		expect(SEARCH_PAGE_SIZE).toBe(25);
	});

	it('reads the cursor of a list from a URL', () => {
		expect(cursorParam(new URL('http://x/orgs?cursor=abc'))).toBe('abc');
		expect(cursorParam(new URL('http://x/n?files_cursor=f&cursor=c'), 'files_cursor')).toBe('f');
	});

	it('treats a missing or empty cursor as the first page', () => {
		expect(cursorParam(new URL('http://x/orgs'))).toBeNull();
		expect(cursorParam(new URL('http://x/orgs?cursor='))).toBeNull();
	});

	it('recognizes the parameters that carry cursors', () => {
		expect(isCursorParameter('cursor')).toBe(true);
		expect(isCursorParameter('collections_cursor')).toBe(true);
		expect(isCursorParameter('q')).toBe(false);
		expect(isCursorParameter('cursors')).toBe(false);
	});
});
