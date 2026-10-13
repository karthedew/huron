import { createHash, createHmac } from 'node:crypto';
import { env } from '$env/dynamic/private';
import type { HuronUser } from '$api/types';
import { PolarisApiError } from './polaris-client';
import type { RawBoundTarget, RawPermissions } from './raw-authorization';

export interface RawBridgeConfiguration {
	url: string;
	secret: string;
}

export function rawBridgeConfiguration(): RawBridgeConfiguration {
	const secret = env.HURON_RAW_BRIDGE_SECRET;
	if (!secret || Buffer.byteLength(secret) < 32 || !env.HURON_RAW_API_URL)
		throw new PolarisApiError(503, 'Raw storage is not configured for this Huron deployment.');
	let url: URL;
	try {
		url = new URL(env.HURON_RAW_API_URL);
	} catch {
		throw new PolarisApiError(503, 'The Raw service endpoint is invalid.');
	}
	if (
		!['http:', 'https:'].includes(url.protocol) ||
		url.username ||
		url.password ||
		url.search ||
		url.hash ||
		url.pathname !== '/'
	)
		throw new PolarisApiError(503, 'The Raw service endpoint must be an HTTP origin.');
	return { url: url.origin, secret };
}

export interface RawDelegation {
	user: HuronUser;
	target: RawBoundTarget;
	permissions: RawPermissions;
	method: string;
	path: string;
	body: Uint8Array;
	headers: Record<string, string>;
}

/** One short-lived credential authorizes only these exact request bytes and target. */
export function signRawDelegation(
	request: RawDelegation,
	secret: string,
	now = Math.floor(Date.now() / 1000)
): string {
	const header = Buffer.from(JSON.stringify({ alg: 'HS256', typ: 'JWT' })).toString('base64url');
	const claims = Buffer.from(
		JSON.stringify({
			iss: 'huron-web',
			aud: 'huron-raw',
			sub: `huron-web:${request.user.id}`,
			iat: now,
			exp: now + 60,
			method: request.method,
			path: request.path,
			body_sha256: createHash('sha256').update(request.body).digest('hex'),
			headers: request.headers,
			target: request.target,
			permissions: Object.entries(request.permissions)
				.filter(([, allowed]) => allowed)
				.map(([permission]) => permission)
		})
	).toString('base64url');
	const content = `${header}.${claims}`;
	return `${content}.${createHmac('sha256', secret).update(content).digest('base64url')}`;
}

/** The bridge never follows redirects carrying its server-only delegation. */
export async function rawBridgeRequest(
	request: RawDelegation,
	configuration = rawBridgeConfiguration(),
	fetcher: typeof fetch = fetch
): Promise<Response> {
	if (!request.path.startsWith('/api/raw-web/') || request.path.includes('#'))
		throw new PolarisApiError(400, 'Invalid Raw service operation.');
	let response: Response;
	try {
		response = await fetcher(`${configuration.url}${request.path}`, {
			method: request.method,
			redirect: 'error',
			headers: {
				Authorization: `Bearer ${signRawDelegation(request, configuration.secret)}`,
				'Content-Type': request.method === 'PUT' ? 'application/octet-stream' : 'application/json',
				...(request.method === 'GET' ? {} : { 'Content-Length': String(request.body.byteLength) }),
				...request.headers
			},
			...(request.method === 'GET' ? {} : { body: Buffer.from(request.body) })
		});
	} catch {
		throw new PolarisApiError(
			503,
			'Raw storage is unavailable. Retry this upload when it is running.'
		);
	}
	if (!response.ok) {
		let message = 'The Raw service could not complete this operation.';
		try {
			const value: unknown = await response.json();
			if (
				typeof value === 'object' &&
				value !== null &&
				'detail' in value &&
				typeof value.detail === 'string'
			)
				message = value.detail;
		} catch {
			// Non-JSON infrastructure errors must not expose upstream response bodies.
		}
		throw new PolarisApiError(response.status, message);
	}
	return response;
}
