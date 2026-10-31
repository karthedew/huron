import { render, screen, within } from '@testing-library/svelte';
import { tick } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Collection, Commit } from '$api/types';
import { commitFixture } from '$lib/testing/api-fixtures';
import { page, resetAppState } from '$lib/testing/app-state.svelte';
import { catalogPageData, collectionOf } from '$lib/testing/catalog-data';
import Page from './+page.svelte';

vi.mock('$app/state', () => import('$lib/testing/app-state.svelte'));

afterEach(() => {
	resetAppState();
});

const BASE = '/catalogs/heliophysics/collections/solar-wind.ace.mag-l2-2024/commits';

async function show(
	commits: Commit[],
	{ collection = {}, query = '' }: { collection?: Partial<Collection>; query?: string } = {}
) {
	page.url = new URL(`http://localhost:4173${BASE}${query}`);
	render(Page, {
		props: {
			data: {
				...catalogPageData(),
				collection: collectionOf({ metadata: { title: 'ACE MAG level 2, 2024' }, ...collection }),
				trail: [],
				commits,
				nextCursor: null
			},
			params: { catalog: 'heliophysics', identifier: 'solar-wind.ace.mag-l2-2024' },
			form: undefined
		}
	});
	await tick();
}

describe("a collection's commits", () => {
	it('lists the commits, newest first', async () => {
		await show([commitFixture({ message: 'Second' }), commitFixture({ id: 'c-1', message: null })]);
		expect(document.title).toBe('Commits · ACE MAG level 2, 2024 · Huron');
		const commits = within(
			screen.getByRole('list', { name: 'Commits of ACE MAG level 2, 2024' })
		).getAllByRole('listitem');
		expect(commits).toHaveLength(2);
		expect(commits[0]).toHaveTextContent('Second');
		expect(commits[1]).toHaveTextContent('No message');
	});

	it('explains that a draft has no commits yet', async () => {
		await show([], { collection: { state: 'draft', path: null } });
		expect(screen.getByText(/nothing has been committed to it yet/)).toBeInTheDocument();
		expect(screen.queryByText('No commits yet.')).toBeNull();
	});

	it('says when a collection has no commits', async () => {
		await show([]);
		expect(screen.getByText('No commits yet.')).toBeInTheDocument();
	});

	it('says a later page that came back empty holds no commits', async () => {
		await show([], { query: '?cursor=old' });
		expect(screen.getByText('No commits on this page.')).toBeInTheDocument();
	});
});
