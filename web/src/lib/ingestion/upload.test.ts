// @vitest-environment node
import { describe, it, expect, vi } from 'vitest';
import { RawApiError } from '$api/client';
import { createHash } from 'node:crypto';
import { hashBlob, HASH_CHUNK_BYTES } from './hash';
import { sourcePath, sourceError } from './files';
import {
	submitRawUpload,
	discardRawUpload,
	canReleaseRejectedDraft,
	type UploadDraft,
	type rawUploadApi
} from './upload';
import type { RawIngestSession, RawCommitReceipt } from '$api/types';
const digest = 'a'.repeat(64);
function setup() {
	const session: RawIngestSession = {
		id: 'upload',
		dataset_id: 'dataset',
		revision_id: 'revision',
		revision_number: 1,
		state: 'UPLOADING',
		etag: 1,
		expires_at: '2026-10-14',
		created_by: 'actor',
		manifest_sha256: digest,
		part_bytes: 2,
		files: [
			{
				file_id: 'file',
				path: 'payload/a.txt',
				size: 4,
				expected_sha256: digest,
				action: 'UPLOAD',
				part_count: 2,
				state: 'PENDING',
				completed_parts: []
			}
		],
		registration: null
	};
	const receipt: RawCommitReceipt = {
		id: 'revision',
		dataset_id: 'dataset',
		number: 1,
		manifest_sha256: digest,
		metadata_sha256: digest,
		file_count: 1,
		total_bytes: 4,
		committed_by: 'actor',
		committed_at: '2026-10-13',
		registration: { state: 'registered', dataset_id: 'dataset', revision_id: 'revision' }
	};
	const draft: UploadDraft = {
		key: 'same-identity',
		beginUncertain: false,
		expectedDatasetId: null,
		target: { catalog: 'domain', namespace: ['raw'], name: 'example' },
		metadata: { title: 'Example', creators: ['Scientist'] },
		sources: [{ id: 'a', path: 'payload/a.txt', file: new File(['data'], 'a.txt') }],
		manifest: null,
		session: null,
		receipt: null
	};
	const api: typeof rawUploadApi = {
		begin: vi.fn(async () => structuredClone(session)),
		get: vi.fn(async () => structuredClone(session)),
		part: vi.fn(async (_target, _id, _file, part) => {
			session.files[0].completed_parts.push(part);
			return structuredClone(session.files[0]);
		}),
		complete: vi.fn(async () => ({ ...session.files[0], state: 'COMPLETE' })),
		operate: vi.fn(async (_target, _id, operation) => ({
			...session,
			state: operation === 'verify' ? 'VERIFYING' : 'UPLOADING',
			etag: 2
		})),
		commit: vi.fn(async () => receipt),
		register: vi.fn(async () => receipt.registration)
	};
	return { session, receipt, draft, api };
}
describe('Raw submissions', () => {
	it('preserves relative directory paths and accepts equal basenames in different folders', () => {
		expect(sourcePath({ name: 'a.csv', webkitRelativePath: 'run/a.csv' })).toBe(
			'payload/run/a.csv'
		);
		expect(
			sourceError([
				{ path: 'payload/a/data.csv', file: { size: 1 } },
				{ path: 'payload/b/data.csv', file: { size: 1 } }
			])
		).toBe('');
		expect(
			sourceError([
				{ path: 'payload/data.csv', file: { size: 1 } },
				{ path: 'payload/data.csv', file: { size: 1 } }
			])
		).toContain('Duplicate');
		expect(
			sourceError([
				{ path: 'payload/a', file: { size: 1 } },
				{ path: 'payload/a-other', file: { size: 1 } },
				{ path: 'payload/a/b', file: { size: 1 } }
			])
		).toContain('file and directory');
	});
	it('normalizes Unicode and rejects casefold and byte-length collisions', () => {
		expect(sourcePath({ name: 'cafe\u0301.csv', webkitRelativePath: '' })).toBe('payload/café.csv');
		expect(
			sourceError([
				{ path: 'payload/straße.csv', file: { size: 1 } },
				{ path: 'payload/STRASSE.csv', file: { size: 1 } }
			])
		).toContain('Duplicate');
		expect(sourceError([{ path: 'payload/' + 'é'.repeat(510), file: { size: 1 } }])).toContain(
			'Invalid'
		);
	});
	it('hashes bounded reads with the same SHA-256 as the complete bytes, including empty files', async () => {
		const bytes = new Uint8Array(HASH_CHUNK_BYTES + 17).fill(7);
		const blob = new Blob([bytes]);
		const reads: number[] = [];
		const original = blob.slice.bind(blob);
		vi.spyOn(blob, 'slice').mockImplementation((start, end) => {
			reads.push((end ?? blob.size) - (start ?? 0));
			return original(start, end);
		});
		expect(await hashBlob(blob, () => {})).toBe(createHash('sha256').update(bytes).digest('hex'));
		expect(Math.max(...reads)).toBeLessThanOrEqual(HASH_CHUNK_BYTES);
		expect(await hashBlob(new Blob([]), () => {})).toBe(createHash('sha256').digest('hex'));
	});
	it('resumes confirmed parts with the original identity after an uncertain transfer result', async () => {
		const { draft, api, session } = setup();
		const part = api.part;
		let interrupted = false;
		api.part = vi.fn(async (...args: Parameters<typeof part>) => {
			const result = await part(...args);
			if (!interrupted) {
				interrupted = true;
				throw new Error('Connection interrupted');
			}
			return result;
		});
		const hash = vi.fn(async () => digest);
		await expect(
			submitRawUpload(
				draft,
				() => {},
				() => {},
				api,
				hash
			)
		).rejects.toThrow('Connection interrupted');
		expect(session.files[0].completed_parts).toEqual([1]);
		const receipt = await submitRawUpload(
			draft,
			() => {},
			() => {},
			api,
			hash
		);
		expect(receipt.registration.state).toBe('registered');
		expect(api.begin).toHaveBeenCalledTimes(1);
		expect(api.begin).toHaveBeenCalledWith(
			draft.target,
			draft.metadata,
			draft.manifest,
			'same-identity',
			null
		);
		expect(hash).toHaveBeenCalledTimes(1);
		expect(api.part).toHaveBeenCalledTimes(2);
		expect(api.commit).toHaveBeenCalledWith(
			draft.target,
			expect.objectContaining({ etag: 2 }),
			draft.metadata,
			'same-identity/commit'
		);
	});
	it('retries registration without transferring or committing a second revision', async () => {
		const { draft, api, receipt } = setup();
		api.commit = vi.fn(async (): Promise<RawCommitReceipt> => ({
			...receipt,
			registration: { ...receipt.registration, state: 'pending' }
		}));
		expect(
			(
				await submitRawUpload(
					draft,
					() => {},
					() => {},
					api,
					async () => digest
				)
			).registration.state
		).toBe('pending');
		expect(
			(
				await submitRawUpload(
					draft,
					() => {},
					() => {},
					api,
					async () => digest
				)
			).registration.state
		).toBe('registered');
		expect(api.commit).toHaveBeenCalledTimes(1);
		expect(api.part).toHaveBeenCalledTimes(2);
		expect(api.register).toHaveBeenCalledTimes(1);
	});
	it('does not claim publication when server verification fails', async () => {
		const { draft, api } = setup();
		api.operate = vi.fn(async () => {
			throw new Error('Checksum mismatch');
		});
		await expect(
			submitRawUpload(
				draft,
				() => {},
				() => {},
				api,
				async () => digest
			)
		).rejects.toThrow('Checksum mismatch');
		expect(api.commit).not.toHaveBeenCalled();
		expect(draft.receipt).toBeNull();
	});
});

describe('abandoning a Raw submission', () => {
	for (const state of ['FAILED', 'ABORTED'])
		it(`releases a ${state} draft without another abort`, async () => {
			const { draft, session, api } = setup();
			draft.session = session;
			api.get = vi.fn(async () => ({ ...session, state }));
			await discardRawUpload(draft, () => {}, api);
			expect(api.operate).not.toHaveBeenCalled();
			expect(draft.session.state).toBe(state);
		});
	for (const state of ['COMMITTING', 'COMMITTED', 'RECOVERING'])
		it(`does not abort a stale draft now ${state}`, async () => {
			const { draft, session, api } = setup();
			draft.session = session;
			api.get = vi.fn(async () => ({ ...session, state }));
			await expect(discardRawUpload(draft, () => {}, api)).rejects.toThrow(
				'publishing or recovering'
			);
			expect(api.operate).not.toHaveBeenCalled();
			expect(draft.session.state).toBe(state);
		});
	it('confirms ABORTED before releasing an active upload', async () => {
		const { draft, session, api } = setup();
		draft.session = session;
		api.operate = vi.fn(async () => ({ ...session, state: 'ABORTED' }));
		await discardRawUpload(draft, () => {}, api);
		expect(api.operate).toHaveBeenCalledWith(draft.target, session.id, 'abort');
		expect(draft.session.state).toBe('ABORTED');
	});
});

describe('uncertain begin retries', () => {
	it('retains the original identity when a later preflight rejection follows a lost response', async () => {
		const { draft, api } = setup();
		let attempts = 0;
		api.begin = vi.fn(async () => {
			attempts++;
			if (attempts === 1) throw new TypeError('Connection reset');
			throw new RawApiError(409, 'Catalog path changed', true);
		});
		await expect(
			submitRawUpload(
				draft,
				() => {},
				() => {},
				api,
				async () => digest
			)
		).rejects.toThrow('Connection reset');
		expect(draft.beginUncertain).toBe(true);
		try {
			await submitRawUpload(
				draft,
				() => {},
				() => {},
				api,
				async () => digest
			);
			throw new Error('Expected rejection');
		} catch (error) {
			expect(error).toBeInstanceOf(RawApiError);
			expect(canReleaseRejectedDraft(draft, error)).toBe(false);
		}
		expect(draft.beginUncertain).toBe(true);
		expect(draft.key).toBe('same-identity');
		expect(api.begin).toHaveBeenCalledTimes(2);
	});
	it('allows editing a confirmed first-attempt rejection with no uncertain history', async () => {
		const { draft, api } = setup();
		api.begin = vi.fn(async () => {
			throw new RawApiError(409, 'Catalog path changed', true);
		});
		try {
			await submitRawUpload(
				draft,
				() => {},
				() => {},
				api,
				async () => digest
			);
			throw new Error('Expected rejection');
		} catch (error) {
			expect(error).toBeInstanceOf(RawApiError);
			expect(canReleaseRejectedDraft(draft, error)).toBe(true);
		}
		expect(draft.beginUncertain).toBe(false);
		expect(draft.session).toBeNull();
		expect(draft.sources).toHaveLength(1);
	});
});
