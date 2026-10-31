import { render, screen, within } from '@testing-library/svelte';
import { createRawSnippet } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { CollectionSummary } from '$lib/collections';
import { page, resetAppState } from '$lib/testing/app-state.svelte';
import { catalogPageData, collectionOf } from '$lib/testing/catalog-data';
import Layout from './+layout.svelte';

vi.mock('$app/state', () => import('$lib/testing/app-state.svelte'));

afterEach(() => {
	resetAppState();
});

const ROUTE = '/(app)/catalogs/[catalog=segment]/collections/[identifier=dotted]';

function show(collection: CollectionSummary = collectionOf(), route = ROUTE) {
	page.route = { id: route };
	render(Layout, {
		props: {
			data: { ...catalogPageData(), collection, trail: [] },
			params: { catalog: 'heliophysics', identifier: 'solar-wind.ace.mag-l2-2024' },
			children: createRawSnippet(() => ({ render: () => '<p>The tab</p>' }))
		}
	});
}

describe('the collection layout', () => {
	it('heads the tabs with the title, the identifier and the state', () => {
		show(
			collectionOf({
				metadata: { title: 'ACE MAG level 2, 2024', description: 'Vectors.\nAveraged.' }
			})
		);
		const header = screen.getByRole('banner');
		expect(
			within(header).getByRole('heading', { level: 1, name: 'ACE MAG level 2, 2024' })
		).toBeInTheDocument();
		expect(within(header).getByText('heliophysics.solar-wind.ace.mag-l2-2024')).toHaveClass('mono');
		expect(within(header).getByText('Active')).toBeInTheDocument();
		expect(within(header).getByText(/^Vectors\.\s+Averaged\.$/)).toBeInTheDocument();
		expect(screen.getByText('The tab')).toBeInTheDocument();
	});

	it('names a collection without a title by its identifier, once', () => {
		show(collectionOf({ metadata: {} }));
		expect(
			screen.getByRole('heading', { level: 1, name: 'heliophysics.solar-wind.ace.mag-l2-2024' })
		).toBeInTheDocument();
		expect(screen.getAllByText('heliophysics.solar-wind.ace.mag-l2-2024')).toHaveLength(1);
	});

	it.each([
		[
			'incomplete',
			'Incomplete',
			"The catalog's schema now requires fields this collection lacks. Its files are unaffected."
		],
		[
			'draft',
			'Draft',
			'Reserved, not yet activated: no directory or files on the share; visible to contributors only.'
		]
	])('explains the %s state', (state, label, explanation) => {
		show(collectionOf({ state }));
		const header = screen.getByRole('banner');
		expect(within(header).getByText(label)).toBeInTheDocument();
		expect(within(header).getByText(explanation)).toBeInTheDocument();
	});

	it('explains an incomplete collection whose schema override no longer fits', () => {
		show(
			collectionOf({
				state: 'incomplete',
				schema_override: { type: 'object' },
				problems: [
					{
						path: '/',
						message: "schema override is incompatible: property 'mission' cannot change type",
						rule: 'schema_incompatible'
					}
				]
			})
		);
		const header = screen.getByRole('banner');
		expect(within(header).getByText('Incomplete')).toBeInTheDocument();
		expect(
			within(header).getByText(
				"Its schema override no longer fits the catalog's schema. Its files are unaffected."
			)
		).toBeInTheDocument();
		expect(within(header).queryByText(/requires fields this collection lacks/)).toBeNull();
	});

	it('links the five tabs, marks the current one and counts the files', () => {
		show(collectionOf({ file_count: 120 }), `${ROUTE}/files`);
		const tabs = within(screen.getByRole('navigation', { name: 'Collection' })).getAllByRole(
			'link'
		);
		const base = '/catalogs/heliophysics/collections/solar-wind.ace.mag-l2-2024';
		expect(tabs.map((tab) => [tab.textContent, tab.getAttribute('href')])).toEqual([
			['Overview', base],
			['Files120', `${base}/files`],
			['Commits', `${base}/commits`],
			['Activity', `${base}/activity`],
			['Schema', `${base}/schema`]
		]);
		expect(tabs.filter((tab) => tab.getAttribute('aria-current') === 'page')).toEqual([tabs[1]]);
	});

	it('counts no files of a draft', () => {
		show(collectionOf({ state: 'draft', file_count: 0 }));
		const files = within(screen.getByRole('navigation', { name: 'Collection' })).getByRole('link', {
			name: 'Files'
		});
		expect(files).toHaveTextContent(/^Files$/);
	});
});
