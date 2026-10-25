import type { PolarisProperties, PolarisGenericTable } from '$api/types';

function object(value: unknown): Record<string, unknown> {
	if (typeof value !== 'object' || value === null || Array.isArray(value))
		throw new TypeError('Invalid generic-table metadata object.');
	return Object.fromEntries(Object.entries(value));
}

function text(value: unknown): string {
	if (typeof value !== 'string') throw new TypeError('Invalid generic-table metadata text.');
	return value;
}

/** Locators expose their storage identity without userinfo, signatures or query credentials. */
function location(value: unknown): string {
	const input = text(value);
	try {
		const url = new URL(input);
		url.username = '';
		url.password = '';
		url.search = '';
		url.hash = '';
		return url.toString();
	} catch {
		return input.split(/[?#]/, 1)[0];
	}
}

const DISPLAY_PROPERTIES = new Set([
	'comment',
	'description',
	'owner',
	'huron.layer',
	'source.dataset',
	'source.doi',
	'source.url',
	'source.title',
	'source.sha256',
	'source.media-type'
]);

function safeProperties(value: unknown): PolarisProperties {
	if (value === undefined || value === null) return {};
	return Object.fromEntries(
		Object.entries(object(value))
			.filter(([key]) => DISPLAY_PROPERTIES.has(key))
			.map(([key, value]) => [key, key === 'source.url' ? location(value) : text(value)])
	);
}

/** Decode only registered asset metadata; never return storage-access-configs to a browser. */
export function genericTable(
	value: unknown,
	namespace: string[],
	name: string
): PolarisGenericTable {
	const table = object(object(value).table);
	if (text(table.name) !== name) throw new TypeError('Generic-table identity did not match.');
	return {
		name,
		namespace,
		format: 'generic',
		storageFormat: text(table.format),
		location: table['base-location'] == null ? null : location(table['base-location']),
		doc: table.doc == null ? '' : text(table.doc),
		properties: safeProperties(table.properties)
	};
}
