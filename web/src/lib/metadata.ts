/**
 * A collection's metadata as its Overview shows it: the fields its schema names, in the order of
 * the CLI's walkthrough, then the fields it does not name, each with a label and its value ready
 * to show. Values become links only where that is safe (`http:` and `https:` URIs, email
 * addresses, labels the catalog search can find), times read as fixed UTC text and numbers in the
 * fixed format, so the page never depends on the viewer's locale or clock.
 *
 * Loads return these views rather than the metadata: its keys are whatever contributors chose,
 * and SvelteKit's serializer refuses an object with its own `__proto__` key (which `JSON.parse`
 * keeps), so one collection could otherwise break its page for every viewer.
 */
import type { CollectionProblem, JsonObject } from '$api/types';
import { metadataDescription, metadataTitle } from './collections';
import { clip, formatDate, formatNumber, formatTimestamp, timestampAttribute } from './format';
import { isJsonObject, isRecord, ownValue, stringField } from './json';
import { itemsSchema, propertySchema, requiredKeys, walkthroughOrder } from './schema-view';

/** How one value shows. */
export type MetadataValue =
	/** Text as it was written; also a value its format could not read. */
	| { kind: 'text'; text: string }
	/** A number in the fixed format. */
	| { kind: 'number'; text: string }
	/** `Yes` or `No`. */
	| { kind: 'boolean'; text: string }
	/** A `date-time` or `date`: fixed UTC text and the value of `<time datetime>`. */
	| { kind: 'time'; text: string; datetime: string }
	/** An `email` address, linked with `mailto:`. */
	| { kind: 'email'; text: string; href: string }
	/** A `uri` with an `http:` or `https:` scheme; other schemes show as text. */
	| { kind: 'link'; text: string; href: string }
	/** An array of scalars: a chip each, as text; `more` counts the items left out. */
	| { kind: 'chips'; items: string[]; more: number }
	/** The `labels` object: a `key: value` chip each; `more` counts the labels left out. */
	| { kind: 'labels'; items: LabelChip[]; more: number }
	/** An array that holds objects or arrays: each item in turn; `more` counts those left out. */
	| { kind: 'list'; items: MetadataValue[]; more: number }
	/** An object: its fields; `more` counts those left out. */
	| { kind: 'object'; fields: MetadataField[]; more: number }
	/** `null`, an empty array or an empty object. */
	| { kind: 'none' }
	/** A field the schema requires and the metadata lacks. */
	| { kind: 'missing' };

export interface MetadataField {
	/** The key, shortened to `VALUE_LENGTH` (two long keys may then read alike). */
	key: string;
	/** The schema's title for the field, else its key made readable. */
	label: string;
	value: MetadataValue;
}

/** One label of `labels`. */
export interface LabelChip {
	key: string;
	value: string;
	/**
	 * The `key=value` filter the catalog search finds it by; `null` where the search cannot (a key
	 * that is empty or holds `=`, where the filter splits, or a value that is not text) or where a
	 * key or value is longer than a chip searches for (`MAX_LABEL_LENGTH`).
	 */
	filter: string | null;
}

export interface MetadataView {
	/** The fields the schema names, in walkthrough order; required ones the metadata lacks are missing. */
	fields: MetadataField[];
	/** The fields the schema does not name, by key. */
	other: MetadataField[];
	/** How many more fields there are, of either kind, beyond the values the view shows. */
	more: number;
	/** Whether the view leaves anything out: fields, items of a value, or the end of a text. */
	shortened: boolean;
}

/** A validation problem of the metadata, with the field it is about. */
export interface ProblemRow {
	/** The labels on the way to the field, `Contacts › 1 › Email`; `null` for the whole document. */
	field: string | null;
	message: string;
}

/** The first problems of a collection, and how many more follow them. */
export interface ProblemRows {
	rows: ProblemRow[];
	more: number;
}

/**
 * At most this many items of one array, object or `labels` show, and this many problems; the
 * rest are counted. A long list says little more after its first items.
 */
export const MAX_ITEMS = 50;

/**
 * At most this many values show in all, however they nest: fields, items and labels each count.
 * Metadata may take up a mebibyte, and as markup a value takes many times its JSON, so without a
 * bound one collection could make its page tens of megabytes for every reader.
 */
export const MAX_VALUES = 1000;

/**
 * The longest text one value, key or label shows, in code points; a longer one ends in `…`. A
 * single string may take up most of a mebibyte, and the page repeats it in its markup and data.
 */
export const VALUE_LENGTH = 5_000;

/**
 * The most text the view shows in all, in code points, keys and labels included: capping each
 * text alone would still let a mebibyte spread over many values.
 */
export const TEXT_BUDGET = 100_000;

/**
 * The longest problem message, and the longest field it names, a problem row shows, in code
 * points: the API's messages quote the value they are about, a title of a mebibyte included.
 */
export const PROBLEM_LENGTH = 1_000;

/**
 * The longest label key or value, in code points, a chip searches for. Its link holds the whole
 * label in its address, and the search page's links repeat it: nobody filters by a paragraph, and
 * a label may take up most of a mebibyte. Search results show no more of either (`search.ts`).
 */
export const MAX_LABEL_LENGTH = 100;

/** Nesting shown as fields and lists; anything deeper shows as its JSON text. */
const MAX_DEPTH = 4;

const DATE = /^(\d{4})-(\d{2})-(\d{2})$/;
/** RFC 3339: a time with seconds and an offset, so it names one instant wherever it is read. */
const DATE_TIME =
	/^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(?:[Zz]|[+-](\d{2}):(\d{2}))$/;
/**
 * The years both the fixed `YYYY-MM-DD` text and `<time datetime>` can write: HTML has no year
 * 0, and `toISOString` writes years past 9999 with six digits and a sign.
 */
const FIRST_YEAR = 1;
const LAST_YEAR = 9999;
/**
 * One address and nothing more: no second recipient (`,` `;`), no query or fragment that would
 * fill in more of the mail (`?` `#`), no percent-encoding that could spell any of those or a line
 * break, and no space, control character or other character an address holds only in quotes.
 */
const EMAIL = /^[^\s\p{Cc}@?#%,;:<>()[\]\\"]+@[^\s\p{Cc}@?#%,;:<>()[\]\\"]+$/u;

/** What a view may still show, and whether it has left anything out. */
interface Budget {
	/** Values. */
	left: number;
	/** Code points of text. */
	text: number;
	shortened: boolean;
}

/**
 * The metadata of a collection against its resolved schema. With no schema (it could not be
 * resolved), every field shows by its key, in key order, and nothing is marked missing. The title
 * and the description stay out where the page's head shows them. Long values show their first
 * items (`MAX_ITEMS`), long texts their first `VALUE_LENGTH` code points, and the view as a
 * whole at most `MAX_VALUES` values and `TEXT_BUDGET` code points.
 */
export function metadataView(
	metadata: Readonly<Record<string, unknown>>,
	schema: JsonObject | null
): MetadataView {
	const budget: Budget = { left: MAX_VALUES, text: TEXT_BUDGET, shortened: false };
	const headed = new Set<string>();
	if (metadataTitle(metadata) !== null) headed.add('title');
	if (metadataDescription(metadata) !== null) headed.add('description');
	const present = Object.keys(metadata).filter((key) => !headed.has(key));
	if (schema === null) {
		const fields = firstItems(walkthroughOrder(null, present), MAX_VALUES, budget, (key) =>
			topField(metadata, key, null, budget)
		);
		return { fields: fields.items, other: [], more: fields.more, shortened: budget.shortened };
	}
	const named = new Set(schemaKeys(schema));
	const required = new Set(requiredKeys(schema));
	const fields = firstItems(
		walkthroughOrder(schema, [...named]).filter(
			(key) => !headed.has(key) && (Object.hasOwn(metadata, key) || required.has(key))
		),
		MAX_VALUES,
		budget,
		(key): MetadataField => {
			const property = propertySchema(schema, key);
			return Object.hasOwn(metadata, key)
				? topField(metadata, key, property, budget)
				: {
						key: shownText(key, budget),
						label: labelOf(key, property, budget),
						value: { kind: 'missing' }
					};
		}
	);
	const other = firstItems(
		walkthroughOrder(
			null,
			present.filter((key) => !named.has(key))
		),
		MAX_VALUES,
		budget,
		(key) => topField(metadata, key, null, budget)
	);
	return {
		fields: fields.items,
		other: other.items,
		more: fields.more + other.more,
		shortened: budget.shortened
	};
}

/**
 * The problems of a draft or incomplete collection: the first `MAX_ITEMS`, each with the field it
 * is about, and how many more there are. Messages and fields show their first `PROBLEM_LENGTH`
 * code points.
 */
export function problemRows(
	problems: readonly CollectionProblem[],
	schema: JsonObject | null,
	metadata: Readonly<Record<string, unknown>>
): ProblemRows {
	const first = problems.slice(0, MAX_ITEMS);
	return {
		rows: first.map(({ path, message }) => {
			const field = pointerLabel(path, schema, metadata);
			return {
				field: field === null ? null : clip(field, PROBLEM_LENGTH).text,
				message: clip(message, PROBLEM_LENGTH).text
			};
		}),
		more: problems.length - first.length
	};
}

/**
 * The labels along a problem's JSON pointer: `/contacts/0/email` gives `Contacts › 1 › Email`
 * (items count from 1). `null` for the document itself (`/`), whose message names the field. The
 * API joins the keys with `/` without escaping them, so where a key itself holds `/` the longest
 * run of segments that names a key wins.
 */
export function pointerLabel(
	pointer: string,
	schema: JsonObject | null,
	metadata: Readonly<Record<string, unknown>>
): string | null {
	const segments = pointer.split('/').slice(1);
	if (segments.every((segment) => segment === '')) return null;
	const labels: string[] = [];
	let node: unknown = metadata;
	let at = schema;
	let index = 0;
	while (index < segments.length) {
		if (Array.isArray(node) && /^\d+$/.test(segments[index])) {
			const items: readonly unknown[] = node;
			const position = Number(segments[index]);
			labels.push(String(position + 1));
			node = items[position];
			at = itemsSchema(at);
			index += 1;
			continue;
		}
		const object = isRecord(node) ? node : {};
		const named = new Set(schemaKeys(at));
		// Looked up one by one: the object may hold many thousands of keys.
		const known = (key: string) => Object.hasOwn(object, key) || named.has(key);
		let end = segments.length;
		while (end > index + 1 && !known(segments.slice(index, end).join('/'))) end -= 1;
		const key = segments.slice(index, end).join('/');
		const property = propertySchema(at, key);
		labels.push(labelOf(key, property, unbounded()));
		node = ownValue(object, key);
		at = property;
		index = end;
	}
	return labels.join(' › ');
}

/** A key made readable for a label: `start_time` gives `Start time`. */
export function humanizeKey(key: string): string {
	const words = key.replaceAll('_', ' ').replace(/\s+/g, ' ').trim();
	if (words === '') return key === '' ? '""' : key;
	return words.charAt(0).toUpperCase() + words.slice(1);
}

/**
 * A collection's labels as chips, by key: the first `MAX_ITEMS`, and how many more there are.
 * Lists of collections, such as search results, show them as the Overview's metadata does.
 */
export function labelChips(metadata: Readonly<Record<string, unknown>>): {
	items: LabelChip[];
	more: number;
} {
	const labels = ownValue(metadata, 'labels');
	if (!isRecord(labels)) return { items: [], more: 0 };
	const budget = unbounded();
	return firstItems(walkthroughOrder(null, Object.keys(labels)), MAX_ITEMS, budget, (key) =>
		labelChip(labels, key, budget)
	);
}

/** A budget that runs out of nothing; each text still shows at most `VALUE_LENGTH`. */
function unbounded(): Budget {
	return { left: Infinity, text: Infinity, shortened: false };
}

/**
 * A text as the view shows it: at most `VALUE_LENGTH` code points, and no more than the budget
 * has left, which it takes them from.
 */
function shownText(text: string, budget: Budget): string {
	const shown = clip(text, Math.max(0, Math.min(VALUE_LENGTH, budget.text)));
	budget.text -= shown.kept;
	if (shown.cut) budget.shortened = true;
	return shown.text;
}

/**
 * The first of `items` as `show` presents them, as many as `cap` and what the budget has left
 * allow; `more` counts the rest. Each item takes its share before `show` runs, so what nests
 * inside an item comes out of what is left after it.
 */
function firstItems<T, U>(
	items: readonly T[],
	cap: number,
	budget: Budget,
	show: (item: T) => U
): { items: U[]; more: number } {
	const shown: U[] = [];
	for (const item of items) {
		if (shown.length >= cap || budget.left <= 0 || budget.text <= 0) break;
		budget.left -= 1;
		shown.push(show(item));
	}
	const more = items.length - shown.length;
	if (more > 0) budget.shortened = true;
	return { items: shown, more };
}

/** A top-level field: its `labels` are label chips, everything else shows by its value. */
function topField(
	metadata: Readonly<Record<string, unknown>>,
	key: string,
	schema: JsonObject | null,
	budget: Budget
): MetadataField {
	const value = ownValue(metadata, key);
	if (key === 'labels' && isRecord(value)) {
		return { key, label: labelOf(key, schema, budget), value: labelsValue(value, budget) };
	}
	return field(key, value, schema, 0, budget);
}

function field(
	key: string,
	value: unknown,
	schema: JsonObject | null,
	depth: number,
	budget: Budget
): MetadataField {
	return {
		key: shownText(key, budget),
		label: labelOf(key, schema, budget),
		value: valueOf(value, schema, depth, budget)
	};
}

function labelOf(key: string, schema: JsonObject | null, budget: Budget): string {
	const title = schema === null ? null : stringField(schema, 'title');
	if (title !== null && title.trim() !== '') return shownText(title, budget);
	// Cut before it is made readable, which reads the whole key.
	return humanizeKey(shownText(key, budget));
}

function valueOf(
	value: unknown,
	schema: JsonObject | null,
	depth: number,
	budget: Budget
): MetadataValue {
	if (Array.isArray(value)) return arrayValue(value, schema, depth, budget);
	if (isRecord(value)) return objectValue(value, schema, depth, budget);
	return scalarValue(value, schema, budget);
}

/** A value that holds no other: text read by its format, a number, a boolean or none. */
function scalarValue(value: unknown, schema: JsonObject | null, budget: Budget): MetadataValue {
	if (value === null || value === undefined) return { kind: 'none' };
	if (typeof value === 'string') return textValue(value, schema, budget);
	if (typeof value === 'number') return { kind: 'number', text: formatNumber(value) };
	if (typeof value === 'boolean') return { kind: 'boolean', text: value ? 'Yes' : 'No' };
	return { kind: 'text', text: shownText(String(value), budget) };
}

/**
 * A string, read by the format its schema gives it; what the format cannot read stays text, and
 * so does a text too long to show in full: its link would lead elsewhere than it says.
 */
function textValue(text: string, schema: JsonObject | null, budget: Budget): MetadataValue {
	const shown = shownText(text, budget);
	if (shown !== text) return { kind: 'text', text: shown };
	switch (schema === null ? null : stringField(schema, 'format')) {
		case 'date-time': {
			const instant = dateTime(text);
			return instant === null
				? { kind: 'text', text }
				: { kind: 'time', text: formatTimestamp(instant), datetime: timestampAttribute(instant) };
		}
		case 'date':
			return isCalendarDate(text)
				? { kind: 'time', text: formatDate(text), datetime: text }
				: { kind: 'text', text };
		case 'email':
			return EMAIL.test(text)
				? { kind: 'email', text, href: `mailto:${text}` }
				: { kind: 'text', text };
		case 'uri': {
			const href = webAddress(text);
			return href === null ? { kind: 'text', text } : { kind: 'link', text, href };
		}
		default:
			return { kind: 'text', text };
	}
}

function arrayValue(
	items: readonly unknown[],
	schema: JsonObject | null,
	depth: number,
	budget: Budget
): MetadataValue {
	if (items.length === 0) return { kind: 'none' };
	if (depth >= MAX_DEPTH) return { kind: 'text', text: shownText(JSON.stringify(items), budget) };
	const item = itemsSchema(schema);
	if (items.every(isScalar)) {
		return {
			kind: 'chips',
			...firstItems(items, MAX_ITEMS, budget, (value) => scalarText(value, item, budget))
		};
	}
	return {
		kind: 'list',
		...firstItems(items, MAX_ITEMS, budget, (value) => valueOf(value, item, depth + 1, budget))
	};
}

function objectValue(
	object: Readonly<Record<string, unknown>>,
	schema: JsonObject | null,
	depth: number,
	budget: Budget
): MetadataValue {
	const keys = Object.keys(object);
	if (keys.length === 0) return { kind: 'none' };
	if (depth >= MAX_DEPTH) return { kind: 'text', text: shownText(JSON.stringify(object), budget) };
	const shown = firstItems(walkthroughOrder(schema, keys), MAX_ITEMS, budget, (key) =>
		field(key, ownValue(object, key), propertySchema(schema, key), depth + 1, budget)
	);
	return { kind: 'object', fields: shown.items, more: shown.more };
}

function labelsValue(labels: Readonly<Record<string, unknown>>, budget: Budget): MetadataValue {
	const keys = walkthroughOrder(null, Object.keys(labels));
	if (keys.length === 0) return { kind: 'none' };
	return {
		kind: 'labels',
		...firstItems(keys, MAX_ITEMS, budget, (key) => labelChip(labels, key, budget))
	};
}

/**
 * One label as a chip: numbers in the fixed format, key and value shortened to `VALUE_LENGTH`;
 * a filter only for text the search can find, no longer than `MAX_LABEL_LENGTH`.
 */
function labelChip(
	labels: Readonly<Record<string, unknown>>,
	key: string,
	budget: Budget
): LabelChip {
	const value = ownValue(labels, key);
	const searchable =
		typeof value === 'string' &&
		key !== '' &&
		!key.includes('=') &&
		!longerThan(key, MAX_LABEL_LENGTH) &&
		!longerThan(value, MAX_LABEL_LENGTH);
	return {
		key: shownText(key, budget),
		value: isScalar(value)
			? scalarText(value, null, budget)
			: shownText(JSON.stringify(value), budget),
		filter: searchable ? `${key}=${value}` : null
	};
}

/** Whether a text holds more than `limit` code points; it counts no further than that. */
function longerThan(text: string, limit: number): boolean {
	return text.length > limit && clip(text, limit).cut;
}

/** A scalar as the text of a chip, read by its format like a field's value. */
function scalarText(value: unknown, schema: JsonObject | null, budget: Budget): string {
	const shown = scalarValue(value, schema, budget);
	return 'text' in shown ? shown.text : 'None';
}

/** The keys an object schema names: its properties and its required keys. */
function schemaKeys(schema: JsonObject | null): string[] {
	const properties = schema === null ? undefined : ownValue(schema, 'properties');
	const names = isJsonObject(properties) ? Object.keys(properties) : [];
	return [...new Set([...names, ...requiredKeys(schema)])];
}

/**
 * An RFC 3339 date-time as text `Date` reads alike everywhere, or `null` when it is none or its
 * instant falls in a year the fixed format cannot write.
 */
function dateTime(text: string): string | null {
	const parts = DATE_TIME.exec(text);
	if (parts === null) return null;
	const [, year, month, day, hour, minute, second] = parts.map(Number);
	// `Z` leaves the offset's groups empty.
	const offset = parts[7] === undefined || (Number(parts[7]) <= 23 && Number(parts[8]) <= 59);
	const valid = isDay(year, month, day) && hour <= 23 && minute <= 59 && second <= 59 && offset;
	if (!valid) return null;
	const instant = text.replace(/[t ]/i, 'T').toUpperCase();
	// The offset can move the instant into another year: `9999-12-31T23:59:59-23:59` is in 10000.
	return isWritableYear(new Date(instant).getUTCFullYear()) ? instant : null;
}

function isCalendarDate(text: string): boolean {
	const parts = DATE.exec(text);
	if (parts === null) return false;
	const [, year, month, day] = parts.map(Number);
	return isDay(year, month, day) && isWritableYear(year);
}

function isWritableYear(year: number): boolean {
	return year >= FIRST_YEAR && year <= LAST_YEAR;
}

/** Whether a day exists; `Date` would roll `2024-02-30` over into March instead. */
function isDay(year: number, month: number, day: number): boolean {
	const date = new Date(0);
	date.setUTCFullYear(year, month - 1, day);
	return (
		date.getUTCFullYear() === year && date.getUTCMonth() === month - 1 && date.getUTCDate() === day
	);
}

/** The address of an `http:` or `https:` URI, as the browser will read it; else `null`. */
function webAddress(text: string): string | null {
	let url: URL;
	try {
		url = new URL(text);
	} catch {
		return null;
	}
	return url.protocol === 'http:' || url.protocol === 'https:' ? url.href : null;
}

function isScalar(value: unknown): boolean {
	return (
		value === null ||
		typeof value === 'string' ||
		typeof value === 'number' ||
		typeof value === 'boolean'
	);
}
