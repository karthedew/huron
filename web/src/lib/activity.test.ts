import { describe, expect, it } from 'vitest';
import { AUDIT_ACTIONS, type AuditEntry, type JsonObject } from '$api/types';
import { auditFixture } from '$lib/testing/api-fixtures';
import {
	ACTION_LABELS,
	activityName,
	activityRows,
	activitySchemaIds,
	type SchemaName
} from './activity';

const COLLECTION_ID = '0192f2a4-0000-7000-8000-000000000401';
const BASE = '0192f2a4-0000-7000-8000-000000000201';
const SPACE_WEATHER = '0192f2a4-0000-7000-8000-000000000202';
const SCHEMAS: Record<string, SchemaName> = {
	[BASE]: { name: 'huron-base', version: 1 },
	[SPACE_WEATHER]: { name: 'space-weather', version: 1 }
};

function entry(action: string, objectType: string, detail: JsonObject): AuditEntry {
	return auditFixture({ action, object_type: objectType, detail });
}

function row(action: string, objectType: string, detail: JsonObject) {
	const [only] = activityRows([entry(action, objectType, detail)], SCHEMAS);
	return only;
}

describe('ACTION_LABELS', () => {
	it('labels every action of the closed vocabulary', () => {
		expect(Object.keys(ACTION_LABELS).sort()).toEqual([...AUDIT_ACTIONS].sort());
		for (const label of Object.values(ACTION_LABELS)) expect(label).toMatch(/^[A-Z]/);
	});
});

/** One case per action: the action, its object type, a detail, the label and the summary. */
const CASES: ReadonlyArray<readonly [string, string, JsonObject, string, string]> = [
	[
		'platform.grant',
		'platform',
		{ role: 'platform_admin', ldap_group: 'huron-platform-admins' },
		'Granted a platform role',
		'Platform administrator to huron-platform-admins'
	],
	[
		'platform.revoke',
		'platform',
		{ role: 'platform_admin', ldap_group: 'old-admins' },
		'Revoked a platform role',
		'Platform administrator from old-admins'
	],
	['organization.create', 'organization', { name: 'helio' }, 'Created the organization', 'helio'],
	['organization.delete', 'organization', { name: 'old' }, 'Deleted the organization', 'old'],
	[
		'organization.grant',
		'organization',
		{ role: 'org_admin', ldap_group: 'helio-org-admins' },
		'Granted an organization role',
		'Organization administrator to helio-org-admins'
	],
	[
		'organization.revoke',
		'organization',
		{ role: 'org_admin', ldap_group: 'helio-org-admins' },
		'Revoked an organization role',
		'Organization administrator from helio-org-admins'
	],
	[
		'catalog.create',
		'catalog',
		{ name: 'heliophysics', schema_id: BASE },
		'Created the catalog',
		'heliophysics with schema huron-base v1'
	],
	['catalog.delete', 'catalog', { name: 'old' }, 'Deleted the catalog', 'old'],
	[
		'catalog.grant',
		'catalog',
		{ role: 'reader', ldap_group: 'helio-readers' },
		'Granted a catalog role',
		'Reader to helio-readers'
	],
	[
		'catalog.revoke',
		'catalog',
		{ role: 'contributor', ldap_group: 'helio-contributors' },
		'Revoked a catalog role',
		'Contributor from helio-contributors'
	],
	[
		'catalog.assign_schema',
		'catalog',
		{ schema_id: SPACE_WEATHER, previous: BASE },
		'Assigned schema',
		'space-weather v1 (was huron-base v1)'
	],
	['namespace.create', 'namespace', { path: 'solar-wind.ace' }, 'Created a namespace', ''],
	['namespace.delete', 'namespace', { path: 'old.ns' }, 'Deleted a namespace', 'old.ns'],
	[
		'namespace.configure',
		'namespace',
		{ path: 'fields', collections_allowed: true },
		'Configured a namespace',
		'Now holds collections'
	],
	[
		'schema.publish',
		'schema',
		{ name: 'space-weather', version: 2 },
		'Published a schema',
		'space-weather v2'
	],
	[
		'collection.create',
		'collection',
		{ identifier: 'heliophysics.fields.run001' },
		'Created a collection',
		''
	],
	['collection.update_metadata', 'collection', { version: 5 }, 'Updated metadata', '(revision 5)'],
	[
		'collection.set_schema_override',
		'collection',
		{ version: 6, cleared: false },
		'Changed the schema override',
		'(set, revision 6)'
	],
	['collection.activate', 'collection', { version: 2 }, 'Activated', '(revision 2)'],
	['collection.mark_incomplete', 'collection', { version: 3 }, 'Marked incomplete', '(revision 3)'],
	['collection.mark_active', 'collection', { version: 4 }, 'Marked active', '(revision 4)'],
	[
		'collection.commit',
		'collection',
		{ adds: 3, removes: 1, host: 'dtn02.example.org', message: 'Replace the README', version: 4 },
		'Committed files',
		'3 added, 1 removed · from dtn02.example.org · revision 4 · “Replace the README”'
	],
	[
		'collection.delete',
		'collection',
		{ identifier: 'heliophysics.fields.run099' },
		'Deleted a collection',
		'heliophysics.fields.run099'
	],
	[
		'signing_key.rotate',
		'signing_key',
		{ kid: 'k2', retired: ['k1'] },
		'Rotated the signing key',
		'Key k2 · retired 1 key'
	]
];

describe('activityRows', () => {
	it('has a case for every action of the vocabulary', () => {
		expect(CASES.map(([action]) => action).sort()).toEqual([...AUDIT_ACTIONS].sort());
	});

	it.each(CASES)('summarizes %s', (action, objectType, detail, label, summary) => {
		const shown = row(action, objectType, detail);
		expect(shown.label).toBe(label);
		expect(shown.summary).toBe(summary);
	});

	it('keeps the time, the actor and the raw detail', () => {
		const shown = row('collection.activate', 'collection', { version: 2 });
		expect(shown).toMatchObject({
			key: '7',
			at: '2026-10-03T09:00:00+00:00',
			actor: 'sub-dave',
			action: 'collection.activate'
		});
		expect(JSON.parse(shown.detail)).toEqual({ version: 2 });
		expect(shown.detail).toBe('{\n  "version": 2\n}');
	});

	it('links collections by identifier, else by id', () => {
		expect(
			row('collection.create', 'collection', { identifier: 'heliophysics.fields.run001' }).target
		).toEqual({
			kind: 'collection',
			identifier: 'heliophysics.fields.run001',
			text: 'heliophysics.fields.run001'
		});
		expect(row('collection.commit', 'collection', { adds: 1 }).target).toEqual({
			kind: 'collection-id',
			id: COLLECTION_ID,
			text: 'collection 000000000401'
		});
		const [anonymous] = activityRows(
			[auditFixture({ action: 'collection.activate', object_id: null, detail: {} })],
			{}
		);
		expect(anonymous.target).toBeNull();
	});

	it('links only names that make a well-formed address', () => {
		for (const identifier of ['', 'heliophysics', 'heliophysics.run001', '.a.b', 'a..b', 'A.b.c']) {
			expect(row('collection.create', 'collection', { identifier }).target, identifier).toEqual({
				kind: 'collection-id',
				id: COLLECTION_ID,
				text: 'collection 000000000401'
			});
		}
		const [unknown] = activityRows(
			[auditFixture({ action: 'collection.commit', object_id: 'not-a-uuid', detail: {} })],
			{}
		);
		expect(unknown.target).toBeNull();
		for (const path of ['', 'solar-wind..ace', '/etc', 'Solar']) {
			expect(row('namespace.create', 'namespace', { path }).target, path).toBeNull();
		}
	});

	it('links namespaces that still exist and names deleted things without a link', () => {
		expect(row('namespace.create', 'namespace', { path: 'solar-wind.ace' }).target).toEqual({
			kind: 'namespace',
			path: 'solar-wind.ace',
			text: 'solar-wind.ace'
		});
		expect(row('namespace.delete', 'namespace', { path: 'old' }).target).toBeNull();
		expect(row('collection.delete', 'collection', { identifier: 'h.a.b' }).target).toBeNull();
		expect(row('catalog.grant', 'catalog', { role: 'reader' }).target).toBeNull();
	});

	it('names schemas that could not be looked up by their short id', () => {
		const [shown] = activityRows(
			[entry('catalog.assign_schema', 'catalog', { schema_id: SPACE_WEATHER, previous: BASE })],
			{ [BASE]: { name: 'huron-base', version: 1 } }
		);
		expect(shown.summary).toBe('schema 000000000202 (was huron-base v1)');
	});

	it('says what a commit without a message changed', () => {
		const shown = row('collection.commit', 'collection', {
			adds: 120,
			removes: 0,
			host: 'psp-dtn.example.org',
			message: null,
			version: 3
		});
		expect(shown.summary).toBe(
			'120 added, 0 removed · from psp-dtn.example.org · revision 3 · No message'
		);
	});

	it('says so of an empty commit message too, which other API clients than the CLI may write', () => {
		const shown = row('collection.commit', 'collection', {
			adds: 1,
			removes: 0,
			host: 'h',
			message: '',
			version: 2
		});
		expect(shown.summary).toBe('1 added, 0 removed · from h · revision 2 · No message');
	});

	it('reads what a detail holds and skips what it lacks or mistypes', () => {
		expect(row('collection.commit', 'collection', {}).summary).toBe('');
		expect(row('catalog.assign_schema', 'catalog', { schema_id: 7 }).summary).toBe('');
		expect(row('catalog.grant', 'catalog', { role: 'owner', ldap_group: 'g' }).summary).toBe(
			'owner to g'
		);
		expect(row('namespace.configure', 'namespace', { path: 'x' }).summary).toBe('');
		expect(
			row('namespace.configure', 'namespace', { path: 'x', collections_allowed: false }).summary
		).toBe('Now structure only');
		expect(row('collection.set_schema_override', 'collection', { cleared: true }).summary).toBe(
			'(removed)'
		);
		expect(row('collection.activate', 'collection', {}).summary).toBe('');
		expect(row('signing_key.rotate', 'signing_key', { kid: 'k3', retired: [] }).summary).toBe(
			'Key k3'
		);
		expect(row('schema.publish', 'schema', { name: 'x' }).summary).toBe('x');
	});

	it('shows an action outside the vocabulary by its name', () => {
		const shown = row('collection.archive', 'collection', { version: 1 });
		expect(shown.label).toBe('collection.archive');
		expect(shown.summary).toBe('');
	});

	it('keys entries the store has not numbered by their place', () => {
		const rows = activityRows([auditFixture({ id: null }), auditFixture({ id: null })], {});
		expect(rows.map(({ key }) => key)).toEqual(['entry-0', 'entry-1']);
	});
});

describe('activityName', () => {
	it('says what happened, to what and when, in one line', () => {
		expect(
			activityName(row('collection.create', 'collection', { identifier: 'h.fields.run001' }))
		).toBe('Created a collection, h.fields.run001, 2026-10-03 09:00 UTC');
		expect(activityName(row('collection.activate', 'collection', { version: 2 }))).toBe(
			'Activated (revision 2), collection 000000000401, 2026-10-03 09:00 UTC'
		);
		expect(activityName(row('catalog.grant', 'catalog', { role: 'reader' }))).toBe(
			'Granted a catalog role Reader, 2026-10-03 09:00 UTC'
		);
	});

	it('tells apart entries of one label on the same collection', () => {
		const [first, second] = activityRows(
			[
				entry('collection.update_metadata', 'collection', { version: 3 }),
				entry('collection.update_metadata', 'collection', { version: 4 })
			],
			SCHEMAS
		);
		expect(activityName(first)).not.toBe(activityName(second));
	});
});

describe('activitySchemaIds', () => {
	it('collects the schema ids of catalog entries once each', () => {
		const entries = [
			entry('catalog.create', 'catalog', { name: 'h', schema_id: BASE }),
			entry('catalog.assign_schema', 'catalog', { schema_id: SPACE_WEATHER, previous: BASE }),
			entry('catalog.assign_schema', 'catalog', {
				schema_id: BASE,
				previous: SPACE_WEATHER.toUpperCase()
			})
		];
		expect(activitySchemaIds(entries)).toEqual([BASE, SPACE_WEATHER]);
	});

	it('ignores other actions and ids that are not UUIDs', () => {
		expect(
			activitySchemaIds([
				entry('collection.commit', 'collection', { schema_id: BASE }),
				entry('catalog.assign_schema', 'catalog', { schema_id: '../x', previous: 3 })
			])
		).toEqual([]);
	});
});
