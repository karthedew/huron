/**
 * Generates `src/lib/api/openapi.ts` from the API contract `docs/openapi.json`.
 *
 * One export per `components.schemas` entry under its pydantic name; every `Page_X_` entry
 * becomes the single generic `Page<T>`. Unsupported schema constructs fail loudly instead of
 * degrading to `unknown`, so a contract change cannot silently weaken the types.
 *
 * Usage (from `web/`): `npm run generate:api`.
 */
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, relative } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

/** The API contract, relative to this script. */
export const OPENAPI_DOCUMENT = fileURLToPath(new URL('../../docs/openapi.json', import.meta.url));

/** The generated module, relative to this script. */
export const GENERATED_MODULE = fileURLToPath(
	new URL('../src/lib/api/openapi.ts', import.meta.url)
);

const HEADER = [
	'// Generated from docs/openapi.json by web/scripts/generate-api-types.mjs — do not edit.',
	'// Regenerate with `npm run generate:api` after the API contract changes.'
].join('\n');

const REF_PREFIX = '#/components/schemas/';
const PAGE_NAME = /^Page_([A-Za-z0-9]+)_$/;
const IDENTIFIER = /^[A-Za-z_$][A-Za-z0-9_$]*$/;

/** Keywords this generator turns into TypeScript. */
const TYPE_KEYWORDS = new Set([
	'$ref',
	'anyOf',
	'enum',
	'const',
	'type',
	'properties',
	'required',
	'items',
	'additionalProperties'
]);

/** Keywords that annotate or constrain a value without changing its TypeScript type. */
const ANNOTATION_KEYWORDS = new Set([
	'$comment',
	'title',
	'description',
	'default',
	'examples',
	'deprecated',
	'readOnly',
	'writeOnly',
	'format',
	'contentEncoding',
	'contentMediaType',
	'minLength',
	'maxLength',
	'pattern',
	'minimum',
	'maximum',
	'exclusiveMinimum',
	'exclusiveMaximum',
	'multipleOf',
	'minItems',
	'maxItems',
	'uniqueItems',
	'minProperties',
	'maxProperties'
]);

/**
 * @typedef {Record<string, unknown>} Schema
 */

/**
 * Render the TypeScript module for an OpenAPI document.
 *
 * @param {unknown} document A parsed OpenAPI 3.1 document.
 * @returns {string} The module source, deterministic for a given document.
 */
export function generate(document) {
	const schemas = componentSchemas(document);
	/** @type {string[]} */
	const blocks = [];
	let pageWritten = false;
	for (const name of Object.keys(schemas).sort(compare)) {
		const schema = schemas[name];
		const page = PAGE_NAME.exec(name);
		if (page) {
			checkPage(name, schema, page[1]);
			if (!pageWritten) blocks.push(pageDeclaration());
			pageWritten = true;
			continue;
		}
		blocks.push(declaration(name, schema));
	}
	return `${HEADER}\n\n${blocks.join('\n\n')}\n`;
}

/**
 * @param {unknown} document
 * @returns {Record<string, Schema>}
 */
function componentSchemas(document) {
	const components = isRecord(document) ? document.components : undefined;
	const schemas = isRecord(components) ? components.schemas : undefined;
	if (!isRecord(schemas)) throw new Error('the document has no components.schemas object');
	/** @type {Record<string, Schema>} */
	const result = {};
	for (const [name, schema] of Object.entries(schemas)) {
		if (!IDENTIFIER.test(name))
			throw new Error(`schema name ${JSON.stringify(name)} is not an identifier`);
		if (!isRecord(schema)) throw new Error(`schema ${name} is not an object`);
		result[name] = schema;
	}
	return result;
}

/**
 * @param {string} name
 * @param {Schema} schema
 * @returns {string}
 */
function declaration(name, schema) {
	checkKeywords(schema, name);
	const comment = docComment(descriptionLines(schema), '');
	if (isRecord(schema.properties)) {
		return `${comment}export interface ${name} ${objectBody(schema, name, '')}`;
	}
	return `${comment}export type ${name} = ${typeOf(schema, name)};`;
}

/**
 * @param {Schema} schema
 * @param {string} where
 * @param {string} indent
 * @returns {string}
 */
function objectBody(schema, where, indent) {
	const properties = isRecord(schema.properties) ? schema.properties : {};
	const required = stringList(schema.required, `${where}.required`);
	const inner = `${indent}\t`;
	/** @type {string[]} */
	const lines = [];
	for (const [key, property] of Object.entries(properties)) {
		if (!isRecord(property)) throw new Error(`${where}.${key} is not a schema object`);
		const optional = required.includes(key) ? '' : '?';
		const name = IDENTIFIER.test(key) ? key : quote(key);
		lines.push(
			`${docComment(propertyLines(property), inner)}${inner}${name}${optional}: ${typeOf(property, `${where}.${key}`, inner)};`
		);
	}
	if (lines.length === 0) return '{}';
	return `{\n${lines.join('\n')}\n${indent}}`;
}

/**
 * @param {Schema} schema
 * @param {string} where
 * @param {string} [indent]
 * @returns {string}
 */
function typeOf(schema, where, indent = '') {
	checkKeywords(schema, where);
	if (typeof schema.$ref === 'string') return reference(schema.$ref, where);
	if (Array.isArray(schema.anyOf)) {
		return union(
			schema.anyOf.map((member, index) => {
				if (!isRecord(member)) throw new Error(`${where}.anyOf[${index}] is not a schema object`);
				return typeOf(member, `${where}.anyOf[${index}]`, indent);
			})
		);
	}
	if (Array.isArray(schema.enum)) return union(schema.enum.map((value) => literal(value, where)));
	if ('const' in schema) return literal(schema.const, where);
	if (Array.isArray(schema.type)) {
		return union(schema.type.map((type) => primitive(type, schema, where, indent)));
	}
	if (schema.type === undefined) {
		if (isRecord(schema.properties)) return objectBody(schema, where, indent);
		return 'unknown';
	}
	return primitive(schema.type, schema, where, indent);
}

/**
 * @param {unknown} type
 * @param {Schema} schema
 * @param {string} where
 * @param {string} indent
 * @returns {string}
 */
function primitive(type, schema, where, indent) {
	switch (type) {
		case 'string':
			return 'string';
		case 'integer':
		case 'number':
			return 'number';
		case 'boolean':
			return 'boolean';
		case 'null':
			return 'null';
		case 'array': {
			if (schema.items === undefined) return 'unknown[]';
			if (!isRecord(schema.items)) throw new Error(`${where}.items is not a schema object`);
			return arrayOf(typeOf(schema.items, `${where}.items`, indent));
		}
		case 'object': {
			if (isRecord(schema.properties)) return objectBody(schema, where, indent);
			if (isRecord(schema.additionalProperties)) {
				return `Record<string, ${typeOf(schema.additionalProperties, `${where}.additionalProperties`, indent)}>`;
			}
			return 'Record<string, unknown>';
		}
		default:
			throw new Error(`${where} has the unsupported type ${JSON.stringify(type)}`);
	}
}

/**
 * Refuse what the generator would otherwise drop silently: keywords it does not translate
 * (`oneOf`, `allOf`, `not`, `prefixItems`, …) and a `$ref` next to anything but annotations.
 *
 * @param {Schema} schema
 * @param {string} where
 */
function checkKeywords(schema, where) {
	for (const key of Object.keys(schema)) {
		if (!TYPE_KEYWORDS.has(key) && !ANNOTATION_KEYWORDS.has(key)) {
			throw new Error(`${where} uses the unsupported keyword ${key}`);
		}
		if ('$ref' in schema && key !== '$ref' && TYPE_KEYWORDS.has(key)) {
			throw new Error(`${where} combines $ref with ${key}`);
		}
	}
}

/**
 * @param {string} ref
 * @param {string} where
 * @returns {string}
 */
function reference(ref, where) {
	if (!ref.startsWith(REF_PREFIX)) throw new Error(`${where} has the unsupported $ref ${ref}`);
	const target = ref.slice(REF_PREFIX.length);
	if (!IDENTIFIER.test(target)) throw new Error(`${where} refers to the invalid name ${target}`);
	const page = PAGE_NAME.exec(target);
	return page ? `Page<${page[1]}>` : target;
}

/**
 * Check that a `Page_X_` schema is exactly `{ items: X[]; next_cursor?: string | null }`.
 *
 * @param {string} name
 * @param {Schema} schema
 * @param {string} item
 */
function checkPage(name, schema, item) {
	checkKeywords(schema, name);
	const properties = isRecord(schema.properties) ? schema.properties : {};
	const keys = Object.keys(properties).sort(compare);
	const items = properties.items;
	const cursor = properties.next_cursor;
	const required = stringList(schema.required, `${name}.required`);
	const itemsOk = isRecord(items) && typeOf(items, `${name}.items`) === `${item}[]`;
	const cursorOk = isRecord(cursor) && typeOf(cursor, `${name}.next_cursor`) === 'string | null';
	const shapeOk =
		keys.join(',') === 'items,next_cursor' && required.length === 1 && required[0] === 'items';
	if (!(itemsOk && cursorOk && shapeOk)) {
		throw new Error(
			`${name} is not the page shape { items: ${item}[]; next_cursor?: string | null }`
		);
	}
}

/** @returns {string} */
function pageDeclaration() {
	return [
		'/** One page of a keyset-paginated list; `next_cursor` is absent or null on the last page. */',
		'export interface Page<T> {',
		'\titems: T[];',
		'\tnext_cursor?: string | null;',
		'}'
	].join('\n');
}

/**
 * @param {Schema} schema
 * @returns {string[]}
 */
function descriptionLines(schema) {
	return typeof schema.description === 'string' && schema.description.trim()
		? schema.description.trim().split('\n')
		: [];
}

/**
 * @param {Schema} property
 * @returns {string[]}
 */
function propertyLines(property) {
	const formats = new Set();
	if (typeof property.format === 'string') formats.add(property.format);
	if (Array.isArray(property.anyOf)) {
		for (const member of property.anyOf) {
			if (isRecord(member) && typeof member.format === 'string') formats.add(member.format);
		}
	}
	const lines = descriptionLines(property);
	if (formats.size > 0) lines.push(`Format: ${[...formats].join(', ')}.`);
	return lines;
}

/**
 * @param {string[]} lines
 * @param {string} indent
 * @returns {string}
 */
function docComment(lines, indent) {
	if (lines.length === 0) return '';
	const safe = lines.map((line) => line.replaceAll('*/', '*\\/'));
	if (safe.length === 1) return `${indent}/** ${safe[0]} */\n`;
	return `${indent}/**\n${safe.map((line) => `${indent} * ${line}`).join('\n')}\n${indent} */\n`;
}

/**
 * @param {string[]} members
 * @returns {string}
 */
function union(members) {
	const unique = [...new Set(members)];
	if (unique.length === 0) return 'never';
	return unique.join(' | ');
}

/**
 * @param {string} type
 * @returns {string}
 */
function arrayOf(type) {
	return /^[A-Za-z0-9_$<>, ]+$/.test(type) && !type.includes(' | ') ? `${type}[]` : `(${type})[]`;
}

/**
 * @param {unknown} value
 * @param {string} where
 * @returns {string}
 */
function literal(value, where) {
	if (typeof value === 'string') return quote(value);
	if (typeof value === 'number' && Number.isFinite(value)) return String(value);
	if (typeof value === 'boolean' || value === null) return String(value);
	throw new Error(`${where} has an unsupported literal ${JSON.stringify(value)}`);
}

/**
 * @param {string} value
 * @returns {string}
 */
function quote(value) {
	return `'${value.replaceAll('\\', '\\\\').replaceAll("'", "\\'").replaceAll('\n', '\\n')}'`;
}

/**
 * @param {unknown} value
 * @param {string} where
 * @returns {string[]}
 */
function stringList(value, where) {
	if (value === undefined) return [];
	if (!Array.isArray(value) || !value.every((entry) => typeof entry === 'string')) {
		throw new Error(`${where} is not a list of strings`);
	}
	return value;
}

/**
 * @param {unknown} value
 * @returns {value is Record<string, unknown>}
 */
function isRecord(value) {
	return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/**
 * Code-unit order, independent of the locale.
 *
 * @param {string} a
 * @param {string} b
 * @returns {number}
 */
function compare(a, b) {
	return a < b ? -1 : a > b ? 1 : 0;
}

function main() {
	const document = JSON.parse(readFileSync(OPENAPI_DOCUMENT, 'utf8'));
	mkdirSync(dirname(GENERATED_MODULE), { recursive: true });
	writeFileSync(GENERATED_MODULE, generate(document));
	console.log(`wrote ${relative(process.cwd(), GENERATED_MODULE)}`);
}

if (process.argv[1] && pathToFileURL(process.argv[1]).href === import.meta.url) main();
