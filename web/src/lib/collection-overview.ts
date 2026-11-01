import type { JsonObject } from '$api/types';
import { clip } from './format';
import { isRecord, ownValue } from './json';
import {
	metadataView,
	type MetadataField,
	type MetadataValue,
	type MetadataView
} from './metadata';
import { propertySchema } from './schema-view';

/** The longest text in an Overview fact, including a field's label. */
export const OVERVIEW_TEXT_LENGTH = 160;

/** A few keywords or labels are enough to orient a reader; Metadata holds the rest. */
export const OVERVIEW_ITEMS = 4;

/**
 * Small discovery facts with known meanings. Unknown, missing, empty and malformed fields stay
 * on Metadata; a catalog's required fields are not a list of facts about the data. Labels and
 * formatting still come from its schema. Start and end retain their natural order.
 */
export function overviewMetadata(
	metadata: Readonly<Record<string, unknown>>,
	schema: JsonObject | null
): MetadataView {
	const keys = ['instrument', 'mission', 'start_time', 'end_time', 'keywords', 'labels'];
	const present = keys.filter((key) => useful(key, ownValue(metadata, key)));
	const selected = Object.fromEntries(present.map((key) => [key, ownValue(metadata, key)]));
	const selectedSchema: JsonObject = {
		type: 'object',
		properties: Object.fromEntries(present.map((key) => [key, propertySchema(schema, key) ?? {}]))
	};
	const view = metadataView(selected, selectedSchema);
	const fields = present.flatMap((key) => {
		const field = view.fields.find((candidate) => candidate.key === key);
		return field === undefined ? [] : [previewField(field)];
	});
	return {
		fields: fields.map(({ field }) => field),
		other: [],
		more: 0,
		shortened: view.shortened || fields.some(({ cut }) => cut)
	};
}

function useful(key: string, value: unknown): boolean {
	if (key === 'keywords') {
		return Array.isArray(value) && value.length > 0 && value.every(nonblank);
	}
	if (key === 'labels') {
		return isRecord(value) && Object.keys(value).length > 0 && Object.values(value).every(nonblank);
	}
	return nonblank(value);
}

function nonblank(value: unknown): value is string {
	return typeof value === 'string' && value.trim() !== '';
}

function previewField(field: MetadataField): { field: MetadataField; cut: boolean } {
	const label = previewText(field.label);
	const value = previewValue(field.value);
	return {
		field: { ...field, label: label.text, value: value.value },
		cut: label.cut || value.cut
	};
}

function previewValue(value: MetadataValue): { value: MetadataValue; cut: boolean } {
	if ('text' in value) {
		const text = previewText(value.text);
		return {
			value: text.cut ? { kind: 'text', text: text.text } : value,
			cut: text.cut
		};
	}
	if (value.kind === 'chips') {
		const items = value.items.slice(0, OVERVIEW_ITEMS);
		const more = value.more + value.items.length - items.length;
		return {
			value: {
				kind: 'chips',
				items: items.map((item) => previewText(item).text),
				more
			},
			cut: more > 0 || items.some((item) => previewText(item).cut)
		};
	}
	if (value.kind === 'labels') {
		const items = value.items.slice(0, OVERVIEW_ITEMS).map((item) => {
			const key = previewText(item.key);
			const text = previewText(item.value);
			return { key: key.text, value: text.text, filter: key.cut || text.cut ? null : item.filter };
		});
		const more = value.more + value.items.length - items.length;
		return {
			value: { kind: 'labels', items, more },
			cut:
				more > 0 ||
				value.items
					.slice(0, OVERVIEW_ITEMS)
					.some((item) => previewText(item.key).cut || previewText(item.value).cut)
		};
	}
	return { value, cut: false };
}

function previewText(text: string) {
	const shown = clip(text, OVERVIEW_TEXT_LENGTH);
	return shown.cut ? clip(text, OVERVIEW_TEXT_LENGTH - 1) : shown;
}
