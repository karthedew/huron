import { describe, expect, it } from 'vitest';
import * as client from './client';
import { NotFound } from './types';

describe('the API seam', () => {
	it('returns a keyset page shape, not a bare array', async () => {
		const page = await client.listOrganizations();
		expect(page).toHaveProperty('items');
		expect(page).toHaveProperty('nextCursor');
		expect(page).toHaveProperty('prevCursor');
	});

	it('throws NotFound — never a 403-shaped error — for undiscoverable resources', async () => {
		await expect(client.getOrganization('no-such-org')).rejects.toBeInstanceOf(NotFound);
		await expect(client.getProject('example-org', 'no-such-project')).rejects.toBeInstanceOf(
			NotFound
		);
	});

	it('scopes children to their parent', async () => {
		const projects = await client.listProjects('second-org');
		expect(projects.items).toHaveLength(0);
	});

	it('returns no hits and no facets for an empty query', async () => {
		const results = await client.search('   ');
		expect(results.hits).toHaveLength(0);
		expect(results.facets).toEqual({});
	});

	it('reports a projection watermark on every search response', async () => {
		const results = await client.search('example');
		expect(results.watermark.state).toBeDefined();
	});
});
