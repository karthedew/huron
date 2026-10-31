import { render, screen, within } from '@testing-library/svelte';
import { tick } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { AuditEntry } from '$api/types';
import { auditFixture } from '$lib/testing/api-fixtures';
import { page, resetAppState } from '$lib/testing/app-state.svelte';
import { catalogPageData, collectionOf } from '$lib/testing/catalog-data';
import Page from './+page.svelte';

vi.mock('$app/state', () => import('$lib/testing/app-state.svelte'));

afterEach(() => {
	resetAppState();
});

const BASE = '/catalogs/heliophysics/collections/solar-wind.ace.mag-l2-2024/activity';

async function show(
	entries: AuditEntry[],
	{ nextCursor = null, query = '' }: { nextCursor?: string | null; query?: string } = {}
) {
	page.url = new URL(`http://localhost:4173${BASE}${query}`);
	render(Page, {
		props: {
			data: {
				...catalogPageData(),
				collection: collectionOf({ metadata: { title: 'ACE MAG level 2, 2024' } }),
				trail: [],
				entries,
				nextCursor,
				schemas: {}
			},
			params: { catalog: 'heliophysics', identifier: 'solar-wind.ace.mag-l2-2024' },
			form: undefined
		}
	});
	await tick();
}

describe("a collection's activity", () => {
	it('lists what happened to the collection without links back to it', async () => {
		await show([
			auditFixture({ id: 2 }),
			auditFixture({
				id: 1,
				action: 'collection.create',
				detail: { identifier: 'heliophysics.solar-wind.ace.mag-l2-2024' }
			})
		]);
		expect(document.title).toBe('Activity · ACE MAG level 2, 2024 · Huron');
		const [commit, create] = within(
			screen.getByRole('list', { name: 'Collection activity' })
		).getAllByRole('listitem');
		expect(commit).toHaveTextContent('Committed files');
		expect(commit).toHaveTextContent('3 added, 0 removed · from ws-17 · revision 2');
		expect(create).toHaveTextContent('Created a collection');
		expect(within(commit).queryByRole('link')).toBeNull();
		expect(within(create).queryByRole('link')).toBeNull();
	});

	it('says when there is no activity yet', async () => {
		await show([]);
		expect(screen.getByText('No activity yet.')).toBeInTheDocument();
	});

	it('pages by the cursor alone, and says when a page holds no visible entries', async () => {
		await show([], { nextCursor: 'older', query: '?cursor=newer' });
		expect(screen.getByText('No visible entries on this page.')).toBeInTheDocument();
		expect(
			within(screen.getByRole('navigation', { name: 'Activity pages' })).getByRole('link', {
				name: 'Next page'
			})
		).toHaveAttribute('href', `${BASE}?cursor=older`);
	});

	it('says that a later page with nothing after it shows no visible entries, not that there are none', async () => {
		// A stale or foreign cursor reaches such a page.
		await show([], { query: '?cursor=x' });
		expect(screen.getByText('No visible entries on this page.')).toBeInTheDocument();
		expect(screen.queryByText('No activity yet.')).toBeNull();
		expect(
			within(screen.getByRole('navigation', { name: 'Activity pages' })).getByRole('link', {
				name: 'First page'
			})
		).toBeInTheDocument();
	});
});
