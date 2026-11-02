import { render, screen, within } from '@testing-library/svelte';
import { afterEach, describe, expect, it } from 'vitest';
import type { Collection } from '$api/types';
import { MAX_ITEMS, metadataView } from '$lib/metadata';
import { collectionFixture } from '$lib/testing/api-fixtures';
import { resetAppState } from '$lib/testing/app-state.svelte';
import { catalogPageData, collectionOf } from '$lib/testing/catalog-data';
import Page from './+page.svelte';

afterEach(resetAppState);

function show(collection: Partial<Collection> = {}, schemaResolved = true) {
	const actual = collectionFixture(collection);
	render(Page, {
		props: {
			data: {
				...catalogPageData(),
				collection: collectionOf(collection),
				trail: [],
				metadata: metadataView(actual.metadata, {
					properties: { instrument: { title: 'Sensor' } }
				}),
				problems: { rows: [], more: 0 },
				schemaResolved
			},
			params: { catalog: 'heliophysics', identifier: 'solar-wind.ace.mag-l2-2024' },
			form: undefined
		}
	});
}

describe('collection Metadata tab', () => {
	it('shows all schema fields and other fields, including nested content', () => {
		show({
			metadata: {
				title: 'MAG',
				description: 'Vectors.',
				instrument: 'MAG',
				processing: { steps: ['clean', 'calibrate'] }
			}
		});
		expect(document.title).toBe('Metadata · MAG · Huron');
		const metadata = screen.getByRole('region', { name: 'Metadata' });
		expect(within(metadata).getByText('Sensor')).toBeInTheDocument();
		expect(within(metadata).getByRole('heading', { name: 'Other fields' })).toBeInTheDocument();
		expect(within(metadata).getByText('Processing')).toBeInTheDocument();
		expect(within(metadata).getByText('calibrate')).toBeInTheDocument();
		expect(within(metadata).getByRole('link', { name: 'metadata.json' })).toHaveAttribute(
			'data-sveltekit-reload'
		);
	});

	it('explains unresolved schema fields', () => {
		show({}, false);
		expect(
			screen.getByText(
				"Its schema override no longer fits the catalog's schema, so the fields show by their keys."
			)
		).toBeInTheDocument();
	});

	it('preserves the full metadata bounds and points to its download when shortened', () => {
		show({
			metadata: { keywords: Array.from({ length: MAX_ITEMS + 7 }, (_, index) => `k${index}`) }
		});
		expect(screen.getByText('and 7 more')).toBeInTheDocument();
		expect(
			screen.getByText(
				'This metadata is too long to show in full here. metadata.json holds all of it.'
			)
		).toBeInTheDocument();
		expect(screen.getByRole('link', { name: 'metadata.json' })).toHaveAttribute(
			'href',
			'/catalogs/heliophysics/collections/solar-wind.ace.mag-l2-2024/metadata.json'
		);
	});

	it('shows a long draft without offering a metadata file it does not have', () => {
		show({
			state: 'draft',
			path: null,
			metadata: { keywords: Array.from({ length: MAX_ITEMS + 1 }, (_, index) => `k${index}`) }
		});
		expect(screen.getByText('This metadata is too long to show in full here.')).toBeInTheDocument();
		expect(screen.queryByRole('link', { name: 'metadata.json' })).toBeNull();
	});
});
