import { describe, expect, it } from 'vitest';
import { collectionFixture } from '$lib/testing/api-fixtures';
import { parsedObject } from '$lib/testing/json';
import { serializePageData } from '$lib/testing/page-data';
import {
	HEAD_DESCRIPTION_LENGTH,
	TITLE_LENGTH,
	collectionRow,
	collectionSummary,
	metadataDescription,
	metadataTitle
} from './collections';

describe('collectionRow', () => {
	it('keeps what a list shows of a collection', () => {
		expect(collectionRow(collectionFixture())).toEqual({
			id: '0192f2a4-0000-7000-8000-000000000401',
			identifier: 'heliophysics.solar-wind.ace.mag-l2-2024',
			catalog: 'heliophysics',
			state: 'active',
			title: 'ACE magnetometer level 2, 2024',
			fileCount: 3,
			updatedAt: '2026-10-03T09:00:00+00:00'
		});
	});

	it("names a collection without a title by its name, and keeps a draft's state", () => {
		const draft = collectionFixture({ name: 'mag-l1-draft', state: 'draft', metadata: {} });
		expect(collectionRow(draft)).toMatchObject({ title: 'mag-l1-draft', state: 'draft' });
	});

	it('can be page data whatever keys the metadata holds', () => {
		const collection = collectionFixture({
			metadata: {
				title: 'Proto labels',
				['__proto__']: 'top level',
				labels: { ['__proto__']: 'x', mission: 'proto' }
			}
		});
		// The API's collection itself would break the page.
		expect(() => serializePageData(collection)).toThrow('__proto__');
		const row = collectionRow(collection);
		expect(() => serializePageData([row])).not.toThrow();
		expect(row.title).toBe('Proto labels');
	});

	it('shortens a title longer than the base schema allows, as a draft or an override may hold it', () => {
		// A draft's metadata need not be valid; an override may lift huron-base's maxLength.
		const long = collectionFixture({ state: 'draft', metadata: { title: '𝕏'.repeat(1_000_000) } });
		const { title } = collectionRow(long);
		expect([...title]).toHaveLength(TITLE_LENGTH + 1);
		expect(title).toBe(`${'𝕏'.repeat(TITLE_LENGTH)}…`);
		const exact = collectionFixture({ metadata: { title: 'a'.repeat(TITLE_LENGTH) } });
		expect(collectionRow(exact).title).toBe('a'.repeat(TITLE_LENGTH));
	});
});

describe('metadataTitle', () => {
	it('reads the title the metadata gives', () => {
		expect(metadataTitle({ title: 'Encounter 17 run 001' })).toBe('Encounter 17 run 001');
		expect(metadataTitle({ title: '  padded  ' })).toBe('  padded  ');
	});

	it('has none for a missing, blank or non-text title', () => {
		expect(metadataTitle({})).toBeNull();
		expect(metadataTitle({ title: ' \t' })).toBeNull();
		expect(metadataTitle({ title: 42 })).toBeNull();
		expect(metadataTitle({ title: null })).toBeNull();
	});
});

describe('collectionSummary', () => {
	it('keeps what the head and the details of a collection show', () => {
		expect(
			collectionSummary(
				collectionFixture({
					metadata: { title: 'ACE MAG', description: 'Vectors.', labels: { mission: 'ace' } },
					schema_override: { type: 'object' }
				}),
				'/projects/huron'
			)
		).toEqual({
			id: '0192f2a4-0000-7000-8000-000000000401',
			identifier: 'heliophysics.solar-wind.ace.mag-l2-2024',
			catalog: 'heliophysics',
			state: 'active',
			title: 'ACE MAG',
			description: 'Vectors.',
			shortened: false,
			fileCount: 3,
			revision: 3,
			createdAt: '2026-10-02T09:00:00+00:00',
			createdBy: 'sub-dave',
			updatedAt: '2026-10-03T09:00:00+00:00',
			activatedAt: '2026-10-02T09:05:00+00:00',
			sharePath: '/projects/huron/helio/heliophysics/solar-wind/ace/mag-l2-2024',
			schema: { name: 'huron-base', version: 1 },
			hasOverride: true,
			overrideIncompatible: false
		});
	});

	it('tells an override that no longer fits the catalog schema from problems in the metadata', () => {
		const clash = collectionFixture({
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
		});
		expect(collectionSummary(clash, '/projects/huron').overrideIncompatible).toBe(true);
		const lacking = collectionFixture({
			state: 'incomplete',
			problems: [{ path: '/', message: "'mission' is a required property", rule: 'required' }]
		});
		expect(collectionSummary(lacking, '/projects/huron').overrideIncompatible).toBe(false);
	});

	it('gives a draft no share path, and no title or description it lacks', () => {
		const draft = collectionFixture({
			state: 'draft',
			path: null,
			activated_at: null,
			metadata: { description: '' }
		});
		expect(collectionSummary(draft, '/mnt/share')).toMatchObject({
			sharePath: null,
			activatedAt: null,
			title: null,
			description: null,
			hasOverride: false
		});
	});

	it('can be page data whatever keys the metadata holds', () => {
		const summary = collectionSummary(
			collectionFixture({ metadata: parsedObject('{"title":"P","__proto__":{"x":1}}') }),
			'/projects/huron'
		);
		expect(() => serializePageData(summary)).not.toThrow();
	});
});

describe('collectionSummary of long metadata', () => {
	it('shortens the head: the title to the base schema’s length, the description to a few pages', () => {
		const summary = collectionSummary(
			collectionFixture({
				metadata: { title: 'T'.repeat(250), description: '<'.repeat(1_000_000) }
			}),
			'/projects/huron'
		);
		expect(summary.title).toBe(`${'T'.repeat(TITLE_LENGTH)}…`);
		expect(summary.description).toBe(`${'<'.repeat(HEAD_DESCRIPTION_LENGTH)}…`);
		expect(summary.shortened).toBe(true);
	});

	it('says nothing was shortened where both fit', () => {
		const summary = collectionSummary(
			collectionFixture({
				metadata: {
					title: 'T'.repeat(TITLE_LENGTH),
					description: 'd'.repeat(HEAD_DESCRIPTION_LENGTH)
				}
			}),
			'/projects/huron'
		);
		expect(summary.shortened).toBe(false);
		expect(summary.description).toHaveLength(HEAD_DESCRIPTION_LENGTH);
	});
});

describe('metadataDescription', () => {
	it('reads the description the metadata gives, unless it is blank or not text', () => {
		expect(metadataDescription({ description: 'Flares.' })).toBe('Flares.');
		expect(metadataDescription({ description: '\n ' })).toBeNull();
		expect(metadataDescription({ description: ['a'] })).toBeNull();
		expect(metadataDescription({})).toBeNull();
	});
});
