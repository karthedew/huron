import { render, screen, within } from '@testing-library/svelte';
import { tick } from 'svelte';
import { describe, expect, it } from 'vitest';
import type { Collection, RoleGrant } from '$api/types';
import { catalogPageData, catalogRole, collectionOf } from '$lib/testing/catalog-data';
import Page from './+page.svelte';
const INCOMPATIBLE = {
	state: 'incomplete',
	schema_override: { type: 'object' },
	problems: [{ path: '/', message: 'schema override is incompatible', rule: 'schema_incompatible' }]
} satisfies Partial<Collection>;
async function show({
	collection = {},
	roles = [],
	problems = [],
	schemaResolved = true
}: {
	collection?: Partial<Collection>;
	roles?: RoleGrant[];
	problems?: { field: string | null; message: string }[];
	schemaResolved?: boolean;
} = {}) {
	void schemaResolved;
	render(Page, {
		props: {
			data: {
				...catalogPageData({ roles }),
				collection: collectionOf(collection),
				trail: [],
				hasProblems: problems.length > 0
			},
			params: { catalog: 'heliophysics', identifier: 'solar-wind.ace.mag-l2-2024' },
			form: undefined
		}
	});
	await tick();
}
function hints() {
	return within(screen.getByRole('region', { name: 'With the CLI' })).getAllByRole('region');
}
function command(title: string): string {
	const field = within(screen.getByRole('region', { name: title })).getByRole('textbox');
	return field instanceof HTMLTextAreaElement ? field.value : '';
}
describe('collection CLI', () => {
	it('shows contributors how to replace or remove a schema override that no longer fits', async () => {
		await show({
			collection: INCOMPATIBLE,
			roles: [catalogRole('contributor')],
			problems: [{ field: null, message: INCOMPATIBLE.problems[0].message }],
			schemaResolved: false
		});
		expect(hints().map((hint) => hint.querySelector('p')?.textContent)).toEqual([
			'Select this collection',
			'Replace the schema override with one that fits the catalog schema',
			'Remove the schema override',
			'Add files to this collection'
		]);
		expect(command('Replace the schema override with one that fits the catalog schema')).toBe(
			'huron --catalog heliophysics set override <override.json> heliophysics.solar-wind.ace.mag-l2-2024'
		);
		expect(command('Remove the schema override')).toBe(
			'huron --catalog heliophysics unset override heliophysics.solar-wind.ace.mag-l2-2024'
		);
		expect(
			screen.queryByRole('region', { name: 'Complete the metadata, then publish it' })
		).toBeNull();
	});

	it('shows readers how to check the collection out, and only that', async () => {
		await show({ roles: [catalogRole('reader')] });
		expect(hints()).toHaveLength(1);
		expect(command('Select this collection')).toBe(
			'huron --catalog heliophysics checkout heliophysics.solar-wind.ace.mag-l2-2024'
		);
	});

	it('shows contributors how to add files to this collection and push them', async () => {
		await show({ roles: [catalogRole('contributor')] });
		// The hint selects this collection: `add` and `push` act on the one selected last.
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
			'Select this collection',
			'Complete the metadata, then publish it',
			'Activate this draft'
		]);
		expect(command('Activate this draft')).toBe(
			'huron --catalog heliophysics activate collection heliophysics.solar-wind.ace.mag-l2-2024'
		);
	});

	it('shows contributors how to complete the metadata of an incomplete collection', async () => {
		await show({
			collection: { state: 'incomplete' },
			roles: [catalogRole('catalog_admin')],
			problems: [{ field: null, message: "'mission' is a required property" }]
		});
		expect(command('Complete the metadata, then publish it')).toBe(
			'huron --catalog heliophysics edit meta heliophysics.solar-wind.ace.mag-l2-2024\n' +
				'huron --catalog heliophysics publish meta heliophysics.solar-wind.ace.mag-l2-2024'
		);
	});
});
