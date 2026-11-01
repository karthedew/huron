import { render, screen, within } from '@testing-library/svelte';
import { tick } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Collection, RoleGrant } from '$api/types';
import { MAX_ITEMS, type ProblemRow } from '$lib/metadata';
import { overviewMetadata, OVERVIEW_ITEMS } from '$lib/collection-overview';
import { collectionFixture } from '$lib/testing/api-fixtures';
import { page, resetAppState } from '$lib/testing/app-state.svelte';
import { catalogPageData, catalogRole, collectionOf } from '$lib/testing/catalog-data';
import Page from './+page.svelte';

vi.mock('$app/state', () => import('$lib/testing/app-state.svelte'));

afterEach(() => {
	resetAppState();
	Reflect.deleteProperty(navigator, 'clipboard');
});

const BASE = '/catalogs/heliophysics/collections/solar-wind.ace.mag-l2-2024';
const METADATA = {
	title: 'ACE MAG level 2, 2024',
	description: 'Vectors.',
	instrument: 'MAG',
	labels: { mission: 'ace' }
};

interface ShowOptions {
	collection?: Partial<Collection>;
	roles?: RoleGrant[];
	problems?: ProblemRow[];
	moreProblems?: number;
	schemaResolved?: boolean;
}

/** A schema override that no longer fits the catalog's schema, as the API reports it. */
const INCOMPATIBLE = {
	state: 'incomplete',
	schema_override: { type: 'object' },
	problems: [
		{
			path: '/',
			message:
				"schema override is incompatible: property 'mission' is required by the parent schema and cannot change type",
			rule: 'schema_incompatible'
		}
	]
} satisfies Partial<Collection>;

async function show({
	collection = {},
	roles = [],
	problems = [],
	moreProblems = 0,
	schemaResolved = true
}: ShowOptions = {}) {
	page.url = new URL(`http://localhost:4173${BASE}`);
	const summary = collectionOf({ metadata: METADATA, ...collection });
	render(Page, {
		props: {
			data: {
				...catalogPageData({ roles }),
				collection: summary,
				trail: [],
				metadata: overviewMetadata(collectionFixture(collection).metadata, null),
				problems: { rows: problems, more: moreProblems },
				schemaResolved
			},
			params: { catalog: 'heliophysics', identifier: 'solar-wind.ace.mag-l2-2024' },
			form: undefined
		}
	});
	await tick();
}

function details() {
	return screen.getByRole('region', { name: 'Use this collection' });
}

function detail(label: string): HTMLElement {
	const term = screen.getByText(label, { selector: 'dt' });
	const value = term.nextElementSibling;
	if (!(value instanceof HTMLElement)) throw new Error(`no value for ${label}`);
	return value;
}

describe("a collection's overview", () => {
	it.each([
		[
			'draft',
			'Draft',
			'Reserved, not yet activated: no directory or files on the share; visible to contributors only.'
		],
		[
			'incomplete',
			'Incomplete',
			"The catalog's schema now requires fields this collection lacks. Its files are unaffected."
		]
	])('keeps %s state explanations in the Overview body', async (state, label, explanation) => {
		await show({ collection: { state } });
		expect(screen.getByText(label)).toBeInTheDocument();
		expect(screen.getByText(explanation)).toBeInTheDocument();
	});
	it('shows the description in Overview without embedded command panels', async () => {
		await show({
			collection: { metadata: { title: 'ACE', description: 'Vector observations.' } },
			roles: [catalogRole('catalog_admin')]
		});
		expect(screen.getByText('Vector observations.')).toBeInTheDocument();
		expect(screen.queryByRole('region', { name: 'With the CLI' })).toBeNull();
	});

	it('titles the document with the collection and its catalog', async () => {
		await show();
		expect(document.title).toBe('ACE MAG level 2, 2024 · Heliophysics · Huron');
	});

	it('shows the metadata', async () => {
		await show({ collection: { metadata: METADATA } });
		const metadata = screen.getByRole('region', { name: 'At a glance' });
		expect(within(metadata).getByText('Instrument')).toBeInTheDocument();
		expect(
			within(metadata).getByRole('link', {
				name: 'mission: ace, search the catalog for this label'
			})
		).toHaveAttribute('href', '/search?catalog=heliophysics&label=mission%3Dace');
		expect(
			screen.queryByText("Its schema override no longer fits the catalog's schema", {
				exact: false
			})
		).toBeNull();
	});

	it('links to full metadata and leaves nested or unknown fields off the Overview', async () => {
		await show({
			collection: { metadata: { ...METADATA, processing: { nested: 'Details only' } } }
		});
		expect(screen.getByRole('link', { name: 'View all metadata' })).toHaveAttribute(
			'href',
			`${BASE}/metadata`
		);
		expect(screen.queryByText('Processing')).toBeNull();
		expect(screen.queryByText('Details only')).toBeNull();
	});

	it('keeps preview chips short and directs readers to Metadata for the rest', async () => {
		const keywords = Array.from({ length: MAX_ITEMS + 7 }, (_, index) => `k${index}`);
		await show({ collection: { metadata: { ...METADATA, keywords } } });
		const metadata = screen.getByRole('region', { name: 'At a glance' });
		expect(
			within(metadata).getByText(`and ${keywords.length - OVERVIEW_ITEMS} more`)
		).toBeInTheDocument();
		expect(metadata).toHaveTextContent('This is a preview. The Metadata tab has more detail.');
	});

	it('points to full metadata when a collection has no supported discovery facts', async () => {
		await show({ collection: { metadata: { custom: { nested: true } } } });
		expect(
			screen.getByText("Explore the Metadata tab for this collection's recorded details.")
		).toBeInTheDocument();
		expect(screen.queryByText('Other fields')).toBeNull();
	});

	it('says nothing is left out of metadata that shows in full', async () => {
		await show();
		expect(screen.queryByText(/too long to show in full/)).toBeNull();
	});

	it('gives the share path, files, times, schema and metadata file of a collection', async () => {
		await show({ collection: { schema_override: { type: 'object' } } });
		screen.getByText('Record details').click();
		await tick();
		expect(
			within(detail('Share path')).getByText(
				'/projects/huron/helio/heliophysics/solar-wind/ace/mag-l2-2024'
			).tagName
		).toBe('CODE');
		expect(within(detail('Files')).getByRole('link', { name: '3 files' })).toHaveAttribute(
			'href',
			`${BASE}/files`
		);
		expect(detail('Created')).toHaveTextContent('2026-10-02 09:00 UTC by sub-dave');
		expect(detail('Updated')).toHaveTextContent('2026-10-03 09:00 UTC');
		expect(within(detail('Activated')).getByText('2026-10-02 09:05 UTC').tagName).toBe('TIME');
		expect(detail('Schema')).toHaveTextContent('huron-base v1 with an override');
		expect(within(detail('Schema')).getByRole('link')).toHaveAttribute('href', `${BASE}/schema`);
		const file = within(detail('Metadata file')).getByRole('link', { name: 'metadata.json' });
		expect(file).toHaveAttribute('href', `${BASE}/metadata.json`);
		expect(file).toHaveAttribute('data-sveltekit-reload');
	});

	it('keeps the record revision and the id in technical details', async () => {
		await show({ collection: { version: 4 } });
		const technical = screen.getByText('Record details').closest('details');
		expect(technical?.open).toBe(false);
		expect(technical).toHaveTextContent('Record revision 4');
		expect(technical).toHaveTextContent('it is not a version of the data');
		expect(technical).toHaveTextContent('0192f2a4-0000-7000-8000-000000000401');
	});

	it('copies the share path where the browser has a clipboard', async () => {
		const writeText = vi.fn(() => Promise.resolve());
		Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
		await show();
		within(details()).getByRole('button', { name: 'Copy share path' }).click();
		await tick();
		expect(writeText).toHaveBeenCalledWith(
			'/projects/huron/helio/heliophysics/solar-wind/ace/mag-l2-2024'
		);
	});

	it('gives a draft no directory, file count or metadata file', async () => {
		await show({
			collection: { state: 'draft', path: null, activated_at: null, file_count: 0 },
			roles: [catalogRole('contributor')]
		});
		expect(detail('Share path')).toHaveTextContent('No directory yet');
		expect(within(details()).queryByText('Files')).toBeNull();
		expect(within(details()).queryByText('Metadata file')).toBeNull();
		expect(screen.queryByRole('link', { name: 'metadata.json' })).toBeNull();
		screen.getByText('Record details').click();
		await tick();
		expect(detail('Activated')).toHaveTextContent('Not yet');
	});

	it('lists the problems with the fields they are about', async () => {
		await show({
			collection: { state: 'incomplete' },
			problems: [
				{ field: null, message: "'mission' is a required property" },
				{ field: 'Contacts › 1 › Email', message: "'x' is not a 'email'" }
			]
		});
		const problems = screen.getByRole('region', { name: '2 problems in the metadata' });
		expect(
			within(problems)
				.getAllByRole('listitem')
				.map((item) => item.textContent)
		).toEqual(["'mission' is a required property", "Contacts › 1 › Email: 'x' is not a 'email'"]);
		expect(problems).toHaveTextContent(
			'Once its metadata is fixed, the collection is active again.'
		);
	});

	it('counts the problems it does not list', async () => {
		await show({
			collection: { state: 'incomplete' },
			problems: [{ field: 'Keywords › 1', message: "1 is not of type 'string'" }],
			moreProblems: 120
		});
		const problems = screen.getByRole('region', { name: '121 problems in the metadata' });
		expect(
			within(problems)
				.getAllByRole('listitem')
				.map((item) => item.textContent)
		).toEqual(["Keywords › 1: 1 is not of type 'string'", 'and 120 more problems']);
	});

	it('says a schema override that no longer fits is the problem, and what makes it valid', async () => {
		await show({
			collection: INCOMPATIBLE,
			problems: [{ field: null, message: INCOMPATIBLE.problems[0].message }],
			schemaResolved: false
		});
		const problems = screen.getByRole('region', { name: '1 problem with the schema override' });
		expect(problems).toHaveTextContent(
			'The collection is active again once its schema override is fixed or removed and its metadata is valid.'
		);
		expect(problems).not.toHaveTextContent('Once its metadata is fixed');
	});

	it('tells a draft whose schema override no longer fits what activating it takes', async () => {
		await show({
			collection: { ...INCOMPATIBLE, state: 'draft', path: null },
			problems: [{ field: null, message: INCOMPATIBLE.problems[0].message }],
			schemaResolved: false
		});
		expect(
			screen.getByRole('region', { name: '1 problem with the schema override' })
		).toHaveTextContent(
			'The draft can be activated once its schema override is fixed or removed and its metadata is valid.'
		);
	});

	it('shows no problems section for a valid collection', async () => {
		await show();
		expect(screen.queryByRole('region', { name: /problems? in the metadata/ })).toBeNull();
	});
});
