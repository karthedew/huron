import { describe, expect, it } from 'vitest';
import { ROLES, type GrantSource } from '$api/types';
import { catalogAccess } from './access';

describe('catalogAccess', () => {
	it('lists every role, strongest first, with its groups by scope', () => {
		const sources: GrantSource[] = [
			{ role: 'platform_admin', group: 'huron-platform-admins', scope: 'platform' },
			{ role: 'org_admin', group: 'helio-org-admins', scope: 'organization' },
			{ role: 'reader', group: 'helio-readers', scope: 'organization' },
			{ role: 'reader', group: 'helio-readers', scope: 'catalog' },
			{ role: 'reader', group: 'web-readers', scope: 'catalog' }
		];
		const access = catalogAccess(sources);
		expect(access.map(({ role }) => role)).toEqual([...ROLES]);
		expect(access.find(({ role }) => role === 'reader')?.sources).toEqual([
			{ scope: 'organization', groups: ['helio-readers'] },
			{ scope: 'catalog', groups: ['helio-readers', 'web-readers'] }
		]);
		expect(access.find(({ role }) => role === 'platform_admin')?.sources).toEqual([
			{ scope: 'platform', groups: ['huron-platform-admins'] }
		]);
	});

	it('leaves a role nobody holds without sources', () => {
		const access = catalogAccess([{ role: 'reader', group: 'r', scope: 'catalog' }]);
		expect(access.find(({ role }) => role === 'contributor')?.sources).toEqual([]);
		expect(catalogAccess([]).every(({ sources }) => sources.length === 0)).toBe(true);
	});

	it('keeps the order the API gave the groups in', () => {
		const access = catalogAccess([
			{ role: 'contributor', group: 'b', scope: 'catalog' },
			{ role: 'contributor', group: 'a', scope: 'catalog' }
		]);
		expect(access.find(({ role }) => role === 'contributor')?.sources).toEqual([
			{ scope: 'catalog', groups: ['b', 'a'] }
		]);
	});
});
