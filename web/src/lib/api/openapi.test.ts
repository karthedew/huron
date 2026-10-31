// @vitest-environment node
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import {
	GENERATED_MODULE,
	OPENAPI_DOCUMENT,
	generate
} from '../../../scripts/generate-api-types.mjs';

function document(schemas: Record<string, unknown>): unknown {
	return { openapi: '3.1.0', components: { schemas } };
}

/** The generated module without its two header lines. */
function body(schemas: Record<string, unknown>): string {
	return generate(document(schemas)).split('\n').slice(3).join('\n');
}

describe('the generated API types', () => {
	it('match docs/openapi.json (run `npm run generate:api` after the contract changes)', () => {
		const contract = JSON.parse(readFileSync(OPENAPI_DOCUMENT, 'utf8'));
		expect(readFileSync(GENERATED_MODULE, 'utf8')).toBe(generate(contract));
	});
});

describe('generate', () => {
	it('writes the do-not-edit header', () => {
		expect(generate(document({}))).toMatch(
			/^\/\/ Generated from docs\/openapi\.json .* do not edit\./
		);
	});

	it('writes interfaces with required and optional properties, formats and descriptions', () => {
		expect(
			body({
				Thing: {
					type: 'object',
					description: 'A thing.',
					required: ['id', 'when'],
					properties: {
						id: { type: 'string', format: 'uuid' },
						count: { type: 'integer', description: 'How many.' },
						ratio: { type: 'number' },
						on: { type: 'boolean' },
						when: { anyOf: [{ type: 'string', format: 'date-time' }, { type: 'null' }] },
						'odd-key': { type: 'string' }
					}
				}
			})
		).toBe(
			[
				'/** A thing. */',
				'export interface Thing {',
				'\t/** Format: uuid. */',
				'\tid: string;',
				'\t/** How many. */',
				'\tcount?: number;',
				'\tratio?: number;',
				'\ton?: boolean;',
				'\t/** Format: date-time. */',
				'\twhen: string | null;',
				"\t'odd-key'?: string;",
				'}',
				''
			].join('\n')
		);
	});

	it('resolves references, arrays and open objects', () => {
		expect(
			body({
				A: {
					type: 'object',
					required: ['b', 'list', 'map', 'free', 'any', 'mixed', 'typed'],
					properties: {
						b: { $ref: '#/components/schemas/B' },
						list: { type: 'array', items: { $ref: '#/components/schemas/B' } },
						map: { type: 'object', additionalProperties: true },
						free: { type: 'object' },
						any: { title: 'Anything' },
						mixed: { type: 'array', items: { anyOf: [{ type: 'string' }, { type: 'integer' }] } },
						typed: { type: 'object', additionalProperties: { type: 'integer' } }
					}
				},
				B: { type: 'object', properties: {} }
			})
		).toBe(
			[
				'export interface A {',
				'\tb: B;',
				'\tlist: B[];',
				'\tmap: Record<string, unknown>;',
				'\tfree: Record<string, unknown>;',
				'\tany: unknown;',
				'\tmixed: (string | number)[];',
				'\ttyped: Record<string, number>;',
				'}',
				'',
				'export interface B {}',
				''
			].join('\n')
		);
	});

	it('writes string enums as unions of literals', () => {
		expect(body({ State: { type: 'string', enum: ['draft', 'active', "it's"] } })).toBe(
			"export type State = 'draft' | 'active' | 'it\\'s';\n"
		);
	});

	it('collapses Page_X_ schemas into one generic Page<T>', () => {
		const page = (item: string) => ({
			type: 'object',
			required: ['items'],
			properties: {
				items: { type: 'array', items: { $ref: `#/components/schemas/${item}` } },
				next_cursor: { anyOf: [{ type: 'string' }, { type: 'null' }] }
			}
		});
		const output = body({
			Item: { type: 'object', properties: {} },
			Page_Item_: page('Item'),
			Page_Other_: page('Other'),
			Other: { type: 'object', properties: {} },
			Uses: {
				type: 'object',
				required: ['page'],
				properties: { page: { $ref: '#/components/schemas/Page_Item_' } }
			}
		});
		expect(output.match(/export interface Page<T>/g)).toHaveLength(1);
		expect(output).not.toContain('Page_');
		expect(output).toContain('\tpage: Page<Item>;');
		expect(output).toContain('\titems: T[];\n\tnext_cursor?: string | null;');
	});

	it('ignores annotations and constraints, also next to a $ref', () => {
		expect(
			body({
				A: {
					type: 'object',
					title: 'A',
					required: ['b', 'name', 'tags'],
					properties: {
						b: { $ref: '#/components/schemas/B', description: 'The B.', default: {} },
						name: { type: 'string', title: 'Name', minLength: 1, maxLength: 63, pattern: '^a' },
						tags: { type: 'array', items: { type: 'string' }, maxItems: 5, uniqueItems: true }
					}
				},
				B: { type: 'object', properties: {} }
			})
		).toBe(
			[
				'export interface A {',
				'\t/** The B. */',
				'\tb: B;',
				'\tname: string;',
				'\ttags: string[];',
				'}',
				'',
				'export interface B {}',
				''
			].join('\n')
		);
	});

	it('is deterministic and sorts schemas by name', () => {
		const schemas = { Zed: { type: 'string' }, Alpha: { type: 'integer' } };
		expect(body(schemas)).toBe('export type Alpha = number;\n\nexport type Zed = string;\n');
		expect(generate(document(schemas))).toBe(
			generate(document({ Alpha: schemas.Alpha, Zed: schemas.Zed }))
		);
	});

	it.each([
		['no components', {}],
		['a schema that is not an object', document({ A: 'string' })],
		['an unsupported type', document({ A: { type: 'file' } })],
		['a foreign reference', document({ A: { $ref: 'https://example.org/schema' } })],
		['a non-literal enum', document({ A: { enum: [{}] } })],
		[
			'a malformed page',
			document({ Page_A_: { type: 'object', properties: { items: { type: 'array' } } } })
		],
		[
			'a malformed required list',
			document({ A: { type: 'object', required: [1], properties: {} } })
		]
	])('refuses %s', (_, input) => {
		expect(() => generate(input)).toThrow();
	});

	const B = { type: 'object', properties: {} };

	it.each([
		['oneOf', { A: { oneOf: [{ type: 'string' }, { type: 'integer' }] } }, /A uses .* oneOf/],
		['allOf', { A: { allOf: [{ $ref: '#/components/schemas/B' }] }, B }, /A uses .* allOf/],
		['not', { A: { not: { type: 'string' } } }, /A uses .* not/],
		[
			'oneOf on a property',
			{ A: { type: 'object', properties: { a: { oneOf: [{ type: 'string' }] } } } },
			/A\.a uses .* oneOf/
		],
		[
			'allOf inside anyOf',
			{ A: { anyOf: [{ allOf: [{ $ref: '#/components/schemas/B' }] }, { type: 'null' }] }, B },
			/A\.anyOf\[0\] uses .* allOf/
		],
		['prefixItems', { A: { type: 'array', prefixItems: [{ type: 'string' }] } }, /prefixItems/],
		[
			'patternProperties',
			{ A: { type: 'object', patternProperties: { '^x-': { type: 'string' } } } },
			/patternProperties/
		],
		[
			'a $ref with a type next to it',
			{ A: { $ref: '#/components/schemas/B', type: 'object', properties: { x: {} } }, B },
			/A combines \$ref with/
		],
		[
			'a composed page',
			{
				Page_B_: {
					type: 'object',
					required: ['items'],
					allOf: [{ $ref: '#/components/schemas/B' }],
					properties: {
						items: { type: 'array', items: { $ref: '#/components/schemas/B' } },
						next_cursor: { anyOf: [{ type: 'string' }, { type: 'null' }] }
					}
				},
				B
			},
			/Page_B_ uses .* allOf/
		]
	])('refuses %s instead of typing it as unknown', (_, schemas, message) => {
		expect(() => generate(document(schemas))).toThrow(message);
	});
});
