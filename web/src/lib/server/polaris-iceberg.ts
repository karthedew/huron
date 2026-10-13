import type {
	PolarisIcebergField,
	PolarisIcebergFieldType,
	PolarisIcebergRef,
	PolarisIcebergSchema,
	PolarisIcebergSnapshot,
	PolarisIcebergTable
} from '$api/types';

const SNAPSHOT_KEYS = new Set(['snapshot-id', 'parent-snapshot-id', 'current-snapshot-id']);

/** Preserve int64 snapshot identities while leaving text values and ordinary numbers intact. */
export function parseIcebergResponseJson(content: string): unknown {
	const pieces: string[] = [];
	let copied = 0;
	for (let position = 0; position < content.length; position += 1) {
		if (content[position] !== '"') continue;
		const start = position;
		position += 1;
		while (position < content.length && content[position] !== '"') {
			position += content[position] === '\\' ? 2 : 1;
		}
		const name: unknown = JSON.parse(content.slice(start, position + 1));
		let colon = position + 1;
		while (/\s/.test(content[colon] ?? '') && colon < content.length) colon += 1;
		if (content[colon] !== ':' || typeof name !== 'string' || !SNAPSHOT_KEYS.has(name)) continue;
		let valueStart = colon + 1;
		while (/\s/.test(content[valueStart] ?? '') && valueStart < content.length) valueStart += 1;
		const integer = /^-?(?:0|[1-9]\d*)(?=\s*[,}])/.exec(content.slice(valueStart));
		if (!integer) continue;
		pieces.push(content.slice(copied, valueStart), JSON.stringify(integer[0]));
		copied = valueStart + integer[0].length;
		position = copied - 1;
	}
	pieces.push(content.slice(copied));
	const value: unknown = JSON.parse(pieces.join(''));
	return value;
}

function record(value: unknown): Record<string, unknown> {
	if (typeof value !== 'object' || value === null || Array.isArray(value))
		throw new TypeError('Invalid Iceberg metadata object.');
	return Object.fromEntries(Object.entries(value));
}

function text(value: unknown): string {
	if (typeof value !== 'string') throw new TypeError('Invalid Iceberg metadata text.');
	return value;
}

function number(value: unknown): number {
	if (typeof value !== 'number' || !Number.isSafeInteger(value))
		throw new TypeError('Invalid or unsafe Iceberg metadata integer.');
	return value;
}

function boolean(value: unknown): boolean {
	if (typeof value !== 'boolean') throw new TypeError('Invalid Iceberg metadata flag.');
	return value;
}

function entries<T>(value: unknown, decode: (value: unknown) => T): T[] {
	if (!Array.isArray(value)) throw new TypeError('Invalid Iceberg metadata list.');
	return value.map(decode);
}

function snapshotId(value: unknown): string {
	if (typeof value === 'string' && /^-?\d+$/.test(value)) return value;
	return String(number(value));
}

/** Storage locators carry no userinfo or signed URL parameters into the browser. */
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

const SAFE_TABLE_PROPERTIES = new Set([
	'comment',
	'description',
	'owner',
	'huron.layer',
	'format-version',
	'write.format.default',
	'write.target-file-size-bytes',
	'write.parquet.compression-codec',
	'write.metadata.compression-codec',
	'read.split.target-size',
	'commit.retry.num-retries',
	'gc.enabled',
	'source.dataset',
	'source.doi',
	'source.url',
	'source.title'
]);
const SAFE_SNAPSHOT_SUMMARY = new Set([
	'operation',
	'added-records',
	'deleted-records',
	'total-records',
	'added-data-files',
	'deleted-data-files',
	'total-data-files',
	'added-delete-files',
	'removed-delete-files',
	'total-delete-files',
	'total-position-deletes',
	'total-equality-deletes',
	'total-files-size',
	'added-files-size',
	'removed-files-size',
	'changed-partition-count'
]);

function safeProperties(value: unknown, allowed: Set<string>): Record<string, string> {
	if (value === undefined || value === null) return {};
	return Object.fromEntries(
		Object.entries(record(value))
			.filter(([key]) => allowed.has(key))
			.map(([key, value]) => [key, key === 'source.url' ? location(value) : text(value)])
	);
}

function field(value: unknown, depth = 0): PolarisIcebergField {
	const entry = record(value);
	return {
		id: number(entry.id),
		name: text(entry.name),
		required: boolean(entry.required),
		type: fieldType(entry.type, depth + 1),
		...(typeof entry.doc === 'string' ? { doc: entry.doc } : {})
	};
}

function fieldType(value: unknown, depth: number): PolarisIcebergFieldType {
	if (depth > 32) throw new TypeError('Iceberg schema nesting is too deep.');
	if (typeof value === 'string') return value;
	const entry = record(value);
	switch (entry.type) {
		case 'struct':
			return { type: 'struct', fields: entries(entry.fields, (value) => field(value, depth)) };
		case 'list':
			return {
				type: 'list',
				elementId: number(entry['element-id']),
				elementRequired: boolean(entry['element-required']),
				element: fieldType(entry.element, depth + 1)
			};
		case 'map':
			return {
				type: 'map',
				keyId: number(entry['key-id']),
				key: fieldType(entry.key, depth + 1),
				valueId: number(entry['value-id']),
				valueRequired: boolean(entry['value-required']),
				value: fieldType(entry.value, depth + 1)
			};
		default:
			throw new TypeError('Unsupported Iceberg schema type.');
	}
}

function schema(value: unknown): PolarisIcebergSchema {
	const entry = record(value);
	return {
		schemaId: number(entry['schema-id']),
		identifierFieldIds: entries(entry['identifier-field-ids'] ?? [], number),
		fields: entries(entry.fields, (value) => field(value))
	};
}

function snapshot(value: unknown): PolarisIcebergSnapshot {
	const entry = record(value);
	return {
		snapshotId: snapshotId(entry['snapshot-id']),
		parentSnapshotId:
			entry['parent-snapshot-id'] === undefined ? null : snapshotId(entry['parent-snapshot-id']),
		timestampMs: number(entry['timestamp-ms']),
		schemaId: entry['schema-id'] === undefined ? null : number(entry['schema-id']),
		manifestList: entry['manifest-list'] === undefined ? null : location(entry['manifest-list']),
		summary: safeProperties(entry.summary, SAFE_SNAPSHOT_SUMMARY)
	};
}

function ref(value: unknown): PolarisIcebergRef {
	const entry = record(value);
	if (entry.type !== 'branch' && entry.type !== 'tag')
		throw new TypeError('Invalid Iceberg reference.');
	return {
		type: entry.type,
		snapshotId: snapshotId(entry['snapshot-id']),
		...(entry['min-snapshots-to-keep'] === undefined
			? {}
			: { minSnapshotsToKeep: number(entry['min-snapshots-to-keep']) }),
		...(entry['max-snapshot-age-ms'] === undefined
			? {}
			: { maxSnapshotAgeMs: number(entry['max-snapshot-age-ms']) }),
		...(entry['max-ref-age-ms'] === undefined
			? {}
			: { maxRefAgeMs: number(entry['max-ref-age-ms']) })
	};
}

/** Select table schemas and immutable history; never forward response FileIO or OAuth config. */
export function icebergTable(
	value: unknown,
	namespace: string[],
	name: string
): PolarisIcebergTable {
	const response = record(value);
	const metadata = record(response.metadata);
	return {
		format: 'iceberg',
		name,
		namespace,
		location: location(metadata.location),
		properties: safeProperties(metadata.properties, SAFE_TABLE_PROPERTIES),
		metadataLocation:
			response['metadata-location'] === undefined ? null : location(response['metadata-location']),
		tableUuid: typeof metadata['table-uuid'] === 'string' ? metadata['table-uuid'] : null,
		formatVersion: number(metadata['format-version']),
		currentSchemaId: number(metadata['current-schema-id']),
		currentSnapshotId:
			metadata['current-snapshot-id'] === undefined ||
			metadata['current-snapshot-id'] === null ||
			metadata['current-snapshot-id'] === '-1'
				? null
				: snapshotId(metadata['current-snapshot-id']),
		schemas: entries(metadata.schemas ?? [], schema),
		snapshots: entries(metadata.snapshots ?? [], snapshot),
		refs: Object.fromEntries(
			Object.entries(record(metadata.refs ?? {})).map(([name, value]) => [name, ref(value)])
		),
		snapshotLog: entries(metadata['snapshot-log'] ?? [], (value) => {
			const entry = record(value);
			return {
				timestampMs: number(entry['timestamp-ms']),
				snapshotId: snapshotId(entry['snapshot-id'])
			};
		}),
		metadataLog: entries(metadata['metadata-log'] ?? [], (value) => {
			const entry = record(value);
			return {
				timestampMs: number(entry['timestamp-ms']),
				metadataFile: location(entry['metadata-file'])
			};
		})
	};
}
