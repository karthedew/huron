import { json, type RequestEvent } from '@sveltejs/kit';
import type { HuronUser } from '$api/types';
import {
	parseRawFile,
	parseRawManifest,
	parseRawReceipt,
	parseRawRegistration,
	parseRawRevision,
	parseRawRevisions,
	parseRawSession
} from '$api/raw-ingestion-client';
import {
	boundRawTarget,
	parseRawTarget,
	requireRawPermissions,
	type RawTarget
} from './raw-authorization';
import { rawBridgeRequest } from './raw-bridge';
import { object, PolarisApiError, type PolarisClient } from './polaris-client';
import {
	managedRawDatasetId,
	preflightRawTarget,
	registerCommittedRawDataset
} from './raw-registration';
import { loadRawTargetBranch } from './raw-targets';

const MAX_PART_BYTES = 64 * 1024 * 1024;
const MAX_JSON_BYTES = 8 * 1024 * 1024;

async function requestBytes(request: Request, maximum: number): Promise<Uint8Array> {
	const announced = request.headers.get('content-length');
	if (announced && (!/^\d+$/.test(announced) || Number(announced) > maximum))
		throw new PolarisApiError(413, 'The request exceeds the upload part limit.');
	const chunks: Uint8Array[] = [];
	let size = 0;
	const reader = request.body?.getReader();
	if (reader) {
		try {
			while (true) {
				const next = await reader.read();
				if (next.done) break;
				size += next.value.byteLength;
				if (size > maximum) {
					await reader.cancel();
					throw new PolarisApiError(413, 'The request exceeds the upload part limit.');
				}
				chunks.push(next.value);
			}
		} finally {
			reader.releaseLock();
		}
	}
	if (announced && size !== Number(announced))
		throw new PolarisApiError(400, 'The upload body length did not match its declaration.');
	return Buffer.concat(chunks);
}

function parseJson(text: string): unknown {
	try {
		return JSON.parse(text);
	} catch {
		throw new PolarisApiError(400, 'Send valid JSON.');
	}
}

function incomingObject(value: unknown): Record<string, unknown> {
	if (typeof value !== 'object' || value === null || Array.isArray(value))
		throw new PolarisApiError(400, 'Send a JSON object.');
	return Object.fromEntries(Object.entries(value));
}

function responseText(value: unknown): string {
	if (typeof value !== 'string' || !value)
		throw new PolarisApiError(502, 'The Raw service returned an invalid identity.');
	return value;
}

interface Context {
	user: HuronUser;
	client: PolarisClient;
	target: RawTarget;
}

/** Re-evaluate current grants immediately before issuing each tightly scoped backend credential. */
async function forward(
	context: Context,
	path: string,
	method: string,
	body: Uint8Array = new Uint8Array(),
	headers: Record<string, string> = {},
	onDispatch?: () => void
): Promise<Response> {
	const permissions = await requireRawPermissions(
		context.client,
		context.user,
		context.target,
		path.startsWith('/datasets/') || path.startsWith('/revisions/') ? 'read' : 'write'
	);
	onDispatch?.();
	return rawBridgeRequest({
		user: context.user,
		target: boundRawTarget(context.target),
		permissions,
		method,
		path: `/api/raw-web${path}`,
		body,
		headers
	});
}

async function registerReceipt(
	context: Context,
	uploadId: string,
	receipt: Record<string, unknown>
): Promise<Record<string, unknown>> {
	const registration = object(receipt.registration);
	const datasetId = responseText(registration.dataset_id);
	const revisionId = responseText(registration.revision_id);
	try {
		await registerCommittedRawDataset(context.client, context.user, context.target, datasetId);
		const response = await forward(
			context,
			`/uploads/${encodeURIComponent(uploadId)}/registration`,
			'POST',
			Buffer.from(JSON.stringify({ revision_id: revisionId }))
		);
		return { ...receipt, registration: parseRawRegistration(await response.json()) };
	} catch (error) {
		return {
			...receipt,
			registration: {
				...registration,
				state: 'pending',
				error:
					error instanceof PolarisApiError
						? error.message
						: 'Polaris registration is unavailable. Retry registration to expose this committed revision in Browse.'
			}
		};
	}
}

function boundHeaders(request: Request): Record<string, string> {
	const result: Record<string, string> = {};
	for (const key of ['idempotency-key', 'if-match']) {
		const value = request.headers.get(key);
		if (value) result[key] = value;
	}
	return result;
}

function allowedOperation(path: string, method: string): boolean {
	const id = '[0-9a-fA-F-]{36}';
	if (method === 'GET')
		return new RegExp(
			`^/(?:uploads/${id}|datasets/${id}/revisions|revisions/${id}|revisions/${id}/manifest|revisions/${id}/files/.+)$`
		).test(path);
	if (method === 'PUT')
		return new RegExp(`^/uploads/${id}/files/${id}/parts/[1-9][0-9]*$`).test(path);
	if (method === 'POST')
		return (
			path === '/uploads' ||
			new RegExp(
				`^/uploads/${id}/(?:files/${id}/complete|verify|heartbeat|abort|commit|registration)$`
			).test(path)
		);
	return false;
}

/** Same-origin browser transport; secrets and privileged directory access never leave the server. */
export async function handleRawApi(
	event: Pick<RequestEvent, 'locals' | 'request' | 'url'>
): Promise<Response> {
	let uploadNotStarted =
		event.request.method === 'POST' && event.url.pathname === '/ingestion/api/uploads';
	try {
		const user = event.locals.user;
		const client = event.locals.polaris;
		if (!user || user.disabled || !client)
			throw new PolarisApiError(401, 'Sign in to Huron to continue.');
		if (
			!['GET', 'HEAD'].includes(event.request.method) &&
			event.request.headers.get('origin') !== event.url.origin
		)
			throw new PolarisApiError(403, 'The upload request must come from this Huron site.');
		const path = event.url.pathname.slice('/ingestion/api'.length);
		if (path === '/targets' && event.request.method === 'GET') {
			const namespace: unknown = parseJson(event.url.searchParams.get('namespace') ?? '[]');
			if (!Array.isArray(namespace) || namespace.some((part) => typeof part !== 'string'))
				throw new PolarisApiError(400, 'Invalid namespace.');
			const selection = parseRawTarget({
				catalog: event.url.searchParams.get('catalog'),
				namespace: namespace.length ? namespace : ['root'],
				name: 'selection'
			});
			return json(
				await loadRawTargetBranch(client, user, {
					catalog: selection.catalog,
					namespace: namespace.length ? selection.namespace : [],
					namespacePageToken: event.url.searchParams.get('namespacePageToken') ?? '',
					datasetPageToken: event.url.searchParams.get('datasetPageToken') ?? ''
				})
			);
		}
		if (!allowedOperation(path, event.request.method)) throw new PolarisApiError(404);
		let bytes = await requestBytes(
			event.request,
			event.request.method === 'PUT' ? MAX_PART_BYTES : MAX_JSON_BYTES
		);
		let target: RawTarget;
		let requestedDatasetId: string | null = null;
		if (path === '/uploads' && event.request.method === 'POST') {
			const input = incomingObject(parseJson(Buffer.from(bytes).toString('utf8')));
			target = parseRawTarget(input.target);
			if (
				input.expectedDatasetId !== null &&
				(typeof input.expectedDatasetId !== 'string' ||
					!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(
						input.expectedDatasetId
					))
			)
				throw new PolarisApiError(
					400,
					'Choose a new dataset or select an existing managed dataset.'
				);
			requestedDatasetId = input.expectedDatasetId;
			delete input.target;
			delete input.expectedDatasetId;
			bytes = Buffer.from(JSON.stringify(input));
		} else target = parseRawTarget(parseJson(event.url.searchParams.get('target') ?? 'null'));
		const context = { user, client, target };
		await requireRawPermissions(
			client,
			user,
			target,
			path.startsWith('/datasets/') || path.startsWith('/revisions/') ? 'read' : 'write'
		);
		let expectedDatasetId: string | null = null;
		if (path === '/uploads') {
			expectedDatasetId = await preflightRawTarget(client, user, target);
			if (expectedDatasetId !== requestedDatasetId)
				throw new PolarisApiError(
					409,
					'The selected catalog path changed. Select the intended dataset again before uploading.'
				);
		}
		if (path.startsWith('/datasets/') || path.startsWith('/revisions/')) {
			const managedId = await managedRawDatasetId(client, target);
			if (!managedId || (path.startsWith('/datasets/') && path.split('/')[2] !== managedId))
				throw new PolarisApiError(404);
		}
		if (path.endsWith('/registration')) {
			const uploadId = path.split('/')[2];
			const session = object(await (await forward(context, `/uploads/${uploadId}`, 'GET')).json());
			if (!session.registration)
				throw new PolarisApiError(409, 'Commit this upload before registering it in Polaris.');
			return json(
				parseRawRegistration((await registerReceipt(context, uploadId, session)).registration)
			);
		}
		let backendPath = path;
		if (path.endsWith('/revisions') && event.url.searchParams.has('before')) {
			const before = event.url.searchParams.get('before') ?? '';
			if (!/^[1-9][0-9]*$/.test(before) || !Number.isSafeInteger(Number(before)))
				throw new PolarisApiError(400, 'Invalid revision page cursor.');
			backendPath += `?before=${before}`;
		}
		const upstream = await forward(
			context,
			backendPath,
			event.request.method,
			bytes,
			boundHeaders(event.request),
			() => {
				uploadNotStarted = false;
			}
		);
		if (path.includes('/revisions/') && path.includes('/files/')) {
			return new Response(upstream.body, {
				status: upstream.status,
				headers: {
					'Content-Type': upstream.headers.get('content-type') ?? 'application/octet-stream',
					'Content-Disposition': upstream.headers.get('content-disposition') ?? 'attachment',
					'Cache-Control': 'private, no-store',
					'X-Content-Type-Options': 'nosniff'
				}
			});
		}
		if (upstream.status === 204) return new Response(null, { status: 204 });
		const result = object(await upstream.json());
		if (expectedDatasetId && result.dataset_id !== expectedDatasetId)
			throw new PolarisApiError(
				409,
				'This Polaris registration does not match this Raw service dataset.'
			);
		if (path.endsWith('/commit'))
			return json(parseRawReceipt(await registerReceipt(context, path.split('/')[2], result)));
		const decoded =
			path.includes('/parts/') || path.endsWith('/complete')
				? parseRawFile(result)
				: path.endsWith('/revisions')
					? parseRawRevisions(result)
					: path.endsWith('/manifest')
						? parseRawManifest(result)
						: path.startsWith('/revisions/')
							? parseRawRevision(result)
							: parseRawSession(result);
		return json(decoded, {
			status: upstream.status,
			headers: { 'Cache-Control': 'private, no-store' }
		});
	} catch (error) {
		return json(
			{
				message:
					error instanceof PolarisApiError
						? error.message
						: 'Unable to complete the Raw upload operation.',
				...(uploadNotStarted ? { uploadNotStarted: true } : {})
			},
			{ status: error instanceof PolarisApiError ? error.status : 500 }
		);
	}
}
