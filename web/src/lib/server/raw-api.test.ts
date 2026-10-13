import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { HuronUser } from '$api/types';
import { handleRawApi } from './raw-api';
import { requireRawPermissions } from './raw-authorization';
import { rawBridgeRequest } from './raw-bridge';
import {
	managedRawDatasetId,
	preflightRawTarget,
	registerCommittedRawDataset
} from './raw-registration';
import { PolarisApiError, PolarisClient } from './polaris-client';

vi.mock('./raw-authorization', async (original) => ({
	...(await original<typeof import('./raw-authorization')>()),
	requireRawPermissions: vi.fn()
}));
vi.mock('./raw-bridge', () => ({ rawBridgeRequest: vi.fn() }));
vi.mock('./raw-registration', () => ({
	managedRawDatasetId: vi.fn(),
	preflightRawTarget: vi.fn(),
	registerCommittedRawDataset: vi.fn()
}));

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
const client = new PolarisClient({
	url: 'http://polaris.test',
	realm: 'POLARIS',
	clientId: 'alice',
	clientSecret: 'secret'
});
const target = { catalog: 'science', namespace: ['earth'], name: 'upload' };
const uploadId = '11111111-1111-4111-8111-111111111111';
const datasetId = '22222222-2222-4222-8222-222222222222';
const revisionId = '33333333-3333-4333-8333-333333333333';
const registration = { state: 'pending', dataset_id: datasetId, revision_id: revisionId };
const receipt = {
	id: revisionId,
	dataset_id: datasetId,
	number: 1,
	manifest_sha256: 'a'.repeat(64),
	metadata_sha256: 'b'.repeat(64),
	file_count: 1,
	total_bytes: 4,
	committed_by: 'huron-web:alice',
	committed_at: '2026-10-13T00:00:00Z',
	registration
};

function event(path: string, method = 'GET', body?: string, origin = 'http://huron.test') {
	const url = new URL(`http://huron.test/ingestion/api${path}`);
	url.searchParams.set('target', JSON.stringify(target));
	return {
		locals: { user, polaris: client },
		url,
		request: new Request(url, {
			method,
			...(body ? { body } : {}),
			headers: {
				origin,
				'content-type': 'application/json',
				'idempotency-key': 'same-upload',
				'if-match': '"4"'
			}
		})
	};
}

beforeEach(() => {
	vi.resetAllMocks();
	vi.mocked(requireRawPermissions).mockResolvedValue({ read: true, write: true, create: true });
	vi.mocked(preflightRawTarget).mockResolvedValue(null);
	vi.mocked(managedRawDatasetId).mockResolvedValue(datasetId);
	vi.mocked(registerCommittedRawDataset).mockResolvedValue();
});

describe('Raw browser API authorization and publication', () => {
	it.each(['POST', 'PUT'])(
		'rejects cross-origin %s requests before reading grants or forwarding bytes',
		async (method) => {
			const response = await handleRawApi(
				event(`/uploads/${uploadId}/commit`, method, '{}', 'http://other.test')
			);
			expect(response.status).toBe(403);
			expect(requireRawPermissions).not.toHaveBeenCalled();
			expect(rawBridgeRequest).not.toHaveBeenCalled();
		}
	);

	it('does not call the backend after current organization or Polaris permission denial', async () => {
		vi.mocked(requireRawPermissions).mockRejectedValue(new PolarisApiError(404));
		expect((await handleRawApi(event(`/uploads/${uploadId}/verify`, 'POST', '{}'))).status).toBe(
			404
		);
		expect(rawBridgeRequest).not.toHaveBeenCalled();
	});

	it('returns a durable commit receipt as registration pending without re-uploading on Polaris failure', async () => {
		vi.mocked(rawBridgeRequest).mockResolvedValue(Response.json(receipt));
		vi.mocked(registerCommittedRawDataset).mockRejectedValue(
			new PolarisApiError(503, 'Polaris is unavailable.')
		);
		const response = await handleRawApi(
			event(
				`/uploads/${uploadId}/commit`,
				'POST',
				'{"manifest_sha256":"digest","metadata":{"title":"Files"}}'
			)
		);
		expect(response.status).toBe(200);
		expect(await response.json()).toMatchObject({
			id: revisionId,
			number: 1,
			registration: { state: 'pending', error: 'Polaris is unavailable.' }
		});
		expect(rawBridgeRequest).toHaveBeenCalledTimes(1);
		expect(rawBridgeRequest).toHaveBeenCalledWith(
			expect.objectContaining({
				path: `/api/raw-web/uploads/${uploadId}/commit`,
				target: expect.objectContaining(target),
				headers: { 'idempotency-key': 'same-upload', 'if-match': '"4"' }
			})
		);
	});

	it('retries registration using the persisted session receipt and never starts another upload', async () => {
		vi.mocked(rawBridgeRequest)
			.mockResolvedValueOnce(Response.json({ registration }))
			.mockResolvedValueOnce(Response.json({ ...registration, state: 'registered' }));
		const response = await handleRawApi(
			event(`/uploads/${uploadId}/registration`, 'POST', '{"revision_id":"attacker-value"}')
		);
		expect(await response.json()).toEqual({ ...registration, state: 'registered' });
		expect(rawBridgeRequest).toHaveBeenNthCalledWith(
			2,
			expect.objectContaining({
				path: `/api/raw-web/uploads/${uploadId}/registration`,
				body: Buffer.from(JSON.stringify({ revision_id: revisionId }))
			})
		);
		expect(preflightRawTarget).not.toHaveBeenCalled();
	});

	it('keeps the complete committed revision when acknowledgement returns a direct registration object', async () => {
		vi.mocked(rawBridgeRequest)
			.mockResolvedValueOnce(Response.json(receipt))
			.mockResolvedValueOnce(Response.json({ ...registration, state: 'registered' }));
		const response = await handleRawApi(event(`/uploads/${uploadId}/commit`, 'POST', '{}'));
		expect(response.status).toBe(200);
		expect(await response.json()).toEqual({
			...receipt,
			registration: { ...registration, state: 'registered' }
		});
	});

	it('refuses a dataset URL that does not match the current Polaris registration', async () => {
		const response = await handleRawApi(event(`/datasets/${uploadId}/revisions`));
		expect(response.status).toBe(404);
		expect(rawBridgeRequest).not.toHaveBeenCalled();
	});

	it('binds the validated revision cursor into the forwarded signed request', async () => {
		vi.mocked(rawBridgeRequest).mockResolvedValue(
			Response.json({ revisions: [], next_before: null })
		);
		const request = event(`/datasets/${datasetId}/revisions`);
		request.url.searchParams.set('before', '101');
		expect((await handleRawApi(request)).status).toBe(200);
		expect(rawBridgeRequest).toHaveBeenCalledWith(
			expect.objectContaining({ path: `/api/raw-web/datasets/${datasetId}/revisions?before=101` })
		);
		vi.mocked(rawBridgeRequest).mockClear();
		request.url.searchParams.set('before', '101&other=target');
		expect((await handleRawApi(request)).status).toBe(400);
		expect(rawBridgeRequest).not.toHaveBeenCalled();
	});

	it('refuses creating a new dataset at an existing managed name before beginning an upload', async () => {
		vi.mocked(preflightRawTarget).mockResolvedValue(datasetId);
		const response = await handleRawApi(
			event(
				'/uploads',
				'POST',
				JSON.stringify({ target, expectedDatasetId: null, title: 'New', files: [] })
			)
		);
		expect(response.status).toBe(409);
		expect(await response.json()).toMatchObject({ uploadNotStarted: true });
		expect(rawBridgeRequest).not.toHaveBeenCalled();
	});

	it('refuses a stale existing dataset selection and requires explicit create versus append intent', async () => {
		vi.mocked(preflightRawTarget).mockResolvedValue(datasetId);
		const mismatch = await handleRawApi(
			event(
				'/uploads',
				'POST',
				JSON.stringify({ target, expectedDatasetId: uploadId, title: 'Append', files: [] })
			)
		);
		expect(mismatch.status).toBe(409);
		const missing = await handleRawApi(
			event('/uploads', 'POST', JSON.stringify({ target, title: 'Unspecified', files: [] }))
		);
		expect(missing.status).toBe(400);
		expect(rawBridgeRequest).not.toHaveBeenCalled();
	});

	it('marks a begin request as not started when its final authorization fails before dispatch', async () => {
		vi.mocked(requireRawPermissions)
			.mockResolvedValueOnce({ read: true, write: true, create: true })
			.mockRejectedValueOnce(new PolarisApiError(403));
		const response = await handleRawApi(
			event(
				'/uploads',
				'POST',
				JSON.stringify({ target, expectedDatasetId: null, title: 'New', files: [] })
			)
		);
		expect(response.status).toBe(403);
		expect(await response.json()).toMatchObject({ uploadNotStarted: true });
		expect(rawBridgeRequest).not.toHaveBeenCalled();
	});

	it('never marks an uncertain backend begin failure as an upload that did not start', async () => {
		vi.mocked(rawBridgeRequest).mockRejectedValue(new PolarisApiError(503, 'Response lost.'));
		const response = await handleRawApi(
			event(
				'/uploads',
				'POST',
				JSON.stringify({ target, expectedDatasetId: null, title: 'New', files: [] })
			)
		);
		expect(response.status).toBe(503);
		expect(await response.json()).not.toHaveProperty('uploadNotStarted');
		expect(rawBridgeRequest).toHaveBeenCalledOnce();
	});

	it('omits the marker after a begin response is malformed or identifies a different dataset', async () => {
		vi.mocked(rawBridgeRequest).mockResolvedValueOnce(Response.json({}));
		const malformed = await handleRawApi(
			event(
				'/uploads',
				'POST',
				JSON.stringify({ target, expectedDatasetId: null, title: 'New', files: [] })
			)
		);
		expect(malformed.status).toBe(500);
		expect(await malformed.json()).not.toHaveProperty('uploadNotStarted');
		vi.mocked(preflightRawTarget).mockResolvedValue(datasetId);
		vi.mocked(rawBridgeRequest).mockResolvedValueOnce(Response.json({ dataset_id: uploadId }));
		const mismatch = await handleRawApi(
			event(
				'/uploads',
				'POST',
				JSON.stringify({ target, expectedDatasetId: datasetId, title: 'Append', files: [] })
			)
		);
		expect(mismatch.status).toBe(409);
		expect(await mismatch.json()).not.toHaveProperty('uploadNotStarted');
	});
});
