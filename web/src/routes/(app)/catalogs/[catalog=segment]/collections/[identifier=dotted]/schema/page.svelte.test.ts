import { render, screen, within } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { schemaView, type SchemaView } from '$lib/schema-view';
import { page, resetAppState } from '$lib/testing/app-state.svelte';
import { catalogPageData, collectionOf } from '$lib/testing/catalog-data';
import Page from './+page.svelte';

vi.mock('$app/state', () => import('$lib/testing/app-state.svelte'));

afterEach(() => {
	resetAppState();
});

const RESOLVED = schemaView({
	type: 'object',
	required: ['title'],
	properties: {
		title: { type: 'string', title: 'Title' },
		release_date: { type: 'string', format: 'date', title: 'Release date' }
	}
});
const OVERRIDE = schemaView({
	type: 'object',
	properties: { release_date: { type: 'string', format: 'date', title: 'Release date' } }
});

function show(schema: SchemaView | null, override: SchemaView | null, state = 'active') {
	render(Page, {
		props: {
			data: {
				...catalogPageData(),
				collection: collectionOf({
					state,
					metadata: { title: 'Wind SWE 2023' },
					schema_override: override === null ? null : { type: 'object' }
				}),
				trail: [],
				schema,
				override
			},
			params: { catalog: 'heliophysics', identifier: 'solar-wind.wind.swe-2023' },
			form: undefined
		}
	});
}

describe("a collection's schema", () => {
	it("shows the catalog's schema as the collection's when it has no override", () => {
		show(RESOLVED, null);
		expect(document.title).toBe('Schema · Wind SWE 2023 · Huron');
		expect(screen.getByRole('heading', { level: 2, name: /^Schema/ })).toHaveTextContent(
			/^Schema huron-base v1$/
		);
		expect(screen.getByRole('table', { name: "Fields of the collection's schema" })).toBeVisible();
		expect(screen.queryByRole('heading', { name: 'Schema override' })).toBeNull();
	});

	it('shows the override on its own beside the composed schema', () => {
		show(RESOLVED, OVERRIDE);
		expect(screen.getByRole('heading', { level: 2, name: /^Schema huron/ })).toHaveTextContent(
			"Schema huron-base v1 with this collection's override"
		);
		const override = screen.getByRole('region', { name: 'Schema override' });
		expect(
			within(override)
				.getByRole('table', { name: 'Fields of the schema override' })
				.querySelectorAll('tbody tr')
		).toHaveLength(1);
		expect(screen.getAllByRole('table')).toHaveLength(2);
	});

	it("points to metadata.json for the whole of an override too long to show, unless it's a draft's", () => {
		const huge = schemaView({
			type: 'object',
			properties: Object.fromEntries(Array.from({ length: 300 }, (_, index) => [`p${index}`, {}]))
		});
		show(RESOLVED, huge);
		const override = screen.getByRole('region', { name: 'Schema override' });
		expect(within(override).getByRole('link', { name: 'metadata.json' })).toHaveAttribute(
			'href',
			'/catalogs/heliophysics/collections/solar-wind.ace.mag-l2-2024/metadata.json'
		);
	});

	it('has no metadata.json to point to for a draft, nor for an override shown in full', () => {
		const huge = schemaView({
			type: 'object',
			properties: Object.fromEntries(Array.from({ length: 300 }, (_, index) => [`p${index}`, {}]))
		});
		show(RESOLVED, huge, 'draft');
		expect(screen.queryByRole('link', { name: 'metadata.json' })).toBeNull();
	});

	it('names no metadata.json beside an override shown in full', () => {
		show(RESOLVED, OVERRIDE);
		expect(screen.queryByRole('link', { name: 'metadata.json' })).toBeNull();
	});

	it('explains why there is no composed schema when the override no longer fits', () => {
		show(null, OVERRIDE);
		expect(screen.getByText(/no longer fits the catalog's schema/)).toBeInTheDocument();
		expect(screen.getAllByRole('table')).toHaveLength(1);
	});
});
