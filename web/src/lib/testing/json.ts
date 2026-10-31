import type { JsonObject, JsonValue } from '$api/types';
import { isJsonObject } from '$lib/json';

/**
 * A JSON object as `JSON.parse` reads an API answer: a `__proto__` key stays a property of its
 * own, which object literals in tests cannot write without computed keys.
 */
export function parsedObject(text: string): JsonObject {
	// JSON.parse only ever produces JSON values, so the declared type is exact.
	const value: JsonValue = JSON.parse(text);
	if (!isJsonObject(value)) throw new Error('not a JSON object');
	return value;
}
