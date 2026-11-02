// @vitest-environment node
import { describe, expect, it } from 'vitest';
import type { JsonValue } from '$api/types';
import { serializePageData } from '$lib/testing/page-data';
import { huronBase, spaceWeather } from '$lib/testing/schemas';
import { isJsonObject, parseExactly } from './json';
import {
	MAX_ENUM_VALUES,
	MAX_SCHEMA_FIELDS,
	SCHEMA_JSON_LENGTH,
	SCHEMA_TEXT_LENGTH,
	itemsSchema,
	propertySchema,
	requiredKeys,
	schemaView,
	walkthroughOrder
} from './schema-view';

describe('schemaView', () => {
	it('lists every field of huron-base with what it accepts', () => {
		const view = schemaView(huronBase());
		expect(view.title).toBe('Huron base metadata');
		expect(view.description).toBe('Fields every collection carries.');
		expect(view.otherFields).toBe(true);
		expect(view.fields.map(({ label, type, required }) => [label, type, required])).toEqual([
			['Title', 'string', true],
			['Description', 'string', true],
			['Campaign', 'string', false],
			['Contacts', 'array of objects', false],
			['Contacts › name', 'string', true],
			['Contacts › email', 'string', false],
			['End time', 'string', false],
			['Instrument', 'string', false],
			['Keywords', 'array of strings', false],
			['Labels', 'object', false],
			['Start time', 'string', false]
		]);
	});

	it('states the constraints of each field', () => {
		const fields = new Map(
			schemaView(huronBase()).fields.map((field) => [field.key, field.constraints])
		);
		expect(fields.get('title')).toEqual(['1 to 200 characters']);
		expect(fields.get('description')).toEqual(['at least 1 character']);
		expect(fields.get('keywords')).toEqual(['unique items', 'each item: at least 1 character']);
		expect(fields.get('contacts')).toEqual(['each item: no other keys']);
		expect(fields.get('contacts/name')).toEqual(['at least 1 character']);
		expect(fields.get('contacts/email')).toEqual(['format email']);
		expect(fields.get('start_time')).toEqual(['format date-time']);
		expect(fields.get('labels')).toEqual(['each value: string']);
		expect(fields.get('instrument')).toEqual([]);
	});

	it('keeps descriptions and nests rows under their parent', () => {
		const labels = schemaView(huronBase()).fields.find(({ key }) => key === 'labels');
		expect(labels?.description).toBe('Free-form string labels used for search.');
		const name = schemaView(huronBase()).fields.find(({ key }) => key === 'contacts/name');
		expect(name?.depth).toBe(1);
	});

	it('puts the fields an organization schema requires among the required ones', () => {
		const view = schemaView(spaceWeather());
		expect(view.title).toBe('Space weather metadata');
		expect(view.fields.slice(0, 3).map(({ label, required }) => [label, required])).toEqual([
			['Title', true],
			['Description', true],
			['Mission', true]
		]);
	});

	it('describes every keyword a schema document may use', () => {
		const view = schemaView({
			type: 'object',
			additionalProperties: false,
			properties: {
				level: { type: 'string', enum: ['l1', 'l2'] },
				kind: { type: 'string', const: 'raw' },
				count: { type: 'integer', minimum: 0, maximum: 10, default: 1 },
				ratio: { type: 'number', minimum: 0.5 },
				score: { type: 'number', maximum: 100 },
				code: { type: 'string', minLength: 3, maxLength: 3, pattern: '^[A-Z]+$' },
				short: { type: 'string', maxLength: 1 },
				site: { type: 'string', format: 'uri' },
				tags: { type: 'array', items: { type: 'string', maxLength: 8 }, minItems: 1, maxItems: 5 },
				pair: { type: 'array', minItems: 2, maxItems: 2 },
				nested: {
					type: 'object',
					title: 'Nested',
					required: ['inner'],
					properties: { inner: { type: 'boolean', title: 'Inner' } }
				},
				either: { type: ['string', 'null'] },
				anything: {}
			}
		});
		expect(view.otherFields).toBe(false);
		const fields = new Map(view.fields.map((field) => [field.key, field]));
		expect(fields.get('level')?.constraints).toEqual(['one of "l1", "l2"']);
		expect(fields.get('kind')?.constraints).toEqual(['exactly "raw"']);
		expect(fields.get('count')?.constraints).toEqual(['from 0 to 10', 'default 1']);
		expect(fields.get('ratio')?.constraints).toEqual(['at least 0.5']);
		expect(fields.get('score')?.constraints).toEqual(['at most 100']);
		expect(fields.get('code')?.constraints).toEqual(['exactly 3 characters', 'pattern ^[A-Z]+$']);
		expect(fields.get('short')?.constraints).toEqual(['at most 1 character']);
		expect(fields.get('site')?.constraints).toEqual(['format uri']);
		expect(fields.get('tags')?.constraints).toEqual([
			'1 to 5 items',
			'each item: at most 8 characters'
		]);
		expect(fields.get('tags')?.type).toBe('array of strings');
		expect(fields.get('pair')?.constraints).toEqual(['exactly 2 items']);
		expect(fields.get('pair')?.type).toBe('array');
		expect(fields.get('nested/inner')).toMatchObject({
			label: 'Nested › Inner',
			type: 'boolean',
			required: true
		});
		expect(fields.get('either')?.type).toBe('string or null');
		expect(fields.get('anything')?.type).toBe('any');
	});

	it('writes bounds exactly, with an exponent where they are tiny or huge', () => {
		const view = schemaView({
			type: 'object',
			properties: {
				flux: { type: 'number', minimum: 1e-30, maximum: 1e300 },
				mass: { type: 'number', minimum: 6.62607015e-34 },
				fill: { type: 'number', maximum: -1e31 },
				charge: { type: 'number', minimum: 1.602176634e-19 },
				samples: { type: 'array', minItems: 1000, maxItems: 2000 }
			}
		});
		const fields = new Map(view.fields.map((field) => [field.key, field.constraints]));
		expect(fields.get('flux')).toEqual(['from 1e-30 to 1e+300']);
		expect(fields.get('mass')).toEqual(['at least 6.62607015e-34']);
		expect(fields.get('fill')).toEqual(['at most -1e+31']);
		expect(fields.get('charge')).toEqual(['at least 1.602176634e-19']);
		expect(fields.get('samples')).toEqual(['1,000 to 2,000 items']);
	});

	it('writes integers too large for a number with the digits the API wrote', () => {
		// Parsed as every API answer is. CDF TT2000 epochs, for one, are int64 nanoseconds; the two
		// counts of "pair" round to the same number, 2^53.
		const document = parseExactly(`{
			"type": "object",
			"properties": {
				"epoch": { "type": "integer", "minimum": -9223372036854775807, "maximum": 9223372036854775807 },
				"flag": { "type": "integer", "enum": [9007199254740993, 1], "default": 9007199254740993 },
				"record": { "type": "object", "const": { "id": 9223372036854775807 } },
				"text": { "type": "string", "maxLength": 9223372036854775807 },
				"samples": {
					"type": "array",
					"items": { "type": "integer", "minimum": 9007199254740993 },
					"minItems": 9007199254740993,
					"maxItems": 9007199254740993
				},
				"pair": { "type": "array", "minItems": 9007199254740992, "maxItems": 9007199254740993 }
			}
		}`);
		if (!isJsonObject(document)) throw new Error('not an object');
		const view = schemaView(document);
		const fields = new Map(view.fields.map((field) => [field.key, field.constraints]));
		expect(fields.get('epoch')).toEqual(['from -9223372036854775807 to 9223372036854775807']);
		expect(fields.get('flag')).toEqual(['one of 9007199254740993, 1', 'default 9007199254740993']);
		expect(fields.get('record')).toEqual(['exactly {"id":9223372036854775807}']);
		expect(fields.get('text')).toEqual(['at most 9,223,372,036,854,775,807 characters']);
		expect(fields.get('samples')).toEqual([
			'exactly 9,007,199,254,740,993 items',
			'each item: at least 9007199254740993'
		]);
		expect(fields.get('pair')).toEqual(['9,007,199,254,740,992 to 9,007,199,254,740,993 items']);
		expect(view.json).toContain('"minimum": -9223372036854775807,');
		expect(view.json).toContain('"maximum": 9223372036854775807');
		expect(view.json).not.toContain('9223372036854776000');
		expect(JSON.parse(view.json)).toEqual(document);
	});

	it('keys every row apart, also when property names hold "/" or "~"', () => {
		const view = schemaView({
			type: 'object',
			properties: {
				instrument: { type: 'object', properties: { name: { type: 'string' } } },
				'instrument/name': { type: 'string' },
				'a~1b': { type: 'string' },
				'a/b': { type: 'string' }
			}
		});
		expect(view.fields.map(({ key, label }) => [key, label])).toEqual([
			['a~1b', 'a/b'],
			['a~01b', 'a~1b'],
			['instrument', 'instrument'],
			['instrument/name', 'instrument › name'],
			['instrument~1name', 'instrument/name']
		]);
	});

	it('has no rows for a schema without properties', () => {
		expect(schemaView({ type: 'object' })).toEqual({
			title: null,
			description: null,
			otherFields: null,
			fields: [],
			moreFields: 0,
			json: '{\n  "type": "object"\n}',
			jsonShortened: false,
			shortened: false
		});
	});

	it('shows the first rows of a schema of thousands of properties, and counts the rest', () => {
		// An override of 20,000 properties, as a contributor may set one: the API bounds none.
		const properties = Object.fromEntries(
			Array.from({ length: 20_000 }, (_, index) => [
				`p${String(index).padStart(5, '0')}`,
				{ type: 'string', description: 'A field of the override.' }
			])
		);
		const view = schemaView({ type: 'object', properties });
		expect(view.fields).toHaveLength(MAX_SCHEMA_FIELDS);
		expect(view.fields[0].key).toBe('p00000');
		expect(view.moreFields).toBe(20_000 - MAX_SCHEMA_FIELDS);
		expect([...view.json]).toHaveLength(SCHEMA_JSON_LENGTH + 1);
		expect(view).toMatchObject({ jsonShortened: true, shortened: true });
		expect(JSON.stringify(view).length).toBeLessThan(400_000);
	});

	it('counts the nested rows it leaves out as well', () => {
		const nested = {
			type: 'object',
			properties: Object.fromEntries(
				Array.from({ length: MAX_SCHEMA_FIELDS }, (_, index) => [`n${index}`, { type: 'string' }])
			)
		};
		const view = schemaView({
			type: 'object',
			properties: { a: nested, b: nested }
		});
		expect(view.fields).toHaveLength(MAX_SCHEMA_FIELDS);
		expect(view.moreFields).toBe(2 * MAX_SCHEMA_FIELDS + 2 - MAX_SCHEMA_FIELDS);
	});

	it('shortens each long text of a row, and names the first values of a long enum', () => {
		const long = 'x'.repeat(50_000);
		const view = schemaView({
			type: 'object',
			title: long,
			properties: {
				[long]: { type: 'string', description: long, pattern: long },
				kind: { type: 'string', enum: Array.from({ length: 500 }, (_, index) => `v${index}`) }
			}
		});
		const [kind, wide] = view.fields;
		expect(view.title).toBe(`${'x'.repeat(SCHEMA_TEXT_LENGTH)}…`);
		expect([...wide.key]).toHaveLength(SCHEMA_TEXT_LENGTH + 1);
		expect([...wide.label]).toHaveLength(SCHEMA_TEXT_LENGTH + 1);
		expect([...wide.description]).toHaveLength(SCHEMA_TEXT_LENGTH + 1);
		expect(wide.constraints.every((rule) => [...rule].length <= SCHEMA_TEXT_LENGTH + 1)).toBe(true);
		expect(kind.constraints[0]).toMatch(
			new RegExp(`^one of "v0", .*"v${MAX_ENUM_VALUES - 1}", and 450 more$`)
		);
		expect(view.shortened).toBe(true);
		expect(view.jsonShortened).toBe(false);
	});

	it('keeps the document as indented JSON text', () => {
		const document = spaceWeather();
		expect(JSON.parse(schemaView(document).json)).toEqual(document);
		expect(schemaView(document).json).toBe(JSON.stringify(document, null, 2));
	});

	it('can be page data whatever the properties are named', () => {
		// As `JSON.parse` reads an API answer: `__proto__` stays a property of its own.
		const document: JsonValue = JSON.parse(
			'{"type":"object","properties":{"__proto__":{"type":"object","properties":{"__proto__":{"type":"string","enum":[{"__proto__":1}]}}}}}'
		);
		if (!isJsonObject(document)) throw new Error('not an object');
		expect(() => serializePageData(document)).toThrow('__proto__');
		const view = schemaView(document);
		expect(() => serializePageData(view)).not.toThrow();
		expect(view.fields.map(({ key, label, constraints }) => [key, label, constraints])).toEqual([
			['__proto__', '__proto__', []],
			['__proto__/__proto__', '__proto__ › __proto__', ['one of {"__proto__":1}']]
		]);
		expect(view.json).toContain('"__proto__"');
	});
});

describe('walkthroughOrder', () => {
	it('puts the required keys first, in their order, then the others by key', () => {
		const schema = { type: 'object', required: ['title', 'description', 'title'] };
		expect(walkthroughOrder(schema, ['zeta', 'description', 'Alpha', 'title', 'beta'])).toEqual([
			'title',
			'description',
			'Alpha',
			'beta',
			'zeta'
		]);
	});

	it('leaves out required keys it was not given, and orders by key without a schema', () => {
		expect(walkthroughOrder({ required: ['mission'] }, ['b', 'a'])).toEqual(['a', 'b']);
		expect(walkthroughOrder(null, ['b', 'a', 'b'])).toEqual(['a', 'b']);
	});
});

describe('the parts of an object schema', () => {
	it('names its required keys once each, ignoring what is not a key', () => {
		expect(requiredKeys({ required: ['a', 1, 'b', 'a'] })).toEqual(['a', 'b']);
		expect(requiredKeys({ required: 'a' })).toEqual([]);
		expect(requiredKeys(null)).toEqual([]);
	});

	it('finds the schema of an own property and of the items', () => {
		const schema = huronBase();
		expect(propertySchema(schema, 'title')).toMatchObject({ title: 'Title' });
		expect(propertySchema(schema, 'nope')).toBeNull();
		expect(propertySchema(schema, 'constructor')).toBeNull();
		expect(propertySchema({ properties: { a: 'not a schema' } }, 'a')).toBeNull();
		expect(propertySchema(null, 'title')).toBeNull();
		expect(itemsSchema(propertySchema(schema, 'contacts'))).toMatchObject({ required: ['name'] });
		expect(itemsSchema(propertySchema(schema, 'title'))).toBeNull();
		expect(itemsSchema(null)).toBeNull();
	});
});
