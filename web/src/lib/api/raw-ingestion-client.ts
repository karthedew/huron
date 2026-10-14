import type {
	RawTarget,
	RawManifestFile,
	RawRevisionMetadata,
	RawIngestFile,
	RawRegistration,
	RawIngestSession,
	RawRevision,
	RawCommitReceipt,
	RawRevisionPage,
	RawRevisionManifest,
	RawTargetBranch,
	RawErrorResponse
} from './raw-ingestion-types';

export class RawApiError extends Error {
	constructor(
		public status: number,
		message: string,
		public uploadNotStarted = false
	) {
		super(message);
		this.name = 'RawApiError';
	}
}
function object(value: unknown): Record<string, unknown> {
	if (!value || typeof value !== 'object' || Array.isArray(value))
		throw new Error('Invalid Raw service response.');
	return Object.fromEntries(Object.entries(value));
}
function text(value: unknown): string {
	if (typeof value !== 'string') throw new Error('Invalid Raw service text.');
	return value;
}
function number(value: unknown): number {
	if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 0)
		throw new Error('Invalid Raw service count.');
	return value;
}
function array<T>(value: unknown, parse: (entry: unknown) => T): T[] {
	if (!Array.isArray(value)) throw new Error('Invalid Raw service list.');
	return value.map(parse);
}
const nullableText = (value: unknown) => (value == null ? null : text(value));
export function parseRawRegistration(value: unknown): RawRegistration {
	const v = object(value);
	if (v.state !== 'registered' && v.state !== 'pending')
		throw new Error('Invalid Raw registration state.');
	return {
		state: v.state,
		dataset_id: text(v.dataset_id),
		revision_id: text(v.revision_id),
		...(v.error === undefined ? {} : { error: text(v.error) })
	};
}
export function parseRawFile(value: unknown): RawIngestFile {
	const v = object(value);
	return {
		file_id: text(v.file_id),
		path: text(v.path),
		size: number(v.size),
		expected_sha256: text(v.expected_sha256),
		action: text(v.action),
		part_count: number(v.part_count),
		state: text(v.state),
		completed_parts: array(v.completed_parts, number)
	};
}
export function parseRawSession(value: unknown): RawIngestSession {
	const v = object(value);
	return {
		id: text(v.id),
		dataset_id: text(v.dataset_id),
		revision_id: text(v.revision_id),
		revision_number: number(v.revision_number),
		state: text(v.state),
		etag: number(v.etag),
		expires_at: text(v.expires_at),
		created_by: text(v.created_by),
		manifest_sha256: text(v.manifest_sha256),
		part_bytes: number(v.part_bytes),
		files: array(v.files, parseRawFile),
		registration: v.registration == null ? null : parseRawRegistration(v.registration)
	};
}
export function parseRawRevision(value: unknown): RawRevision {
	const v = object(value);
	return {
		id: text(v.id),
		dataset_id: text(v.dataset_id),
		number: number(v.number),
		manifest_sha256: text(v.manifest_sha256),
		metadata_sha256: text(v.metadata_sha256),
		file_count: number(v.file_count),
		total_bytes: number(v.total_bytes),
		committed_by: text(v.committed_by),
		committed_at: text(v.committed_at)
	};
}
export function parseRawReceipt(value: unknown): RawCommitReceipt {
	return {
		...parseRawRevision(value),
		registration: parseRawRegistration(object(value).registration)
	};
}
export function parseRawRevisions(value: unknown): RawRevisionPage {
	const v = object(value);
	return {
		revisions: array(v.revisions, parseRawRevision),
		next_before: v.next_before == null ? null : number(v.next_before)
	};
}
export function parseRawManifest(value: unknown): RawRevisionManifest {
	const v = object(value);
	return {
		schema: text(v.schema),
		hash_algorithm: text(v.hash_algorithm),
		files: array(v.files, (item) => {
			const f = object(item);
			return {
				path: text(f.path),
				size: number(f.size),
				sha256: text(f.sha256),
				media_type: text(f.media_type)
			};
		})
	};
}
export function parseRawBranch(value: unknown): RawTargetBranch {
	const v = object(value);
	return {
		catalog: text(v.catalog),
		namespace: array(v.namespace, text),
		folders: array(v.folders, (item) => array(item, text)),
		datasets: array(v.datasets, (item) => {
			const d = object(item);
			return { name: text(d.name), datasetId: nullableText(d.datasetId) };
		}),
		nextNamespacePageToken: nullableText(v.nextNamespacePageToken),
		nextDatasetPageToken: nullableText(v.nextDatasetPageToken)
	};
}

export function rawApiPath(path: string, target: RawTarget): `/ingestion/api/${string}` {
	return `/ingestion/api/${path}?${new URLSearchParams({ organization: target.organization, target: JSON.stringify(target) })}`;
}
async function request(path: string, init: RequestInit = {}): Promise<unknown> {
	const response = await fetch(path, {
		...init,
		headers: {
			...(init.body instanceof Blob ? {} : { 'Content-Type': 'application/json' }),
			...init.headers
		}
	});
	if (!response.ok) {
		let failure: RawErrorResponse = {
			message: 'The Raw operation failed. You can retry the same submission.'
		};
		try {
			const value = object(await response.json());
			failure = {
				message:
					typeof value.message === 'string'
						? value.message
						: typeof value.detail === 'string'
							? value.detail
							: failure.message,
				uploadNotStarted: value.uploadNotStarted === true
			};
		} catch {
			/* Keep infrastructure details out of the browser. */
		}
		throw new RawApiError(response.status, failure.message, failure.uploadNotStarted === true);
	}
	return response.json();
}
export async function browseRawTargets(
	catalog: string,
	namespace: string[],
	namespacePageToken: string | null = null,
	datasetPageToken: string | null = null,
	organization = ''
): Promise<RawTargetBranch> {
	const query = new URLSearchParams({
		organization,
		catalog,
		namespace: JSON.stringify(namespace)
	});
	if (namespacePageToken) query.set('namespacePageToken', namespacePageToken);
	if (datasetPageToken) query.set('datasetPageToken', datasetPageToken);
	return parseRawBranch(await request(`/ingestion/api/targets?${query}`));
}
export async function beginRawUpload(
	target: RawTarget,
	metadata: RawRevisionMetadata,
	files: RawManifestFile[],
	key: string,
	expectedDatasetId: string | null
): Promise<RawIngestSession> {
	return parseRawSession(
		await request(
			`/ingestion/api/uploads?${new URLSearchParams({ organization: target.organization })}`,
			{
				method: 'POST',
				headers: { 'Idempotency-Key': key },
				body: JSON.stringify({
					target,
					expectedDatasetId,
					title: metadata.title,
					description: metadata.description ?? '',
					files
				})
			}
		)
	);
}
export async function getRawUpload(target: RawTarget, id: string): Promise<RawIngestSession> {
	return parseRawSession(await request(rawApiPath(`uploads/${encodeURIComponent(id)}`, target)));
}
export async function uploadRawPart(
	target: RawTarget,
	id: string,
	fileId: string,
	part: number,
	body: Blob
): Promise<RawIngestFile> {
	return parseRawFile(
		await request(
			rawApiPath(
				`uploads/${encodeURIComponent(id)}/files/${encodeURIComponent(fileId)}/parts/${part}`,
				target
			),
			{ method: 'PUT', body, headers: { 'Content-Type': 'application/octet-stream' } }
		)
	);
}
export async function completeRawFile(
	target: RawTarget,
	id: string,
	fileId: string
): Promise<RawIngestFile> {
	return parseRawFile(
		await request(
			rawApiPath(
				`uploads/${encodeURIComponent(id)}/files/${encodeURIComponent(fileId)}/complete`,
				target
			),
			{ method: 'POST', body: '{}' }
		)
	);
}
export async function operateRawUpload(
	target: RawTarget,
	id: string,
	operation: 'verify' | 'heartbeat' | 'abort'
): Promise<RawIngestSession> {
	return parseRawSession(
		await request(rawApiPath(`uploads/${encodeURIComponent(id)}/${operation}`, target), {
			method: 'POST',
			body: '{}'
		})
	);
}
export async function commitRawUpload(
	target: RawTarget,
	session: RawIngestSession,
	metadata: RawRevisionMetadata,
	key: string
): Promise<RawCommitReceipt> {
	return parseRawReceipt(
		await request(rawApiPath(`uploads/${encodeURIComponent(session.id)}/commit`, target), {
			method: 'POST',
			headers: { 'If-Match': `"${session.etag}"`, 'Idempotency-Key': key },
			body: JSON.stringify({ manifest_sha256: session.manifest_sha256, metadata })
		})
	);
}
export async function registerRawUpload(target: RawTarget, id: string): Promise<RawRegistration> {
	return parseRawRegistration(
		await request(rawApiPath(`uploads/${encodeURIComponent(id)}/registration`, target), {
			method: 'POST',
			body: '{}'
		})
	);
}
export async function listRawRevisions(
	target: RawTarget,
	datasetId: string,
	before: number | null = null
): Promise<RawRevisionPage> {
	const path = rawApiPath(`datasets/${encodeURIComponent(datasetId)}/revisions`, target);
	return parseRawRevisions(await request(path + (before === null ? '' : `&before=${before}`)));
}
export function rawFileDownloadUrl(
	target: RawTarget,
	revisionId: string,
	path: string
): `/ingestion/api/${string}` {
	return rawApiPath(
		`revisions/${encodeURIComponent(revisionId)}/files/${path.split('/').map(encodeURIComponent).join('/')}`,
		target
	);
}
