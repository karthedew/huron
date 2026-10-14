import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { HuronUser } from '$api/types';
import { datasetLayer } from '$api/catalog-datasets';
import { requireRawPermissions } from './raw-authorization';
import { managedRawDatasetId, registerCommittedRawDataset } from './raw-registration';
import { object, PolarisClient, properties } from './polaris-client';

vi.mock('./raw-authorization', () => ({ requireRawPermissions: vi.fn() }));
const target = {
	organization: 'org',
	catalog: 'science',
	namespace: ['earth'],
	name: 'observations'
};
const datasetId = '11111111-1111-4111-8111-111111111111';
const otherId = '22222222-2222-4222-8222-222222222222';
const user: HuronUser = {
	id: 'alice',
	username: 'alice',
	displayName: 'Alice',
	disabled: false,
	isAdmin: false,
	polarisPrincipal: 'alice',
	polarisPrincipalRole: 'alice-role',
	createdAt: ''
};

function fixture(initialId: string | null, conflictingId: string | null = null) {
	let storedId = initialId;
	const writes: { method: string; body: unknown }[] = [];
	const client = new PolarisClient(
		{ url: 'http://polaris.test', realm: 'POLARIS', clientId: 'alice', clientSecret: 'secret' },
		async (input, init) => {
			const url = new URL(String(input));
			if (url.pathname.endsWith('/oauth/tokens')) return Response.json({ access_token: 'token' });
			if (init?.method === 'POST') {
				const body: unknown = JSON.parse(String(init.body));
				writes.push({ method: 'POST', body });
				storedId = conflictingId ?? datasetId;
				return conflictingId ? new Response(null, { status: 409 }) : Response.json({});
			}
			if (!storedId) return new Response(null, { status: 404 });
			return Response.json({
				table: {
					name: target.name,
					format: 'raw',
					properties: { 'huron.raw.service': 'huron-raw-v1', 'huron.raw.dataset-id': storedId }
				}
			});
		}
	);
	return { client, writes };
}

beforeEach(() => {
	vi.resetAllMocks();
	vi.mocked(requireRawPermissions).mockResolvedValue({ read: true, write: true, create: true });
});

describe('Raw Polaris registration retry safety', () => {
	it('registers the stable identity once and makes a completed retry read-only', async () => {
		const setup = fixture(null);
		await registerCommittedRawDataset(setup.client, user, target, datasetId);
		await registerCommittedRawDataset(setup.client, user, target, datasetId);
		expect(setup.writes).toEqual([
			{
				method: 'POST',
				body: {
					name: target.name,
					format: 'raw',
					properties: {
						'huron.dataset-type': 'raw',
						'huron.raw.service': 'huron-raw-v1',
						'huron.raw.dataset-id': datasetId
					}
				}
			}
		]);
		expect(await managedRawDatasetId(setup.client, target)).toBe(datasetId);
	});

	it.each([
		{ namespace: ['earth'], expected: 'unassigned' },
		{ namespace: ['earth', 'bronze'], expected: 'bronze' },
		{ namespace: ['silver', 'earth'], expected: 'silver' },
		{ namespace: ['earth', 'gold'], expected: 'gold' }
	])(
		'keeps Raw storage independent of the processing stage in $namespace',
		async ({ namespace, expected }) => {
			const setup = fixture(null);
			await registerCommittedRawDataset(setup.client, user, { ...target, namespace }, datasetId);
			const registered = object(setup.writes[0].body);
			expect(registered.format).toBe('raw');
			expect(datasetLayer(namespace, properties(registered.properties)).id).toBe(expected);
		}
	);

	it('does not adopt a different dataset already registered at the same name', async () => {
		const setup = fixture(otherId);
		await expect(
			registerCommittedRawDataset(setup.client, user, target, datasetId)
		).rejects.toMatchObject({ status: 409 });
		expect(setup.writes).toHaveLength(0);
	});

	it('rejects a concurrent create of another identity instead of dropping or replacing it', async () => {
		const setup = fixture(null, otherId);
		await expect(
			registerCommittedRawDataset(setup.client, user, target, datasetId)
		).rejects.toMatchObject({ status: 409 });
		expect(setup.writes).toHaveLength(1);
		expect(await managedRawDatasetId(setup.client, target)).toBe(otherId);
	});
});
