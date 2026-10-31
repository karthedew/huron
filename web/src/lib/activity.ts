/**
 * Audit entries as the activity pages show them: a label per action of the closed vocabulary
 * (`AUDIT_ACTIONS`, from `src/huron/core/lake/audit/models.py`) and a summary of the detail each
 * action records. The detail keys follow where the core records each action.
 */
import { isAuditAction, isRole, type AuditAction, type AuditEntry } from '$api/types';
import { countLabel, formatCount, formatTimestamp, shortId } from './format';
import { booleanField, numberField, ownValue, stringField } from './json';
import { match as isDottedPath } from '../params/dotted';
import { ROLE_NAMES } from './roles';

/** Human labels of the audit actions. */
export const ACTION_LABELS: Readonly<Record<AuditAction, string>> = {
	'platform.grant': 'Granted a platform role',
	'platform.revoke': 'Revoked a platform role',
	'organization.create': 'Created the organization',
	'organization.delete': 'Deleted the organization',
	'organization.grant': 'Granted an organization role',
	'organization.revoke': 'Revoked an organization role',
	'catalog.create': 'Created the catalog',
	'catalog.delete': 'Deleted the catalog',
	'catalog.grant': 'Granted a catalog role',
	'catalog.revoke': 'Revoked a catalog role',
	'catalog.assign_schema': 'Assigned schema',
	'namespace.create': 'Created a namespace',
	'namespace.delete': 'Deleted a namespace',
	'namespace.configure': 'Configured a namespace',
	'schema.publish': 'Published a schema',
	'collection.create': 'Created a collection',
	'collection.update_metadata': 'Updated metadata',
	'collection.set_schema_override': 'Changed the schema override',
	'collection.activate': 'Activated',
	'collection.mark_incomplete': 'Marked incomplete',
	'collection.mark_active': 'Marked active',
	'collection.commit': 'Committed files',
	'collection.delete': 'Deleted a collection',
	'signing_key.rotate': 'Rotated the signing key'
};

/** A registry entry's name and version, to name a schema id. */
export interface SchemaName {
	name: string;
	version: number;
}

/** What an entry is about, where the page can link to it. */
export type ActivityTarget =
	| { kind: 'namespace'; path: string; text: string }
	| { kind: 'collection'; identifier: string; text: string }
	/** A collection the entry names only by id: `/collections/<id>` finds it. */
	| { kind: 'collection-id'; id: string; text: string };

export interface ActivityRow {
	/** Unique within a page of entries. */
	key: string;
	/** The ISO time of the entry. */
	at: string;
	actor: string;
	action: string;
	label: string;
	/** What the detail says, as a short phrase; empty when it says nothing more. */
	summary: string;
	target: ActivityTarget | null;
	/** The detail as the API recorded it, as indented JSON. */
	detail: string;
}

/** An entry's detail: keys by action, values as the API recorded them. */
type Detail = AuditEntry['detail'];

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Actions whose object no longer exists: the summary names it, without a link. */
const GONE: ReadonlySet<string> = new Set(['collection.delete', 'namespace.delete']);

/**
 * The schema ids the summaries name (a catalog's schema on create and assignment), once each,
 * in order of appearance; only well-formed ids, so a lookup never builds a bad path.
 */
export function activitySchemaIds(entries: readonly AuditEntry[]): string[] {
	const ids = new Set<string>();
	for (const { action, detail } of entries) {
		if (action !== 'catalog.create' && action !== 'catalog.assign_schema') continue;
		for (const key of ['schema_id', 'previous']) {
			const id = stringField(detail, key);
			if (id !== null && UUID.test(id)) ids.add(id.toLowerCase());
		}
	}
	return [...ids];
}

/** The rows of a page of entries; `schemas` names the schema ids that could be looked up. */
export function activityRows(
	entries: readonly AuditEntry[],
	schemas: Readonly<Record<string, SchemaName>>
): ActivityRow[] {
	return entries.map((entry, index) => ({
		key: entry.id === null ? `entry-${index}` : String(entry.id),
		at: entry.at,
		actor: entry.actor,
		action: entry.action,
		label: isAuditAction(entry.action) ? ACTION_LABELS[entry.action] : entry.action,
		summary: summary(entry, schemas),
		target: target(entry),
		detail: JSON.stringify(entry.detail, null, 2)
	}));
}

/**
 * An entry in one line: what happened, to what, and when. A page holds many entries with the same
 * label, so controls of an entry (its details) carry this to tell them apart.
 */
export function activityName(row: ActivityRow): string {
	return join(', ', [
		join(' ', [row.label, row.summary]),
		row.target?.text ?? null,
		formatTimestamp(row.at)
	]);
}

function summary(entry: AuditEntry, schemas: Readonly<Record<string, SchemaName>>): string {
	const { detail } = entry;
	const schema = (key: string) => schemaText(stringField(detail, key), schemas);
	switch (entry.action) {
		case 'platform.grant':
		case 'organization.grant':
		case 'catalog.grant':
			return roleChange(detail, 'to');
		case 'platform.revoke':
		case 'organization.revoke':
		case 'catalog.revoke':
			return roleChange(detail, 'from');
		case 'organization.create':
		case 'organization.delete':
		case 'catalog.delete':
			return stringField(detail, 'name') ?? '';
		case 'catalog.create': {
			const created = schema('schema_id');
			return join(' ', [
				stringField(detail, 'name'),
				created === null ? null : `with schema ${created}`
			]);
		}
		case 'catalog.assign_schema': {
			const previous = schema('previous');
			return join(' ', [schema('schema_id'), previous === null ? null : `(was ${previous})`]);
		}
		case 'namespace.delete':
			return stringField(detail, 'path') ?? '';
		case 'namespace.configure': {
			const allowed = booleanField(detail, 'collections_allowed');
			if (allowed === null) return '';
			return allowed ? 'Now holds collections' : 'Now structure only';
		}
		case 'schema.publish':
			return schemaName(stringField(detail, 'name'), numberField(detail, 'version')) ?? '';
		case 'collection.delete':
			return stringField(detail, 'identifier') ?? '';
		case 'collection.update_metadata':
		case 'collection.activate':
		case 'collection.mark_incomplete':
		case 'collection.mark_active':
			return aside([revision(detail)]);
		case 'collection.set_schema_override': {
			const cleared = booleanField(detail, 'cleared');
			const change = cleared === null ? null : cleared ? 'removed' : 'set';
			return aside([change, revision(detail)]);
		}
		case 'collection.commit':
			return commitSummary(detail);
		case 'signing_key.rotate':
			return rotation(detail);
		default:
			return '';
	}
}

/** What an entry links to; only names that make a well-formed address are linked. */
function target(entry: AuditEntry): ActivityTarget | null {
	if (GONE.has(entry.action)) return null;
	if (entry.object_type === 'namespace') {
		const path = stringField(entry.detail, 'path');
		return path !== null && isDottedPath(path) ? { kind: 'namespace', path, text: path } : null;
	}
	if (entry.object_type !== 'collection') return null;
	const identifier = stringField(entry.detail, 'identifier');
	if (identifier !== null && isCollectionIdentifier(identifier)) {
		return { kind: 'collection', identifier, text: identifier };
	}
	if (entry.object_id === null || !UUID.test(entry.object_id)) return null;
	return {
		kind: 'collection-id',
		id: entry.object_id,
		text: `collection ${shortId(entry.object_id)}`
	};
}

/** `catalog.namespace.path.name`: a catalog, at least one namespace, then the name. */
function isCollectionIdentifier(identifier: string): boolean {
	return isDottedPath(identifier) && identifier.split('.').length >= 3;
}

function roleChange(detail: Detail, preposition: 'to' | 'from'): string {
	const role = stringField(detail, 'role');
	const group = stringField(detail, 'ldap_group');
	const name = role === null ? null : isRole(role) ? ROLE_NAMES[role] : role;
	return join(' ', [name, group === null ? null : `${preposition} ${group}`]);
}

function schemaText(
	id: string | null,
	schemas: Readonly<Record<string, SchemaName>>
): string | null {
	if (id === null) return null;
	const known = Object.hasOwn(schemas, id.toLowerCase()) ? schemas[id.toLowerCase()] : undefined;
	return known === undefined ? `schema ${shortId(id)}` : `${known.name} v${known.version}`;
}

function schemaName(name: string | null, version: number | null): string | null {
	if (name === null) return null;
	return version === null ? name : `${name} v${version}`;
}

/** The collection's record revision after the change; not a version of its data. */
function revision(detail: Detail): string | null {
	const version = numberField(detail, 'version');
	return version === null ? null : `revision ${formatCount(version)}`;
}

function commitSummary(detail: Detail): string {
	const adds = numberField(detail, 'adds');
	const removes = numberField(detail, 'removes');
	const host = stringField(detail, 'host');
	const message = ownValue(detail, 'message');
	const changes =
		adds === null || removes === null
			? null
			: `${formatCount(adds)} added, ${formatCount(removes)} removed`;
	const said =
		typeof message === 'string' && message !== ''
			? `“${message}”`
			: message === null || message === ''
				? 'No message'
				: null;
	return join(' · ', [changes, host === null ? null : `from ${host}`, revision(detail), said]);
}

function rotation(detail: Detail): string {
	const kid = stringField(detail, 'kid');
	const retired = ownValue(detail, 'retired');
	const count = Array.isArray(retired) ? retired.length : 0;
	return join(' · ', [
		kid === null ? null : `Key ${kid}`,
		count === 0 ? null : `retired ${countLabel(count, 'key')}`
	]);
}

/** Parts that complete a label in parentheses: "Activated (revision 2)". */
function aside(parts: ReadonlyArray<string | null>): string {
	const text = join(', ', parts);
	return text === '' ? '' : `(${text})`;
}

function join(separator: string, parts: ReadonlyArray<string | null>): string {
	return parts.filter((part): part is string => part !== null && part !== '').join(separator);
}
