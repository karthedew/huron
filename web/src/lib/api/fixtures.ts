/**
 * SYNTHETIC FIXTURES — DELETED AT P1. Only `client.ts` may import this file.
 *
 * Deliberately obvious placeholders: enough shape to prove every layout and state
 * renders (populated, empty, stale, unavailable index), and not one row more. This is
 * not a demo dataset. See ./README.md.
 */

import type {
	ApiKey,
	Dataset,
	LayerAvailability,
	Organization,
	OrganizationMember,
	PermissionGrant,
	Project,
	SearchResults,
	WhoAmI
} from './types';

const layers = (raw: string, bronze: string, silver: string, gold: string): LayerAvailability => {
	const parse = (v: string) =>
		v === '+' ? ({ state: 'present' } as const) : ({ state: 'absent' } as const);
	return { raw: parse(raw), bronze: parse(bronze), silver: parse(silver), gold: parse(gold) };
};

export const organizations: Organization[] = [
	{
		slug: 'example-org',
		name: 'Example Organization',
		description: 'Placeholder organization — fixture data, not a real tenant.',
		projectCount: 2
	},
	{
		slug: 'second-org',
		name: 'Second Organization',
		description: 'Placeholder organization used to prove multi-org browse renders.',
		projectCount: 0
	}
];

export const projects: Project[] = [
	{
		slug: 'example-study',
		orgSlug: 'example-org',
		name: 'Example Study',
		description: 'Placeholder project.',
		datasetCount: 2,
		quota: {
			rawUsed: 412_000_000_000,
			rawLimit: 1_000_000_000_000,
			objectUsed: 88_000_000_000,
			objectLimit: 500_000_000_000
		}
	},
	{
		slug: 'empty-study',
		orgSlug: 'example-org',
		name: 'Empty Study',
		description: 'Placeholder project with no datasets — proves the empty state renders.',
		datasetCount: 0,
		quota: { rawUsed: 0, rawLimit: 1_000_000_000_000, objectUsed: 0, objectLimit: 500_000_000_000 }
	}
];

export const datasets: Dataset[] = [
	{
		slug: 'example-sweep',
		orgSlug: 'example-org',
		projectSlug: 'example-study',
		name: 'Example Sweep',
		description: 'Placeholder dataset with all four layers materialized.',
		lifecycle: 'ACTIVE',
		classification: 'unclassified',
		profile: 'example-profile@1',
		tags: ['placeholder', 'fixture'],
		layers: layers('+', '+', '+', '+')
	},
	{
		slug: 'draft-dataset',
		orgSlug: 'example-org',
		projectSlug: 'example-study',
		name: 'Draft Dataset',
		description: 'Placeholder freshly created dataset — active immediately, no revisions yet.',
		lifecycle: 'ACTIVE',
		classification: 'unclassified',
		profile: 'example-profile@1',
		tags: ['placeholder'],
		layers: layers('-', '-', '-', '-')
	}
];

export const searchResults: SearchResults = {
	hits: [
		{
			kind: 'dataset',
			slugPath: '/example-org/example-study/example-sweep',
			title: 'Example Sweep',
			snippet: 'Placeholder dataset with all four layers materialized.',
			layers: layers('+', '+', '+', '+'),
			classification: 'unclassified'
		},
		{
			kind: 'product',
			slugPath: '/product/example-product',
			title: 'Example Product',
			snippet: 'Placeholder Gold product, marked stale to prove the badge renders.',
			layers: layers('+', '+', '+', '+'),
			classification: 'unclassified',
			stale: { reason: 'upstream revision corrected — recompute pending' }
		}
	],
	watermark: { state: 'healthy', lagSeconds: 12 },
	facets: {
		organization: [{ value: 'example-org', count: 2 }],
		classification: [{ value: 'unclassified', count: 2 }],
		layer: [
			{ value: 'raw', count: 2 },
			{ value: 'gold', count: 1 }
		]
	},
	nextCursor: null,
	prevCursor: null
};

export const apiKeys: ApiKey[] = [
	{
		id: 'key-placeholder-1',
		name: 'placeholder-workstation',
		scopes: ['read'],
		projectRestriction: 'example-org/example-study',
		createdAt: '2026-01-04T08:00:00Z',
		lastUsedAt: '2026-02-20T17:45:00Z',
		expiresAt: '2027-01-04T08:00:00Z'
	}
];

export const whoami: WhoAmI = {
	subject: 'karl.schmidt@example.org',
	displayName: 'Karl Schmidt',
	bindings: [
		{ principal: 'karl.schmidt@example.org', role: 'reader', scope: 'example-org/example-study' },
		{ principal: 'karl.schmidt@example.org', role: 'project_admin', scope: 'example-org' }
	]
};

export const organizationMembers: OrganizationMember[] = [
	{
		id: 'member-karl',
		displayName: 'Karl Schmidt',
		email: 'karl.schmidt@example.org',
		kind: 'user',
		status: 'active',
		lastActiveAt: '2026-08-30T17:42:00Z'
	},
	{
		id: 'member-maya',
		displayName: 'Maya Chen',
		email: 'maya.chen@example.org',
		kind: 'user',
		status: 'active',
		lastActiveAt: '2026-08-29T14:18:00Z'
	},
	{
		id: 'member-science',
		displayName: 'Science Data Team',
		email: 'group:science-data',
		kind: 'group',
		status: 'active',
		lastActiveAt: null
	},
	{
		id: 'member-pipeline',
		displayName: 'Bronze Pipeline',
		email: 'sa:bronze-pipeline',
		kind: 'service_account',
		status: 'active',
		lastActiveAt: '2026-08-30T16:58:00Z'
	}
];

export const organizationPermissions: PermissionGrant[] = [
	{
		id: 'grant-karl-admin',
		principal: 'user:karl.schmidt@example.org',
		displayName: 'Karl Schmidt',
		principalKind: 'user',
		role: 'organization_admin',
		scope: 'example-org',
		inherited: false
	},
	{
		id: 'grant-maya-admin',
		principal: 'user:maya.chen@example.org',
		displayName: 'Maya Chen',
		principalKind: 'user',
		role: 'project_admin',
		scope: 'example-org',
		inherited: false
	},
	{
		id: 'grant-science-reader',
		principal: 'group:science-data',
		displayName: 'Science Data Team',
		principalKind: 'group',
		role: 'reader',
		scope: 'example-org',
		inherited: false
	},
	{
		id: 'grant-platform',
		principal: 'group:platform-owners',
		displayName: 'Platform Owners',
		principalKind: 'group',
		role: 'platform_owner',
		scope: 'SYSTEM',
		inherited: true,
		inheritedFrom: 'System'
	}
];

export const projectPermissions: PermissionGrant[] = [
	{
		id: 'grant-project-science',
		principal: 'group:science-data',
		displayName: 'Science Data Team',
		principalKind: 'group',
		role: 'developer',
		scope: 'example-org/example-study',
		inherited: false
	},
	{
		id: 'grant-project-karl',
		principal: 'user:karl.schmidt@example.org',
		displayName: 'Karl Schmidt',
		principalKind: 'user',
		role: 'organization_admin',
		scope: 'example-org',
		inherited: true,
		inheritedFrom: 'Example Organization'
	},
	{
		id: 'grant-project-maya',
		principal: 'user:maya.chen@example.org',
		displayName: 'Maya Chen',
		principalKind: 'user',
		role: 'project_admin',
		scope: 'example-org',
		inherited: true,
		inheritedFrom: 'Example Organization'
	}
];
