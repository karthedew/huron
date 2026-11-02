import { readFileSync } from 'node:fs';
import type { JsonObject, JsonValue } from '$api/types';
import { isJsonObject } from '$lib/json';

/** The platform schema every catalog starts from, as the API ships it (for tests run in node). */
export function huronBase(): JsonObject {
	const url = new URL('../../../../src/huron/schema/documents/huron-base-v1.json', import.meta.url);
	// JSON.parse only ever produces JSON values, so the declared type is exact.
	const document: JsonValue = JSON.parse(readFileSync(url, 'utf8'));
	if (!isJsonObject(document)) throw new Error('huron-base is not an object');
	return document;
}

/** huron-base with the organization schema of space-weather composed on top. */
export function spaceWeather(): JsonObject {
	const base = huronBase();
	const properties = base.properties;
	if (!isJsonObject(properties)) throw new Error('huron-base has no properties');
	return {
		...base,
		title: 'Space weather metadata',
		required: ['title', 'description', 'mission'],
		properties: { ...properties, mission: { type: 'string', title: 'Mission', minLength: 1 } }
	};
}
