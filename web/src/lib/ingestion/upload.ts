import {
	beginRawUpload,
	RawApiError,
	getRawUpload,
	uploadRawPart,
	completeRawFile,
	operateRawUpload,
	commitRawUpload,
	registerRawUpload
} from '$api/client';
import type {
	RawTarget,
	RawRevisionMetadata,
	RawManifestFile,
	RawIngestSession,
	RawCommitReceipt
} from '$api/types';
import type { UploadSource } from './files';
import { hashFile } from './hash-file';
export interface UploadProgress {
	phase: string;
	bytes: number;
	total: number;
	path: string;
}
export interface UploadDraft {
	key: string;
	beginUncertain: boolean;
	expectedDatasetId: string | null;
	target: RawTarget;
	metadata: RawRevisionMetadata;
	sources: UploadSource[];
	manifest: RawManifestFile[] | null;
	session: RawIngestSession | null;
	receipt: RawCommitReceipt | null;
}
export const rawUploadApi = {
	begin: beginRawUpload,
	get: getRawUpload,
	part: uploadRawPart,
	complete: completeRawFile,
	operate: operateRawUpload,
	commit: commitRawUpload,
	register: registerRawUpload
};
/** A later preflight rejection cannot resolve an earlier lost begin response. */
export function canReleaseRejectedDraft(draft: UploadDraft, error: unknown): boolean {
	return (
		!draft.session &&
		!draft.beginUncertain &&
		error instanceof RawApiError &&
		error.uploadNotStarted
	);
}
async function beginRetainedUpload(
	draft: UploadDraft,
	changed: () => void,
	api: typeof rawUploadApi
): Promise<RawIngestSession> {
	if (!draft.manifest) throw new Error('The submission manifest is unavailable.');
	try {
		const session = await api.begin(
			draft.target,
			draft.metadata,
			draft.manifest,
			draft.key,
			draft.expectedDatasetId
		);
		draft.beginUncertain = false;
		return session;
	} catch (error) {
		if (!(error instanceof RawApiError && error.uploadNotStarted)) draft.beginUncertain = true;
		changed();
		throw error;
	}
}
export function confirmedBytes(session: RawIngestSession): number {
	return session.files.reduce(
		(sum, file) =>
			sum +
			(file.state === 'COMPLETE'
				? file.size
				: file.completed_parts.reduce(
						(bytes, part) =>
							bytes +
							Math.max(
								0,
								Math.min(session.part_bytes, file.size - (part - 1) * session.part_bytes)
							),
						0
					)),
		0
	);
}
/** A retained draft owns one upload identity across uncertain network outcomes. */
export async function submitRawUpload(
	draft: UploadDraft,
	progress: (value: UploadProgress) => void,
	changed: () => void,
	api = rawUploadApi,
	hash = hashFile
): Promise<RawCommitReceipt> {
	const total = draft.sources.reduce((sum, entry) => sum + entry.file.size, 0);
	const report = (phase: string, bytes = 0, path = '') => progress({ phase, bytes, total, path });
	if (draft.receipt) {
		if (!draft.session) throw new Error('The committed upload identity is unavailable.');
		report('Registering in Polaris', total);
		draft.receipt = {
			...draft.receipt,
			registration: await api.register(draft.target, draft.session.id)
		};
		changed();
		report(
			draft.receipt.registration.state === 'registered'
				? 'Registered and readable'
				: 'Registration pending',
			total
		);
		return draft.receipt;
	}
	if (!draft.manifest) {
		const manifest: RawManifestFile[] = [];
		let done = 0;
		for (const source of draft.sources) {
			report('Calculating checksums', done, source.path);
			const sha256 = await hash(source.file, (bytes) =>
				report('Calculating checksums', done + bytes, source.path)
			);
			manifest.push({
				path: source.path,
				size: source.file.size,
				sha256,
				media_type: source.file.type || 'application/octet-stream'
			});
			done += source.file.size;
		}
		draft.manifest = manifest;
		changed();
	}
	report('Opening upload');
	draft.session = draft.session
		? await api.get(draft.target, draft.session.id)
		: await beginRetainedUpload(draft, changed, api);
	changed();
	if (['FAILED', 'ABORTED', 'RECOVERING', 'PREPARING'].includes(draft.session.state))
		throw new Error(
			`Upload is ${draft.session.state.toLowerCase()}. Its revision has not been reported as complete.`
		);
	if (draft.session.state === 'UPLOADING') {
		if (draft.session.part_bytes < 1 || draft.session.part_bytes > 64 * 1024 * 1024)
			throw new Error('The server returned an unsupported upload part size.');
		let heartbeat = Date.now();
		for (let index = 0; index < draft.session.files.length; index++) {
			let planned = draft.session.files[index];
			const source = draft.sources.find((entry) => entry.path === planned.path);
			if (
				!source ||
				source.file.size !== planned.size ||
				!draft.manifest.some(
					(entry) => entry.path === planned.path && entry.sha256 === planned.expected_sha256
				)
			)
				throw new Error('The upload plan does not match this frozen submission.');
			if (planned.state === 'COMPLETE') continue;
			for (let part = 1; part <= planned.part_count; part++) {
				if (planned.completed_parts.includes(part)) continue;
				report('Transferring files', confirmedBytes(draft.session), planned.path);
				const start = (part - 1) * draft.session.part_bytes;
				planned = await api.part(
					draft.target,
					draft.session.id,
					planned.file_id,
					part,
					source.file.slice(start, start + draft.session.part_bytes)
				);
				draft.session.files[index] = planned;
				changed();
				report('Transferring files', confirmedBytes(draft.session), planned.path);
				if (Date.now() - heartbeat > 30000) {
					draft.session = await api.operate(draft.target, draft.session.id, 'heartbeat');
					heartbeat = Date.now();
					changed();
				}
			}
			draft.session.files[index] = await api.complete(
				draft.target,
				draft.session.id,
				planned.file_id
			);
			changed();
		}
		report('Verifying files', total);
		draft.session = await api.operate(draft.target, draft.session.id, 'verify');
		changed();
	}
	report('Committing revision', total);
	draft.receipt = await api.commit(
		draft.target,
		draft.session,
		draft.metadata,
		`${draft.key}/commit`
	);
	changed();
	report(
		draft.receipt.registration.state === 'registered'
			? 'Registered and readable'
			: 'Registration pending',
		total
	);
	return draft.receipt;
}

/** Reconcile a possibly stale ledger before abandoning; publication cannot be cancelled. */
export async function discardRawUpload(
	draft: UploadDraft,
	changed: () => void,
	api = rawUploadApi
): Promise<void> {
	if (draft.receipt) throw new Error('This revision is already committed.');
	if (!draft.session && draft.manifest) {
		draft.session = await beginRetainedUpload(draft, changed, api);
		changed();
	}
	if (!draft.session) return;
	draft.session = await api.get(draft.target, draft.session.id);
	changed();
	if (['FAILED', 'ABORTED'].includes(draft.session.state)) return;
	if (!['UPLOADING', 'VERIFYING'].includes(draft.session.state))
		throw new Error(
			'This upload is publishing or recovering. Retry to obtain its outcome before editing.'
		);
	draft.session = await api.operate(draft.target, draft.session.id, 'abort');
	changed();
	if (draft.session.state !== 'ABORTED')
		throw new Error('The service has not confirmed that this upload was abandoned.');
}
