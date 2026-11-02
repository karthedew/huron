import type { JsonObject, JsonValue } from '$api/types';

/**
 * Narrowing of JSON values the API sent, for code on both sides: schema documents, audit
 * details and metadata are typed as JSON (or as unknown values by key) and read by checking
 * each value.
 */
export function isJsonObject(value: JsonValue | undefined): value is JsonObject {
	return isRecord(value);
}

/** Whether a value is an object that is no array: a JSON object, or one typed loosely. */
export function isRecord(value: unknown): value is Readonly<Record<string, unknown>> {
	return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/** The own property `key` of an object, if it is a string. */
export function stringField(object: Readonly<Record<string, unknown>>, key: string): string | null {
	const value = ownValue(object, key);
	return typeof value === 'string' ? value : null;
}

/** The own property `key` of an object, if it is a finite number. */
export function numberField(object: Readonly<Record<string, unknown>>, key: string): number | null {
	const value = ownValue(object, key);
	return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

/** The own property `key` of an object, if it is a boolean. */
export function booleanField(
	object: Readonly<Record<string, unknown>>,
	key: string
): boolean | null {
	const value = ownValue(object, key);
	return typeof value === 'boolean' ? value : null;
}

/** The own property `key` of an object; inherited properties never count. */
export function ownValue<T>(object: Readonly<Record<string, T>>, key: string): T | undefined {
	return Object.hasOwn(object, key) ? object[key] : undefined;
}

/** Whether a value is JSON all the way down: what `JSON.parse` can produce. */
export function isJsonValue(value: unknown): value is JsonValue {
	if (value === null || typeof value === 'string' || typeof value === 'boolean') return true;
	if (typeof value === 'number') return Number.isFinite(value);
	if (Array.isArray(value)) return value.every(isJsonValue);
	return typeof value === 'object' && Object.values(value).every(isJsonValue);
}

/**
 * Whether a value the API typed loosely (`Record<string, unknown>`, such as a schema override)
 * is a JSON object all the way down, which the schema helpers read.
 */
export function isJsonDocument(value: unknown): value is JsonObject {
	return isRecord(value) && isJsonValue(value);
}

/**
 * `JSON.parse`, keeping the digits of each integer past 2^53, which it rounds to the nearest
 * number: a schema may bound an int64 field by 9223372036854775807, and the API keeps those
 * digits exactly. The values are those of `JSON.parse`; `integerDigits` and `exactJson` read the
 * digits. Throws on text that is not JSON, as `JSON.parse` does.
 */
export function parseExactly(text: string): JsonValue {
	// JSON.parse only ever produces JSON values, so the declared type is exact. The reviver
	// returns each value as it is; text without such a long run of digits needs none.
	const value: JsonValue = LONG_DIGITS.test(text)
		? JSON.parse(text, keepIntegerDigits)
		: JSON.parse(text);
	return value;
}

/**
 * The digits `parseExactly` kept for the integer at `holder[key]` (an array's key is its index),
 * or `null` when a number holds it exactly.
 */
export function integerDigits(holder: object, key: string): string | null {
	return integerDigitsOf.get(holder)?.get(key) ?? null;
}

/**
 * Whether a value holds a number that may be an integer `JSON.parse` rounded: one past 2^53,
 * whose digits only `parseExactly` keeps. Walks the value without recursion, however deep it
 * nests.
 */
export function hasInexactIntegers(value: unknown): boolean {
	const stack: unknown[] = [value];
	while (stack.length > 0) {
		const next = stack.pop();
		if (typeof next === 'number') {
			if (Number.isInteger(next) && !Number.isSafeInteger(next)) return true;
		} else if (Array.isArray(next)) {
			// One at a time: spreading an array of many thousands of items overflows the call stack.
			for (const item of next) stack.push(item);
		} else if (isRecord(next)) {
			for (const item of Object.values(next)) stack.push(item);
		}
	}
	return false;
}

/** `JSON.stringify`, writing each integer `parseExactly` kept with its own digits. */
export function exactJson(value: JsonValue, indent?: number): string {
	return JSON.stringify(value, writeIntegerDigits, indent);
}

/**
 * The digits `parseExactly` kept, by the object or array holding each integer and its key
 * there. A side table leaves the parsed values plain JSON for every other reader; a copy of an
 * object has no entries.
 */
const integerDigitsOf = new WeakMap<object, Map<string, string>>();

/** The fewest digits an integer a number cannot hold may have: 2^53 + 1 has 16. */
const LONG_DIGITS = /\d{16}/;
/** A JSON number written as an integer, without fraction or exponent. */
const INTEGER = /^-?\d+$/;

function keepIntegerDigits(
	this: unknown,
	key: string,
	value: unknown,
	context?: { source?: string }
): unknown {
	const source = context?.source;
	if (
		typeof value === 'number' &&
		!Number.isSafeInteger(value) &&
		source !== undefined &&
		INTEGER.test(source) &&
		typeof this === 'object' &&
		this !== null
	) {
		const digits = integerDigitsOf.get(this) ?? new Map<string, string>();
		digits.set(key, source);
		integerDigitsOf.set(this, digits);
	}
	return value;
}

function writeIntegerDigits(this: unknown, key: string, value: unknown): unknown {
	if (typeof value !== 'number' || typeof this !== 'object' || this === null) return value;
	const digits = integerDigits(this, key);
	return digits === null ? value : JSON.rawJSON(digits);
}
