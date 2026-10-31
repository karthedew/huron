import { render, screen, within } from '@testing-library/svelte';
import { tick } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Collection, RoleGrant } from '$api/types';
import { MAX_ITEMS, metadataView, type ProblemRow } from '$lib/metadata';
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
				metadata: metadataView(collectionFixture(collection).metadata, null),
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
	return screen.getByRole('complementary', { name: 'Details' });
}

function detail(label: string): HTMLElement {
	const term = within(details()).getByText(label, { selector: 'dt' });
	const value = term.nextElementSibling;
	if (!(value instanceof HTMLElement)) throw new Error(`no value for ${label}`);
	return value;
}

/** The hints of the CLI section. */
function hints() {
	return within(screen.getByRole('region', { name: 'With the CLI' })).getAllByRole('region');
}

/** The commands of a hint, from the field that stands in for the code block without a clipboard. */
function command(title: string): string {
	const field = within(screen.getByRole('region', { name: title })).getByRole('textbox');
	return field instanceof HTMLTextAreaElement ? field.value : '';
}

describe("a collection's overview", () => {
	it('titles the document with the collection and its catalog', async () => {
		await show();
		expect(document.title).toBe('ACE MAG level 2, 2024 · Heliophysics · Huron');
	});

	it('shows the metadata', async () => {
		await show({ collection: { metadata: METADATA } });
		const metadata = screen.getByRole('region', { name: 'Metadata' });
		expect(within(metadata).getByText('Instrument')).toBeInTheDocument();
		expect(
			within(metadata).getByRole('link', {
				name: 'mission: ace, search the catalog for this label'
			})
		).toHaveAttribute('href', '/catalogs/heliophysics/search?label=mission%3Dace');
		expect(
			screen.queryByText("Its schema override no longer fits the catalog's schema", {
				exact: false
			})
		).toBeNull();
	});

	it('says why the fields show by their keys when the schema cannot be resolved', async () => {
		await show({ schemaResolved: false });
		expect(
			screen.getByText(
				"Its schema override no longer fits the catalog's schema, so the fields show by their keys."
			)
		).toBeInTheDocument();
	});

	it('points to metadata.json for what a long metadata leaves out', async () => {
		const keywords = Array.from({ length: MAX_ITEMS + 7 }, (_, index) => `k${index}`);
		await show({ collection: { metadata: { ...METADATA, keywords } } });
		const metadata = screen.getByRole('region', { name: 'Metadata' });
		expect(within(metadata).getByText('and 7 more')).toBeInTheDocument();
		expect(metadata).toHaveTextContent(
			'This metadata is too long to show in full here. metadata.json holds all of it.'
		);
		expect(within(metadata).getByRole('link', { name: 'metadata.json' })).toHaveAttribute(
			'href',
			`${BASE}/metadata.json`
		);
	});

	it('says a long draft is shortened, without a metadata file to point to', async () => {
		const keywords = Array.from({ length: MAX_ITEMS + 1 }, (_, index) => `k${index}`);
		await show({
			collection: { state: 'draft', path: null, metadata: { ...METADATA, keywords } },
			roles: [catalogRole('contributor')]
		});
		const metadata = screen.getByRole('region', { name: 'Metadata' });
		expect(metadata).toHaveTextContent('This metadata is too long to show in full here.');
		expect(within(metadata).queryByRole('link', { name: 'metadata.json' })).toBeNull();
	});

	it('says nothing is left out of metadata that shows in full', async () => {
		await show();
		expect(screen.queryByText(/too long to show in full/)).toBeNull();
	});

	it('gives the share path, files, times, schema and metadata file of a collection', async () => {
		await show({ collection: { schema_override: { type: 'object' } } });
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
		const technical = within(details()).getByText('Technical details').closest('details');
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

	it('shows contributors how to replace or remove a schema override that no longer fits', async () => {
		await show({
			collection: INCOMPATIBLE,
			roles: [catalogRole('contributor')],
			problems: [{ field: null, message: INCOMPATIBLE.problems[0].message }],
			schemaResolved: false
		});
		expect(hints().map((hint) => hint.querySelector('p')?.textContent)).toEqual([
			'Check out this collection',
			'Replace the schema override with one that fits',
			'Remove the schema override',
			'Add files to this collection'
		]);
		expect(command('Replace the schema override with one that fits')).toBe(
			'huron --catalog heliophysics meta override set <override.json> heliophysics.solar-wind.ace.mag-l2-2024'
		);
		expect(command('Remove the schema override')).toBe(
			'huron --catalog heliophysics meta override clear heliophysics.solar-wind.ace.mag-l2-2024'
		);
		expect(
			screen.queryByRole('region', { name: 'Complete the metadata, then publish it' })
		).toBeNull();
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

	it('shows readers how to check the collection out, and only that', async () => {
		await show({ roles: [catalogRole('reader')] });
		expect(hints()).toHaveLength(1);
		expect(command('Check out this collection')).toBe(
			'huron --catalog heliophysics checkout heliophysics.solar-wind.ace.mag-l2-2024'
		);
	});

	it('shows contributors how to add files to this collection and push them', async () => {
		await show({ roles: [catalogRole('contributor')] });
		// The hint checks this collection out: `add` and `push` act on the one checked out last.
		expect(command('Add files to this collection')).toBe(
			'huron --catalog heliophysics checkout heliophysics.solar-wind.ace.mag-l2-2024\n' +
				'huron --catalog heliophysics add <file>…\n' +
				'huron --catalog heliophysics push -m "<message>"'
		);
		expect(screen.queryByRole('region', { name: 'Activate this draft' })).toBeNull();
	});

	it('shows contributors how to activate a draft and complete its metadata', async () => {
		await show({
			collection: { state: 'draft', path: null },
			roles: [catalogRole('contributor')],
			problems: [{ field: null, message: "'description' is a required property" }]
		});
		expect(hints().map((hint) => hint.querySelector('p')?.textContent)).toEqual([
			'Check out this collection',
			'Complete the metadata, then publish it',
			'Activate this draft'
		]);
		expect(command('Activate this draft')).toBe(
			'huron --catalog heliophysics collection activate heliophysics.solar-wind.ace.mag-l2-2024'
		);
		expect(screen.getByRole('region', { name: '1 problem in the metadata' })).toHaveTextContent(
			'The draft can be activated once its metadata is fixed.'
		);
	});

	it('shows contributors how to complete the metadata of an incomplete collection', async () => {
		await show({
			collection: { state: 'incomplete' },
			roles: [catalogRole('catalog_admin')],
			problems: [{ field: null, message: "'mission' is a required property" }]
		});
		expect(command('Complete the metadata, then publish it')).toBe(
			'huron --catalog heliophysics meta edit heliophysics.solar-wind.ace.mag-l2-2024\n' +
				'huron --catalog heliophysics meta publish heliophysics.solar-wind.ace.mag-l2-2024'
		);
	});
});
