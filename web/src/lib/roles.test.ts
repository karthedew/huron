import { describe, expect, it } from 'vitest';
import { ROLES } from '$api/types';
import { catalogFixture, organizationFixture } from '$lib/testing/api-fixtures';
import { ROLE_ABILITIES, ROLE_NAMES, describeRoles } from './roles';

const HELIO = organizationFixture();
const GEO = organizationFixture({ id: 'o-geo', name: 'geo', display_name: 'Earth Science' });
const HELIOPHYSICS = catalogFixture();
const GEOSCIENCE = catalogFixture({
	id: 'c-geo',
	name: 'geoscience',
	organization: 'geo',
	display_name: ''
});
const SCOPES = { organizations: [HELIO, GEO], catalogs: [HELIOPHYSICS, GEOSCIENCE] };

describe('role copy', () => {
	it('names every role and what it allows', () => {
		for (const role of ROLES) {
			expect(ROLE_NAMES[role]).not.toBe('');
			expect(ROLE_ABILITIES[role]).not.toBe('');
		}
		expect(ROLE_NAMES.org_admin).toBe('Organization administrator');
	});
});

describe('describeRoles', () => {
	it('puts the platform first, then organizations, then catalogs by name', () => {
		const sentences = describeRoles(
			[
				{ scope: 'catalog', scope_id: GEOSCIENCE.id, role: 'reader' },
				{ scope: 'catalog', scope_id: HELIOPHYSICS.id, role: 'contributor' },
				{ scope: 'organization', scope_id: HELIO.id, role: 'org_admin' },
				{ scope: 'platform', scope_id: null, role: 'platform_admin' }
			],
			SCOPES
		);
		expect(sentences.map(({ lead }) => lead)).toEqual([
			'You are a platform administrator',
			'You are an organization administrator of',
			'You are a reader of',
			'You are a contributor to'
		]);
		expect(sentences.map(({ target }) => target)).toEqual([
			{ kind: 'platform' },
			{ kind: 'organization', name: 'helio', label: 'Heliophysics Division', context: null },
			{ kind: 'catalog', name: 'geoscience', label: 'geoscience', context: 'Earth Science' },
			{
				kind: 'catalog',
				name: 'heliophysics',
				label: 'Heliophysics',
				context: 'Heliophysics Division'
			}
		]);
		expect(sentences[0].abilities).toBe(`You can ${ROLE_ABILITIES.platform_admin}.`);
		expect(new Set(sentences.map(({ key }) => key)).size).toBe(4);
	});

	it('orders several roles on one catalog from the strongest', () => {
		const sentences = describeRoles(
			[
				{ scope: 'catalog', scope_id: HELIOPHYSICS.id, role: 'reader' },
				{ scope: 'catalog', scope_id: HELIOPHYSICS.id, role: 'catalog_admin' }
			],
			SCOPES
		);
		expect(sentences.map(({ lead }) => lead)).toEqual([
			'You are a catalog administrator of',
			'You are a reader of'
		]);
	});

	it('keeps scopes it cannot name, by their kind and short id', () => {
		const [catalog, organization] = describeRoles(
			[
				{ scope: 'catalog', scope_id: '0192f2a4-0000-7000-8000-00000000abcd', role: 'reader' },
				{ scope: 'organization', scope_id: null, role: 'org_admin' }
			],
			{ organizations: [], catalogs: [] }
		);
		expect(catalog.target).toEqual({ kind: 'unresolved', label: 'catalog 00000000abcd' });
		expect(organization.target).toEqual({ kind: 'unresolved', label: 'organization' });
		expect(catalog.abilities).toBe(`You can ${ROLE_ABILITIES.reader}.`);
	});

	it('names a catalog without a visible organization without context', () => {
		const [sentence] = describeRoles(
			[{ scope: 'catalog', scope_id: HELIOPHYSICS.id, role: 'reader' }],
			{ organizations: [], catalogs: [HELIOPHYSICS] }
		);
		expect(sentence.target).toMatchObject({ kind: 'catalog', context: null });
	});

	it('shows a role it does not know without explaining it', () => {
		const [sentence] = describeRoles(
			[{ scope: 'catalog', scope_id: HELIOPHYSICS.id, role: 'auditor' }],
			SCOPES
		);
		expect(sentence.lead).toBe('You hold the role auditor on');
		expect(sentence.abilities).toBe('');
	});

	it('describes no roles as none', () => {
		expect(describeRoles([], SCOPES)).toEqual([]);
	});
});
