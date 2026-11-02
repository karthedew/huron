/**
 * A resolved metadata schema as a field table: one row per property, nested properties
 * flattened under their parent (`Contacts › name`), with what each accepts. The keywords are the
 * subset `src/huron/schema/documents/schema-document-v1.json` allows.
 */
import type { JsonObject, JsonSchemaDocument, JsonValue } from '$api/types';
import { clip, countLabel, formatCount, formatNumber, shortened } from './format';
import {
	booleanField,
	exactJson,
	integerDigits,
	isJsonObject,
	numberField,
	ownValue,
	stringField
} from './json';

export interface SchemaField {
	/**
	 * Unique within the table: the property keys from the top down as JSON Pointer tokens, joined
	 * by `/` (`contacts/name`). A key's own `~` and `/` are escaped as `~0` and `~1` (RFC 6901), so
	 * a property named `instrument/name` never meets `name` inside `instrument`.
	 */
	key: string;
	/** Each level's title, else its key, from the top down: `Contacts › name`. */
	label: string;
	/** 0 for a top-level property. */
	depth: number;
	type: string;
	/** Required at its own level: by the schema, or by each object of its parent. */
	required: boolean;
	constraints: string[];
	description: string;
}

/**
 * What the schema pages show, as plain values. Loads return the view rather than the document:
 * property names are whatever the schema's author chose, and SvelteKit's serializer refuses an
 * object with its own `__proto__` key (which `JSON.parse` keeps).
 */
export interface SchemaView {
	title: string | null;
	description: string | null;
	/** Whether metadata may hold fields the schema does not name; `null` when it does not say. */
	otherFields: boolean | null;
	/** The first `MAX_SCHEMA_FIELDS` rows. */
	fields: SchemaField[];
	/** How many more rows the schema has. */
	moreFields: number;
	/**
	 * The document itself as indented JSON text, its first `SCHEMA_JSON_LENGTH` code points.
	 * Here and in the constraints, an integer too large for a number keeps the digits the API
	 * wrote, where the document was parsed with `parseExactly`, as schema documents are
	 * (`HuronApi`'s exact reads).
	 */
	json: string;
	/** Whether `json` holds only the start of the document. */
	jsonShortened: boolean;
	/** Whether the view leaves anything out: rows, the end of a text, or of the JSON. */
	shortened: boolean;
}

/**
 * The most rows a schema's table shows; the rest are counted. The API bounds no schema's size,
 * and a contributor's override of 20,000 properties made a Schema tab of 44 MB.
 */
export const MAX_SCHEMA_FIELDS = 200;

/** The longest text one cell of the table shows, in code points; a longer one ends in `…`. */
export const SCHEMA_TEXT_LENGTH = 1_000;

/** The most values of an `enum` a constraint names; the rest are counted. */
export const MAX_ENUM_VALUES = 50;

/** The most JSON text of a document the page shows, in code points (256 KiB of ASCII). */
export const SCHEMA_JSON_LENGTH = 262_144;

const PLURALS: Readonly<Record<string, string>> = {
	string: 'strings',
	number: 'numbers',
	integer: 'integers',
	boolean: 'booleans',
	array: 'arrays',
	object: 'objects'
};

/**
 * The table of a resolved schema document: its first `MAX_SCHEMA_FIELDS` rows, each text cut to
 * `SCHEMA_TEXT_LENGTH`, and its JSON to `SCHEMA_JSON_LENGTH`.
 */
export function schemaView(document: JsonSchemaDocument): SchemaView {
	const table: Table = { rows: [], more: 0, shortened: false };
	propertyRows(document, [], [], table);
	const json = clip(exactJson(document, 2), SCHEMA_JSON_LENGTH);
	const title = textOf(stringField(document, 'title'), table);
	const description = textOf(stringField(document, 'description'), table);
	return {
		title,
		description,
		otherFields: booleanField(document, 'additionalProperties'),
		fields: table.rows,
		moreFields: table.more,
		json: json.text,
		jsonShortened: json.cut,
		shortened: table.shortened || table.more > 0 || json.cut
	};
}

/** The rows a table shows, how many more it has, and whether any text was cut. */
interface Table {
	rows: SchemaField[];
	more: number;
	shortened: boolean;
}

/** A text as a cell shows it: at most `SCHEMA_TEXT_LENGTH` code points. */
function cellText(text: string, table: Table): string {
	const shown = clip(text, SCHEMA_TEXT_LENGTH);
	if (shown.cut) table.shortened = true;
	return shown.text;
}

function textOf(text: string | null, table: Table): string | null {
	return text === null ? null : cellText(text, table);
}

/** The keys an object schema requires at its own level, once each, in its order. */
export function requiredKeys(schema: JsonObject | null): string[] {
	return schema === null ? [] : [...new Set(strings(ownValue(schema, 'required')))];
}

/**
 * Keys in the order of the CLI's metadata walkthrough: those the schema requires, in its
 * `required` order, then the others by key. A fixed comparison, so the server and the browser
 * order keys alike.
 */
export function walkthroughOrder(schema: JsonObject | null, keys: readonly string[]): string[] {
	// Sets keep this linear: metadata objects and schemas may both hold many thousands of keys.
	const present = new Set(keys);
	const required = requiredKeys(schema).filter((key) => present.has(key));
	const first = new Set(required);
	const others = [...present].filter((key) => !first.has(key)).sort(byCodePoint);
	return [...required, ...others];
}

/** The schema of one property of an object schema, if it names one. */
export function propertySchema(schema: JsonObject | null, key: string): JsonObject | null {
	if (schema === null) return null;
	const properties = ownValue(schema, 'properties');
	if (!isJsonObject(properties)) return null;
	const property = ownValue(properties, key);
	return isJsonObject(property) ? property : null;
}

/** The schema of an array schema's items, if it has one. */
export function itemsSchema(schema: JsonObject | null): JsonObject | null {
	const items = schema === null ? undefined : ownValue(schema, 'items');
	return isJsonObject(items) ? items : null;
}

/**
 * The rows of an object schema's properties in walkthrough order, each followed by the rows of
 * its own properties (or its items' properties), into `table` while it has room; the rows that
 * do not fit are counted.
 */
function propertyRows(
	schema: JsonObject,
	keys: readonly string[],
	labels: readonly string[],
	table: Table
): void {
	const properties = ownValue(schema, 'properties');
	if (!isJsonObject(properties)) return;
	// A set: a schema may require many thousands of keys.
	const required = new Set(requiredKeys(schema));
	for (const name of walkthroughOrder(schema, Object.keys(properties))) {
		const property = properties[name];
		if (!isJsonObject(property)) continue;
		const path = [...keys, name];
		const label = [
			...labels,
			shortened(stringField(property, 'title') ?? name, SCHEMA_TEXT_LENGTH)
		];
		if (table.rows.length < MAX_SCHEMA_FIELDS) {
			table.rows.push({
				key: cellText(path.map(pointerToken).join('/'), table),
				label: cellText(label.join(' › '), table),
				depth: keys.length,
				type: cellText(typeText(property), table),
				required: required.has(name),
				constraints: constraints(property).map((rule) => cellText(rule, table)),
				description: cellText(stringField(property, 'description') ?? '', table)
			});
		} else {
			table.more += 1;
		}
		const items = ownValue(property, 'items');
		const nested = isJsonObject(items) && hasType(property, 'array') ? items : property;
		propertyRows(nested, path, label, table);
	}
}

function typeText(schema: JsonObject): string {
	const type = typeOf(schema);
	if (type !== 'array') return type;
	const items = ownValue(schema, 'items');
	if (!isJsonObject(items)) return 'array';
	const itemType = typeOf(items);
	return `array of ${PLURALS[itemType] ?? itemType}`;
}

function typeOf(schema: JsonObject): string {
	const type = ownValue(schema, 'type');
	if (typeof type === 'string') return type;
	if (Array.isArray(type)) {
		const names = type.filter((name): name is string => typeof name === 'string');
		if (names.length > 0) return names.join(' or ');
	}
	return 'any';
}

function hasType(schema: JsonObject, type: string): boolean {
	return typeOf(schema) === type;
}

/** What a property accepts beyond its type, in a fixed order. */
function constraints(schema: JsonObject): string[] {
	const found: string[] = [];
	const enumeration = ownValue(schema, 'enum');
	if (Array.isArray(enumeration)) {
		const values = enumeration
			.slice(0, MAX_ENUM_VALUES)
			.map((value, index) => literal(value, enumeration, String(index)));
		const more = enumeration.length - values.length;
		found.push(`one of ${values.join(', ')}${more > 0 ? `, and ${formatCount(more)} more` : ''}`);
	}
	const constant = ownValue(schema, 'const');
	if (constant !== undefined) found.push(`exactly ${literal(constant, schema, 'const')}`);
	const range = bounds(numberText(schema, 'minimum'), numberText(schema, 'maximum'));
	if (range !== null) found.push(range);
	const length = sizes(schema, 'minLength', 'maxLength', 'character');
	if (length !== null) found.push(length);
	const pattern = stringField(schema, 'pattern');
	if (pattern !== null) found.push(`pattern ${pattern}`);
	const format = stringField(schema, 'format');
	if (format !== null) found.push(`format ${format}`);
	const count = sizes(schema, 'minItems', 'maxItems', 'item');
	if (count !== null) found.push(count);
	if (booleanField(schema, 'uniqueItems') === true) found.push('unique items');
	const items = ownValue(schema, 'items');
	if (isJsonObject(items)) {
		for (const rule of constraints(items)) found.push(`each item: ${rule}`);
	}
	found.push(...extraKeys(schema));
	const fallback = ownValue(schema, 'default');
	if (fallback !== undefined) found.push(`default ${literal(fallback, schema, 'default')}`);
	return found;
}

/** What an object schema says about keys its properties do not name. */
function extraKeys(schema: JsonObject): string[] {
	const extra = ownValue(schema, 'additionalProperties');
	if (extra === false) return ['no other keys'];
	if (!isJsonObject(extra)) return [];
	return [
		`each value: ${typeText(extra)}`,
		...constraints(extra).map((rule) => `each value: ${rule}`)
	];
}

function bounds(minimum: string | null, maximum: string | null): string | null {
	if (minimum !== null && maximum !== null) return `from ${minimum} to ${maximum}`;
	if (minimum !== null) return `at least ${minimum}`;
	if (maximum !== null) return `at most ${maximum}`;
	return null;
}

/** A number keyword in the fixed format, or the digits the API wrote where a number rounds them. */
function numberText(schema: JsonObject, key: string): string | null {
	const digits = integerDigits(schema, key);
	if (digits !== null) return digits;
	const value = numberField(schema, key);
	return value === null ? null : formatNumber(value);
}

function sizes(schema: JsonObject, minKey: string, maxKey: string, unit: string): string | null {
	const minimum = countValue(schema, minKey);
	const maximum = countValue(schema, maxKey);
	if (minimum !== null && maximum !== null) {
		return minimum === maximum
			? `exactly ${countLabel(minimum, unit)}`
			: `${formatCount(minimum)} to ${countLabel(maximum, unit)}`;
	}
	if (minimum !== null) return `at least ${countLabel(minimum, unit)}`;
	if (maximum !== null) return `at most ${countLabel(maximum, unit)}`;
	return null;
}

/**
 * A count keyword (`maxLength`, `minItems`), as a `bigint` where a number would round it. Only
 * such counts are `bigint`s, so a `bigint` and a number never hold the same count and `===`
 * still tells counts apart.
 */
function countValue(schema: JsonObject, key: string): number | bigint | null {
	const digits = integerDigits(schema, key);
	return digits === null ? numberField(schema, key) : BigInt(digits);
}

function pointerToken(key: string): string {
	return key.replaceAll('~', '~0').replaceAll('/', '~1');
}

/** `holder[key]` as JSON text, with the digits the API wrote where a number rounds them. */
function literal(value: JsonValue, holder: object, key: string): string {
	return integerDigits(holder, key) ?? exactJson(value);
}

function strings(value: JsonValue | undefined): string[] {
	return Array.isArray(value)
		? value.filter((item): item is string => typeof item === 'string')
		: [];
}

/** A fixed comparison, so the server and the browser order keys alike. */
function byCodePoint(a: string, b: string): number {
	if (a === b) return 0;
	return a < b ? -1 : 1;
}
