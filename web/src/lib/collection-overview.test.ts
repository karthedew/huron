import { describe, expect, it } from 'vitest';
import { OVERVIEW_ITEMS, OVERVIEW_TEXT_LENGTH, overviewMetadata } from './collection-overview';
import { serializePageData } from './testing/page-data';

describe('collection overview metadata', () => {
	it('keeps discovery facts in reading order, with schema labels and formatted times', () => {
		const view = overviewMetadata(
			{
				end_time: '2024-12-31T23:59:59Z',
				start_time: '2024-01-01T00:00:00Z',
				instrument: 'MAG',
				mission: 'ACE',
				keywords: ['wind'],
				labels: { level: 'l2' },
				contacts: [{ name: 'Team' }],
				processing: { steps: ['many'] }
			},
			{
				properties: {
					instrument: { title: 'Sensor' },
					start_time: { format: 'date-time' },
					end_time: { format: 'date-time' }
				}
			}
		);
		expect(view.fields.map(({ key }) => key)).toEqual([
			'instrument',
			'mission',
			'start_time',
			'end_time',
			'keywords',
			'labels'
		]);
		expect(view.fields[0]).toMatchObject({ label: 'Sensor', value: { kind: 'text', text: 'MAG' } });
		expect(view.fields[2].value).toMatchObject({ kind: 'time', text: '2024-01-01 00:00 UTC' });
		expect(view.fields[3].value).toMatchObject({ kind: 'time', text: '2024-12-31 23:59 UTC' });
		expect(view.other).toEqual([]);
		expect(view.shortened).toBe(false);
	});

	it('does not invent facts from an unknown schema or show its required fields as missing', () => {
		expect(
			overviewMetadata(
				{ depth: 300, arbitrary: { nested: true } },
				{ required: ['instrument', 'unknown'], properties: { depth: { title: 'Depth' } } }
			)
		).toEqual({ fields: [], other: [], more: 0, shortened: false });
		expect(overviewMetadata({}, null).fields).toEqual([]);
	});

	it.each([
		{
			instrument: {},
			mission: 7,
			start_time: null,
			end_time: false,
			keywords: ['wind', 7],
			labels: { level: {} }
		},
		{ instrument: '', mission: '  ', start_time: [], end_time: {}, keywords: [], labels: {} },
		{ keywords: [''], labels: { empty: ' ' } }
	])('omits empty and malformed values: %j', (metadata) => {
		expect(overviewMetadata(metadata, null).fields).toEqual([]);
	});

	it('shows an invalid date as recorded text, without inventing an instant', () => {
		const view = overviewMetadata(
			{ start_time: 'sometime' },
			{ properties: { start_time: { format: 'date-time' } } }
		);
		expect(view.fields[0].value).toEqual({ kind: 'text', text: 'sometime' });
	});

	it('limits preview text and removes links whose visible text would be shortened', () => {
		const long = `https://example.org/${'x'.repeat(300)}`;
		const view = overviewMetadata(
			{ instrument: long },
			{ properties: { instrument: { title: '😀'.repeat(300), format: 'uri' } } }
		);
		expect([...view.fields[0].label]).toHaveLength(OVERVIEW_TEXT_LENGTH);
		expect(view.fields[0].value).toEqual({
			kind: 'text',
			text: `${long.slice(0, OVERVIEW_TEXT_LENGTH - 1)}…`
		});
		expect(view.shortened).toBe(true);
	});

	it('keeps a value at the preview boundary whole', () => {
		const text = '😀'.repeat(OVERVIEW_TEXT_LENGTH);
		const view = overviewMetadata({ instrument: text }, null);
		expect(view.fields[0].value).toEqual({ kind: 'text', text });
		expect(view.shortened).toBe(false);
	});

	it('shows only a few keywords and labels and counts the rest', () => {
		const view = overviewMetadata(
			{
				keywords: Array.from({ length: 60 }, (_, n) => `word${n}`),
				labels: Object.fromEntries(Array.from({ length: 60 }, (_, n) => [`key${n}`, 'value']))
			},
			null
		);
		for (const field of view.fields) {
			expect(field.value).toMatchObject({ more: 60 - OVERVIEW_ITEMS });
			if ('items' in field.value) expect(field.value.items).toHaveLength(OVERVIEW_ITEMS);
		}
		expect(view.shortened).toBe(true);
	});

	it('keeps short label searches and bounds long chips without changing their target', () => {
		const view = overviewMetadata(
			{ keywords: ['x'.repeat(300)], labels: { long: 'y'.repeat(300), mission: 'ace' } },
			null
		);
		expect(view.fields[0].value).toMatchObject({
			items: [`${'x'.repeat(OVERVIEW_TEXT_LENGTH - 1)}…`]
		});
		expect(view.fields[1].value).toMatchObject({
			items: [
				{ key: 'long', value: `${'y'.repeat(OVERVIEW_TEXT_LENGTH - 1)}…`, filter: null },
				{ key: 'mission', value: 'ace', filter: 'mission=ace' }
			]
		});
		expect(view.shortened).toBe(true);
	});

	it('ignores inherited fields and returns serializable views for user-chosen label keys', () => {
		const metadata = Object.create({ instrument: 'Inherited' });
		metadata.labels = JSON.parse('{"__proto__":"recorded"}');
		const view = overviewMetadata(metadata, null);
		expect(view.fields.map(({ key }) => key)).toEqual(['labels']);
		expect(() => serializePageData(view)).not.toThrow();
	});
});
