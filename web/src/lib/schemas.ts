import type { SchemaEntry } from '$api/types';
import { shortened } from './format';
import { SCHEMA_TEXT_LENGTH } from './schema-view';

/** A registry version without its authored document, safe to send as page data. */
export interface SchemaSummary {
	id: string;
	name: string;
	version: number;
	organizationId: string | null;
	extendsId: string | null;
	createdAt: string;
	createdBy: string;
}

/** The bounded identifying fields of a registry version; its document stays on the server. */
export function schemaSummary(entry: SchemaEntry): SchemaSummary {
	return {
		id: entry.id,
		name: shortened(entry.name, SCHEMA_TEXT_LENGTH),
		version: entry.version,
		organizationId: entry.organization_id,
		extendsId: entry.extends_id,
		createdAt: shortened(entry.created_at, SCHEMA_TEXT_LENGTH),
		createdBy: shortened(entry.created_by, SCHEMA_TEXT_LENGTH)
	};
}
