// @vitest-environment node
import { describe, expect, it } from 'vitest';
import type { JsonObject } from '$api/types';
import { parsedObject } from '$lib/testing/json';
import { serializePageData } from '$lib/testing/page-data';
import { huronBase, spaceWeather } from '$lib/testing/schemas';
import { isJsonObject } from './json';
import {
	MAX_ITEMS,
	MAX_LABEL_LENGTH,
	MAX_VALUES,
	PROBLEM_LENGTH,
	TEXT_BUDGET,
	VALUE_LENGTH,
	humanizeKey,
	labelChips,
	metadataView,
	pointerLabel,
	problemRows,
	type MetadataField,
	type MetadataValue
} from './metadata';

/** The metadata of mag-l2-2024 in the e2e fixture. */
const MAG = {
	title: 'ACE MAG level 2, 2024',
	description: 'Interplanetary magnetic field vectors from the ACE magnetometer.',
	keywords: ['magnetic field', 'solar wind', 'L1'],
	contacts: [
		{ name: 'ACE MAG team', email: 'ace-mag@example.org' },
		{ name: 'Science data center' }
	],
	instrument: 'MAG',
	start_time: '2024-01-01T00:00:00Z',
	end_time: '2024-12-31T23:59:59Z',
	labels: { mission: 'ace', instrument: 'mag', level: 'l2' }
};

/** A schema with one property of every kind a schema document may describe. */
const EVERY_KIND: JsonObject = {
	type: 'object',
	required: ['release'],
	properties: {
		release: { type: 'string', format: 'date', title: 'Release date' },
		measured: { type: 'string', format: 'date-time' },
		contact: { type: 'string', format: 'email' },
		landing_page: { type: 'string', format: 'uri', title: 'Landing page' },
		cadence: { type: 'integer' },
		fill: { type: 'number' },
		calibrated: { type: 'boolean' },
		bands: { type: 'array', items: { type: 'number' } },
		processing: {
			type: 'object',
			required: ['version'],
			properties: { version: { type: 'string', title: 'Version' }, level: { type: 'string' } }
		}
	}
};

function value(fields: readonly MetadataField[], key: string): MetadataValue | undefined {
	return fields.find((field) => field.key === key)?.value;
}

describe('metadataView', () => {
	it("lists the schema's fields in walkthrough order without the title and description", () => {
		const view = metadataView(MAG, huronBase());
		expect(view.fields.map(({ key, label }) => [key, label])).toEqual([
			['contacts', 'Contacts'],
			['end_time', 'End time'],
			['instrument', 'Instrument'],
			['keywords', 'Keywords'],
			['labels', 'Labels'],
			['start_time', 'Start time']
		]);
		expect(view.other).toEqual([]);
		expect(view).toMatchObject({ more: 0, shortened: false });
	});

	it('puts the required fields first, in the order the schema requires them', () => {
		const view = metadataView(
			{ title: 'Kp', description: 'Index', mission: 'ground', instrument: 'magnetometers' },
			spaceWeather()
		);
		expect(view.fields.map(({ key }) => key)).toEqual(['mission', 'instrument']);
	});

	it('lists the fields the schema does not name under other fields, by key', () => {
		const view = metadataView(
			{ ...MAG, zeta: 'last', alpha: 'first', Beta: 'capital' },
			huronBase()
		);
		expect(view.other.map(({ key, label }) => [key, label])).toEqual([
			['Beta', 'Beta'],
			['alpha', 'Alpha'],
			['zeta', 'Zeta']
		]);
	});

	it('marks required fields the metadata lacks, and only those', () => {
		const view = metadataView({ title: 'Flare list 2024', description: 'Flares' }, spaceWeather());
		expect(view.fields).toEqual([{ key: 'mission', label: 'Mission', value: { kind: 'missing' } }]);
	});

	it('marks a missing description, which the head then cannot show', () => {
		const view = metadataView({ title: 'ACE MAG level 1 (draft)' }, huronBase());
		expect(view.fields).toEqual([
			{ key: 'description', label: 'Description', value: { kind: 'missing' } }
		]);
	});

	it('keeps a title or description the head cannot show among the fields', () => {
		const view = metadataView({ title: 42, description: ' ' }, huronBase());
		expect(view.fields).toEqual([
			{ key: 'title', label: 'Title', value: { kind: 'number', text: '42' } },
			{ key: 'description', label: 'Description', value: { kind: 'text', text: ' ' } }
		]);
	});

	it('shows every field by its key, in key order, when the schema could not be resolved', () => {
		const view = metadataView({ title: 'T', zeta: 1, alpha: 'a' }, null);
		expect(view.fields.map(({ key, label }) => [key, label])).toEqual([
			['alpha', 'Alpha'],
			['zeta', 'Zeta']
		]);
		expect(view.other).toEqual([]);
	});

	it('shows date-times as fixed UTC text with their instant', () => {
		const fields = metadataView(MAG, huronBase()).fields;
		expect(value(fields, 'start_time')).toEqual({
			kind: 'time',
			text: '2024-01-01 00:00 UTC',
			datetime: '2024-01-01T00:00:00.000Z'
		});
		const shifted = metadataView({ measured: '2024-03-01T01:30:00+02:00' }, EVERY_KIND).fields;
		expect(value(shifted, 'measured')).toEqual({
			kind: 'time',
			text: '2024-02-29 23:30 UTC',
			datetime: '2024-02-29T23:30:00.000Z'
		});
	});

	it('shows a date-time it cannot place in time as the text it is', () => {
		for (const text of [
			'2024-01-01T10:00:00',
			'2024-02-30T00:00:00Z',
			'2024-01-01T24:00:00Z',
			'1',
			'next Tuesday'
		]) {
			const fields = metadataView({ measured: text }, EVERY_KIND).fields;
			expect(value(fields, 'measured'), text).toEqual({ kind: 'text', text });
		}
	});

	it('shows a date-time as the text it is when its instant falls before year 1 or after 9999', () => {
		// Each one is valid RFC 3339; only the offset carries the first two out of range.
		for (const text of [
			'9999-12-31T23:59:59-23:59',
			'0001-01-01T00:00:00+00:01',
			'0000-06-15T12:00:00Z'
		]) {
			const fields = metadataView({ measured: text }, EVERY_KIND).fields;
			expect(value(fields, 'measured'), text).toEqual({ kind: 'text', text });
		}
		const last = metadataView({ measured: '9999-12-31T23:59:59+23:59' }, EVERY_KIND).fields;
		expect(value(last, 'measured')).toEqual({
			kind: 'time',
			text: '9999-12-31 00:00 UTC',
			datetime: '9999-12-31T00:00:59.000Z'
		});
		const first = metadataView({ measured: '0001-01-01T00:00:00Z' }, EVERY_KIND).fields;
		expect(value(first, 'measured')).toEqual({
			kind: 'time',
			text: '0001-01-01 00:00 UTC',
			datetime: '0001-01-01T00:00:00.000Z'
		});
	});

	it('shows dates as they are written, when the day exists', () => {
		expect(value(metadataView({ release: '2024-03-15' }, EVERY_KIND).fields, 'release')).toEqual({
			kind: 'time',
			text: '2024-03-15',
			datetime: '2024-03-15'
		});
		for (const text of ['0001-01-01', '9999-12-31']) {
			expect(value(metadataView({ release: text }, EVERY_KIND).fields, 'release'), text).toEqual({
				kind: 'time',
				text,
				datetime: text
			});
		}
		// HTML has no year 0, so `<time datetime>` could not hold it.
		for (const text of ['2024-02-30', '15/03/2024', '2024-3-15', '0000-01-01']) {
			expect(value(metadataView({ release: text }, EVERY_KIND).fields, 'release'), text).toEqual({
				kind: 'text',
				text
			});
		}
	});

	it('links email addresses with mailto:, and nothing else that claims to be one', () => {
		const fields = metadataView({ contact: 'ace-mag@example.org' }, EVERY_KIND).fields;
		expect(value(fields, 'contact')).toEqual({
			kind: 'email',
			text: 'ace-mag@example.org',
			href: 'mailto:ace-mag@example.org'
		});
		for (const text of ["o'brien+ace@example.org", 'ünïcode@例え.jp']) {
			expect(value(metadataView({ contact: text }, EVERY_KIND).fields, 'contact'), text).toEqual({
				kind: 'email',
				text,
				href: `mailto:${text}`
			});
		}
		for (const text of ['not an address', 'a@b?cc=c@d', 'a@b@c']) {
			expect(value(metadataView({ contact: text }, EVERY_KIND).fields, 'contact'), text).toEqual({
				kind: 'text',
				text
			});
		}
	});

	it('links one address only: never a second recipient or a header spelled in its address', () => {
		for (const text of [
			'a@b.org,victim',
			'a@b.org;boss',
			'team@example.org%2Cattacker%40evil.example',
			'x@y.org%0D%0ABcc:evil',
			'x@y.org\r\nBcc: evil',
			'nul\u0000@example.org',
			'next\u0085line@example.org',
			'javascript:alert(1)@x.org',
			'"quoted"@example.org',
			'a@[127.0.0.1]'
		]) {
			expect(value(metadataView({ contact: text }, EVERY_KIND).fields, 'contact'), text).toEqual({
				kind: 'text',
				text
			});
		}
	});

	it('links http and https addresses only', () => {
		const fields = metadataView(
			{ landing_page: 'https://data.example.org/ace mag' },
			EVERY_KIND
		).fields;
		expect(value(fields, 'landing_page')).toEqual({
			kind: 'link',
			text: 'https://data.example.org/ace mag',
			href: 'https://data.example.org/ace%20mag'
		});
		expect(
			value(metadataView({ landing_page: 'http://example.org' }, EVERY_KIND).fields, 'landing_page')
		).toMatchObject({ kind: 'link', href: 'http://example.org/' });
	});

	it('shows addresses of any other scheme as text, never as a link', () => {
		for (const text of [
			'javascript:alert(1)',
			'JavaScript:alert(1)',
			' javascript:alert(1)',
			'java\tscript:alert(1)',
			'data:text/html,<script>alert(1)</script>',
			'vbscript:msgbox(1)',
			'ftp://ftp.example.org/pub/',
			'file:///etc/passwd',
			'mailto:someone@example.org',
			'//evil.example/path',
			'/relative/path'
		]) {
			expect(
				value(metadataView({ landing_page: text }, EVERY_KIND).fields, 'landing_page'),
				text
			).toEqual({ kind: 'text', text });
		}
	});

	it('shows strings without a format as text, links and times included', () => {
		const view = metadataView(
			{ homepage: 'https://example.org', when: '2024-01-01T00:00:00Z' },
			huronBase()
		);
		expect(value(view.other, 'homepage')).toEqual({ kind: 'text', text: 'https://example.org' });
		expect(value(view.other, 'when')).toEqual({ kind: 'text', text: '2024-01-01T00:00:00Z' });
	});

	it('shows numbers in the fixed format and booleans as Yes or No', () => {
		const fields = metadataView(
			{ cadence: 92, fill: -0.000125, big: 12345678, calibrated: true, flagged: false },
			EVERY_KIND
		);
		expect(value(fields.fields, 'cadence')).toEqual({ kind: 'number', text: '92' });
		expect(value(fields.fields, 'fill')).toEqual({ kind: 'number', text: '-0.000125' });
		expect(value(fields.other, 'big')).toEqual({ kind: 'number', text: '12345678' });
		expect(value(fields.fields, 'calibrated')).toEqual({ kind: 'boolean', text: 'Yes' });
		expect(value(fields.other, 'flagged')).toEqual({ kind: 'boolean', text: 'No' });
	});

	it('shows tiny and huge numbers with an exponent, in fields, chips and lists alike', () => {
		const view = metadataView(
			{
				planck_constant: 6.62607015e-34,
				elementary_charge: 1.602176634e-19,
				tiny_negative: -1e-25,
				fill: -1e31,
				largest: 1.7976931348623157e308,
				samples: [1e-22, 2e-22],
				runs: [{ floor: -2.2250738585072014e-308 }]
			},
			EVERY_KIND
		);
		const number = (text: string) => ({ kind: 'number', text });
		expect(value(view.other, 'planck_constant')).toEqual(number('6.62607015e-34'));
		expect(value(view.other, 'elementary_charge')).toEqual(number('1.602176634e-19'));
		expect(value(view.other, 'tiny_negative')).toEqual(number('-1e-25'));
		expect(value(view.fields, 'fill')).toEqual(number('-1e+31'));
		expect(value(view.other, 'largest')).toEqual(number('1.7976931348623157e+308'));
		expect(value(view.other, 'samples')).toEqual({
			kind: 'chips',
			items: ['1e-22', '2e-22'],
			more: 0
		});
		expect(value(view.other, 'runs')).toEqual({
			kind: 'list',
			items: [
				{
					kind: 'object',
					fields: [{ key: 'floor', label: 'Floor', value: number('-2.2250738585072014e-308') }],
					more: 0
				}
			],
			more: 0
		});
	});

	it('shows arrays of scalars as chips, keywords as plain chips', () => {
		const base = huronBase();
		const properties = isJsonObject(base.properties) ? base.properties : {};
		const view = metadataView(
			{ ...MAG, bands: [1.5, 2], mixed: ['a', 1, true, null, 'a'] },
			{
				...base,
				properties: { ...properties, bands: { type: 'array', items: { type: 'number' } } }
			}
		);
		expect(value(view.fields, 'keywords')).toEqual({
			kind: 'chips',
			items: ['magnetic field', 'solar wind', 'L1'],
			more: 0
		});
		expect(value(view.fields, 'bands')).toEqual({ kind: 'chips', items: ['1.5', '2'], more: 0 });
		expect(value(view.other, 'mixed')).toEqual({
			kind: 'chips',
			items: ['a', '1', 'Yes', 'None', 'a'],
			more: 0
		});
	});

	it('shows chips of dates and times in the fixed format', () => {
		const schema: JsonObject = {
			type: 'object',
			properties: { days: { type: 'array', items: { type: 'string', format: 'date-time' } } }
		};
		const days = ['2024-05-01T12:00:00Z', 'soon', '9999-12-31T23:59:59-23:59'];
		expect(value(metadataView({ days }, schema).fields, 'days')).toEqual({
			kind: 'chips',
			items: ['2024-05-01 12:00 UTC', 'soon', '9999-12-31T23:59:59-23:59'],
			more: 0
		});
	});

	it('shows arrays of objects as a list of their fields, with the titles of the items', () => {
		const contacts = value(metadataView(MAG, huronBase()).fields, 'contacts');
		expect(contacts).toEqual({
			kind: 'list',
			items: [
				{
					kind: 'object',
					fields: [
						{ key: 'name', label: 'Name', value: { kind: 'text', text: 'ACE MAG team' } },
						{
							key: 'email',
							label: 'Email',
							value: {
								kind: 'email',
								text: 'ace-mag@example.org',
								href: 'mailto:ace-mag@example.org'
							}
						}
					],
					more: 0
				},
				{
					kind: 'object',
					fields: [
						{ key: 'name', label: 'Name', value: { kind: 'text', text: 'Science data center' } }
					],
					more: 0
				}
			],
			more: 0
		});
	});

	it('shows objects as their fields, the required ones first', () => {
		const processing = value(
			metadataView({ processing: { level: 'L2', version: '3.1', extra: [] } }, EVERY_KIND).fields,
			'processing'
		);
		expect(processing).toEqual({
			kind: 'object',
			fields: [
				{ key: 'version', label: 'Version', value: { kind: 'text', text: '3.1' } },
				{ key: 'extra', label: 'Extra', value: { kind: 'none' } },
				{ key: 'level', label: 'Level', value: { kind: 'text', text: 'L2' } }
			],
			more: 0
		});
	});

	it('shows null and empty arrays and objects as none', () => {
		const view = metadataView({ a: null, b: [], c: {} }, null);
		expect(view.fields.map((field) => field.value)).toEqual([
			{ kind: 'none' },
			{ kind: 'none' },
			{ kind: 'none' }
		]);
	});

	it('shows what is nested deeper than a few levels as its JSON text', () => {
		const deep = { a: { b: { c: { d: { e: 'deep' } } } } };
		const shown = value(metadataView({ deep }, null).fields, 'deep');
		expect(JSON.stringify(shown)).toContain(JSON.stringify(JSON.stringify({ e: 'deep' })));
		expect(JSON.stringify(shown)).not.toContain('"key":"e"');
	});

	it('shows labels as key: value chips with the filter the catalog search finds them by', () => {
		expect(value(metadataView(MAG, huronBase()).fields, 'labels')).toEqual({
			kind: 'labels',
			items: [
				{ key: 'instrument', value: 'mag', filter: 'instrument=mag' },
				{ key: 'level', value: 'l2', filter: 'level=l2' },
				{ key: 'mission', value: 'ace', filter: 'mission=ace' }
			],
			more: 0
		});
	});

	it('gives no filter to labels the search cannot find', () => {
		const labels = value(
			metadataView(
				{ labels: { 'a=b': 'c', '': 'empty', count: 3, nested: { x: 1 }, 'x:y': 'z=w' } },
				huronBase()
			).fields,
			'labels'
		);
		expect(labels).toEqual({
			kind: 'labels',
			items: [
				{ key: '', value: 'empty', filter: null },
				{ key: 'a=b', value: 'c', filter: null },
				{ key: 'count', value: '3', filter: null },
				{ key: 'nested', value: '{"x":1}', filter: null },
				{ key: 'x:y', value: 'z=w', filter: 'x:y=z=w' }
			],
			more: 0
		});
	});

	it('shows labels that are not an object like any other value', () => {
		expect(value(metadataView({ labels: ['ace'] }, huronBase()).fields, 'labels')).toEqual({
			kind: 'chips',
			items: ['ace'],
			more: 0
		});
		expect(value(metadataView({ labels: {} }, huronBase()).fields, 'labels')).toEqual({
			kind: 'none'
		});
	});

	it('labels fields by the titles of their schema, else by their readable key', () => {
		const schema: JsonObject = {
			type: 'object',
			properties: { pi_name: { type: 'string', title: '  ' }, cadence_s: { type: 'integer' } }
		};
		expect(
			metadataView({ pi_name: 'Dr. Who', cadence_s: 4 }, schema).fields.map(({ label }) => label)
		).toEqual(['Cadence s', 'Pi name']);
	});

	it('can be page data whatever keys the metadata and the schema hold', () => {
		const metadata = parsedObject(
			'{"title":"Proto","__proto__":{"polluted":true},"labels":{"__proto__":"x","mission":"proto"},' +
				'"contacts":[{"__proto__":"y","name":"n"}]}'
		);
		const schema = parsedObject(
			'{"type":"object","required":["__proto__"],"properties":{"__proto__":{"type":"object","title":"Proto"}}}'
		);
		const view = metadataView(metadata, schema);
		expect(() => serializePageData(view)).not.toThrow();
		expect(value(view.fields, '__proto__')).toEqual({
			kind: 'object',
			fields: [{ key: 'polluted', label: 'Polluted', value: { kind: 'boolean', text: 'Yes' } }],
			more: 0
		});
		expect(value(view.other, 'labels')).toMatchObject({
			kind: 'labels',
			items: [
				{ key: '__proto__', value: 'x', filter: '__proto__=x' },
				{ key: 'mission', value: 'proto', filter: 'mission=proto' }
			]
		});
		expect({}).not.toHaveProperty('polluted');
	});

	it('shows the first items of a long array and counts the rest', () => {
		const samples = Array.from({ length: 400_000 }, () => 0);
		const view = metadataView({ samples }, null);
		expect(value(view.fields, 'samples')).toEqual({
			kind: 'chips',
			items: Array.from({ length: MAX_ITEMS }, () => '0'),
			more: 400_000 - MAX_ITEMS
		});
		expect(view).toMatchObject({ more: 0, shortened: true });
	});

	it('shows the first items of long lists, objects and labels and counts the rest', () => {
		const keys = Array.from({ length: MAX_ITEMS + 5 }, (_, index) => `k${index}`);
		const view = metadataView(
			{
				contacts: keys.map((name) => ({ name })),
				wide: Object.fromEntries(keys.map((key) => [key, 1])),
				labels: Object.fromEntries(keys.map((key) => [key, 'v']))
			},
			null
		);
		const contacts = value(view.fields, 'contacts');
		expect(contacts?.kind === 'list' && [contacts.items.length, contacts.more]).toEqual([
			MAX_ITEMS,
			5
		]);
		const wide = value(view.fields, 'wide');
		expect(wide?.kind === 'object' && [wide.fields.length, wide.more]).toEqual([MAX_ITEMS, 5]);
		const labels = value(view.fields, 'labels');
		expect(labels?.kind === 'labels' && [labels.items.length, labels.more]).toEqual([MAX_ITEMS, 5]);
		expect(view.shortened).toBe(true);
	});

	it('shows so many values in all, however the metadata nests them, and counts the fields left out', () => {
		// Each top-level field holds 50 objects of 50 lists; without a bound in all, 125,000 chips.
		const zeros = Array.from({ length: 50 }, () => 0);
		const block = Array.from({ length: 50 }, () =>
			Object.fromEntries(Array.from({ length: 50 }, (_, index) => [`list_${index}`, zeros]))
		);
		const view = metadataView({ a: block, b: block, c: 'last' }, null);
		expect(countValues([...view.fields, ...view.other])).toBeLessThanOrEqual(MAX_VALUES);
		expect(view.fields.map(({ key }) => key)).toEqual(['a']);
		expect(view).toMatchObject({ more: 2, shortened: true });
		expect(() => serializePageData(view)).not.toThrow();
	});

	it('marks nothing as left out when everything shows', () => {
		const zeros = Array.from({ length: MAX_ITEMS }, () => 0);
		const view = metadataView({ ...MAG, zeros }, huronBase());
		expect(value(view.other, 'zeros')).toMatchObject({ kind: 'chips', more: 0 });
		expect(view).toMatchObject({ more: 0, shortened: false });
	});

	it('shows the first part of a single long text, and says the view is shortened', () => {
		// Valid metadata: huron-base sets no length on most fields, and markup escapes each "<".
		const view = metadataView({ ...MAG, notes: '<'.repeat(1_000_000) }, huronBase());
		expect(value(view.other, 'notes')).toEqual({
			kind: 'text',
			text: `${'<'.repeat(VALUE_LENGTH)}…`
		});
		expect(view.shortened).toBe(true);
		const fits = metadataView({ ...MAG, notes: 'n'.repeat(VALUE_LENGTH) }, huronBase());
		expect(value(fits.other, 'notes')).toEqual({ kind: 'text', text: 'n'.repeat(VALUE_LENGTH) });
		expect(fits.shortened).toBe(false);
	});

	it('links no address too long to show in full: its link would lead elsewhere', () => {
		const schema = {
			type: 'object',
			properties: {
				page: { type: 'string', format: 'uri' },
				mail: { type: 'string', format: 'email' }
			}
		};
		const page = `https://example.org/${'p'.repeat(VALUE_LENGTH)}`;
		const mail = `${'m'.repeat(VALUE_LENGTH)}@example.org`;
		const view = metadataView({ page, mail }, schema);
		expect(value(view.fields, 'page')).toEqual({
			kind: 'text',
			text: `${page.slice(0, VALUE_LENGTH)}…`
		});
		expect(value(view.fields, 'mail')).toMatchObject({ kind: 'text' });
	});

	it('shows no more text in all than its budget, however many values share a mebibyte', () => {
		// 400 values of 4,000 characters: each fits alone, 1.6 million together.
		const metadata = Object.fromEntries(
			Array.from({ length: 400 }, (_, index) => [
				`f${String(index).padStart(3, '0')}`,
				'<'.repeat(4_000)
			])
		);
		const view = metadataView(metadata, null);
		expect(shownText(view.fields)).toBeLessThanOrEqual(TEXT_BUDGET + view.fields.length);
		expect(view.more).toBeGreaterThan(0);
		expect(view).toMatchObject({ shortened: true });
	});

	it('shortens long keys, labels and label chips alike', () => {
		const key = `k${'_'.repeat(200_000)}`;
		const metadata = { [key]: 'x', labels: { [key]: 'v'.repeat(200_000) } };
		const view = metadataView(metadata, null);
		const [long, labels] = view.fields;
		expect([...long.key]).toHaveLength(VALUE_LENGTH + 1);
		expect([...long.label].length).toBeLessThanOrEqual(VALUE_LENGTH + 1);
		expect(labels.value).toMatchObject({ kind: 'labels' });
		const chip = labels.value.kind === 'labels' ? labels.value.items[0] : null;
		expect(chip && [[...chip.key].length, [...chip.value].length, chip.filter]).toEqual([
			VALUE_LENGTH + 1,
			VALUE_LENGTH + 1,
			null
		]);
		expect(view.shortened).toBe(true);
	});
});

/** How many code points of text a view's fields show: keys, labels and values. */
function shownText(fields: readonly MetadataField[]): number {
	return fields.reduce(
		(total, field) =>
			total + [...field.key].length + [...field.label].length + valueText(field.value),
		0
	);
}

function valueText(shown: MetadataValue): number {
	switch (shown.kind) {
		case 'chips':
			return shown.items.reduce((total, item) => total + [...item].length, 0);
		case 'labels':
			return shown.items.reduce(
				(total, { key, value }) => total + [...key].length + [...value].length,
				0
			);
		case 'list':
			return shown.items.reduce((total, item) => total + valueText(item), 0);
		case 'object':
			return shownText(shown.fields);
		case 'none':
		case 'missing':
			return 0;
		default:
			return [...shown.text].length;
	}
}

/** The values a view holds: its fields, chips, labels and items, however they nest. */
function countValues(fields: readonly MetadataField[]): number {
	return fields.reduce((total, field) => total + 1 + countValue(field.value), 0);
}

function countValue(shown: MetadataValue): number {
	switch (shown.kind) {
		case 'chips':
			return shown.items.length;
		case 'labels':
			return shown.items.length;
		case 'list':
			return shown.items.reduce((total, item) => total + 1 + countValue(item), 0);
		case 'object':
			return countValues(shown.fields);
		default:
			return 0;
	}
}

describe('problemRows', () => {
	it('names the field of each problem by the titles along its pointer', () => {
		const rows = problemRows(
			[
				{ path: '/contacts/0/email', message: "'x' is not a 'email'", rule: 'format' },
				{ path: '/', message: "'mission' is a required property", rule: 'required' }
			],
			huronBase(),
			{ contacts: [{ name: 'n', email: 'x' }] }
		);
		expect(rows).toEqual({
			rows: [
				{ field: 'Contacts › 1 › Email', message: "'x' is not a 'email'" },
				{ field: null, message: "'mission' is a required property" }
			],
			more: 0
		});
	});

	it('names the first problems and counts the rest', () => {
		const problems = Array.from({ length: MAX_ITEMS + 120 }, (_, index) => ({
			path: `/keywords/${index}`,
			message: `${index} is not of type 'string'`,
			rule: 'type'
		}));
		const rows = problemRows(problems, huronBase(), {
			keywords: problems.map((_, index) => index)
		});
		expect(rows.rows).toHaveLength(MAX_ITEMS);
		expect(rows.rows[0]).toEqual({ field: 'Keywords › 1', message: "0 is not of type 'string'" });
		expect(rows.more).toBe(120);
	});

	it('shortens a message that quotes a long value, and the field it names', () => {
		// jsonschema quotes the value: a draft's title of a mebibyte made a message as long.
		const title = 't'.repeat(1_000_000);
		const key = 'k'.repeat(10_000);
		const rows = problemRows(
			[
				{ path: '/title', message: `'${title}' is too long`, rule: 'maxLength' },
				{ path: `/${key}`, message: 'bad', rule: 'type' }
			],
			huronBase(),
			{ title, [key]: 1 }
		);
		expect(rows.rows[0]).toEqual({
			field: 'Title',
			message: `'${'t'.repeat(PROBLEM_LENGTH - 1)}…`
		});
		expect([...(rows.rows[1].field ?? '')]).toHaveLength(PROBLEM_LENGTH + 1);
	});

	it('can be page data whatever the problems name', () => {
		const rows = problemRows(
			[{ path: '/__proto__', message: 'bad', rule: 'type' }],
			null,
			parsedObject('{"__proto__":1}')
		);
		expect(() => serializePageData(rows)).not.toThrow();
		expect(rows).toEqual({ rows: [{ field: 'Proto', message: 'bad' }], more: 0 });
	});
});

describe('pointerLabel', () => {
	it('names the whole document by nothing', () => {
		expect(pointerLabel('/', huronBase(), {})).toBeNull();
		expect(pointerLabel('', huronBase(), {})).toBeNull();
	});

	it('counts items from 1 and reads labels through the schema of the items', () => {
		expect(pointerLabel('/contacts/1/name', huronBase(), { contacts: [{}, {}] })).toBe(
			'Contacts › 2 › Name'
		);
		expect(pointerLabel('/keywords/0', huronBase(), { keywords: [1] })).toBe('Keywords › 1');
	});

	it('makes keys the schema does not title readable, inside labels too', () => {
		expect(pointerLabel('/labels/data_level', huronBase(), { labels: { data_level: 1 } })).toBe(
			'Labels › Data level'
		);
		expect(pointerLabel('/end_time', null, {})).toBe('End time');
	});

	it('finds a key that holds a slash, which the pointer does not escape', () => {
		const metadata = { 'instrument/name': 'MAG', instrument: { name: 'other' } };
		expect(pointerLabel('/instrument/name', null, metadata)).toBe('Instrument/name');
		expect(pointerLabel('/instrument/name', null, { instrument: { name: 'x' } })).toBe(
			'Instrument › Name'
		);
	});

	it('treats a number as a key where the value is no array', () => {
		expect(pointerLabel('/2024/0', null, { 2024: { 0: 'x' } })).toBe('2024 › 0');
	});
});

describe('humanizeKey', () => {
	it.each([
		['start_time', 'Start time'],
		['mission', 'Mission'],
		['PI_name', 'PI name'],
		['x-ray_flux', 'X-ray flux'],
		['__double__under__', 'Double under'],
		['_', '_'],
		['', '""']
	])('makes %j readable as %j', (key, label) => {
		expect(humanizeKey(key)).toBe(label);
	});
});

describe('labelChips', () => {
	it('gives the chips the metadata view shows, by key, with the filters the search finds', () => {
		const metadata = {
			labels: { mission: 'ace', 'a=b': 'c', count: 17, ratio: 1.5e-7, flag: true, nested: { x: 1 } }
		};
		expect(labelChips(metadata)).toEqual({
			items: [
				{ key: 'a=b', value: 'c', filter: null },
				{ key: 'count', value: '17', filter: null },
				{ key: 'flag', value: 'Yes', filter: null },
				{ key: 'mission', value: 'ace', filter: 'mission=ace' },
				{ key: 'nested', value: '{"x":1}', filter: null },
				{ key: 'ratio', value: '1.5e-7', filter: null }
			],
			more: 0
		});
		const view = metadataView(metadata, null);
		expect(value(view.fields, 'labels')).toEqual({ kind: 'labels', ...labelChips(metadata) });
	});

	it('shows the first labels and counts the rest', () => {
		const keys = Array.from(
			{ length: MAX_ITEMS + 7 },
			(_, index) => `k${String(index).padStart(3, '0')}`
		);
		const chips = labelChips({ labels: Object.fromEntries(keys.map((key) => [key, 'v'])) });
		expect(chips.items.map(({ key }) => key)).toEqual(keys.slice(0, MAX_ITEMS));
		expect(chips.more).toBe(7);
	});

	it('gives none for metadata without labels, or with labels that are not an object', () => {
		for (const metadata of [{}, { labels: ['ace'] }, { labels: 'ace' }, { labels: null }]) {
			expect(labelChips(metadata)).toEqual({ items: [], more: 0 });
		}
	});

	it('searches for no label whose key or value is longer than a chip links to', () => {
		const fits = '😀'.repeat(MAX_LABEL_LENGTH);
		const long = `${'n'.repeat(MAX_LABEL_LENGTH)}😀`;
		const metadata = { labels: { a: fits, [fits]: 'b', c: long, [long]: 'd' } };
		expect(labelChips(metadata).items).toEqual([
			{ key: 'a', value: fits, filter: `a=${fits}` },
			{ key: 'c', value: long, filter: null },
			{ key: long, value: 'd', filter: null },
			{ key: fits, value: 'b', filter: `${fits}=b` }
		]);
		// The collection's own page shows such a label as plain text, in full up to VALUE_LENGTH.
		expect(value(metadataView(metadata, null).fields, 'labels')).toEqual({
			kind: 'labels',
			...labelChips(metadata)
		});
	});

	it('reads only the labels themselves, whatever keys they hold', () => {
		const chips = labelChips(parsedObject('{"labels":{"__proto__":"x","constructor":"y"}}'));
		expect(chips.items).toEqual([
			{ key: '__proto__', value: 'x', filter: '__proto__=x' },
			{ key: 'constructor', value: 'y', filter: 'constructor=y' }
		]);
		expect(labelChips(parsedObject('{"__proto__":{"labels":{"a":"b"}}}')).items).toEqual([]);
		expect(() => serializePageData(chips)).not.toThrow();
	});
});
