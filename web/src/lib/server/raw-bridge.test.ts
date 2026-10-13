import { createHash, createHmac } from 'node:crypto';
import { describe, expect, it, vi } from 'vitest';
import { rawBridgeRequest, signRawDelegation, type RawDelegation } from './raw-bridge';

const request: RawDelegation = {
	user: {
		id: 'immutable-user-id',
		username: 'alice',
		displayName: 'Alice',
		isAdmin: false,
		disabled: false,
		polarisPrincipal: 'alice',
		polarisPrincipalRole: 'alice-role',
		createdAt: ''
	},
	target: {
		endpoint: 'http://polaris.test',
		realm: 'POLARIS',
		catalog: 'science',
		namespace: ['earth'],
		name: 'data'
	},
	permissions: { read: true, write: true, create: false },
	method: 'POST',
	path: '/api/raw-web/uploads/session/commit',
	body: Buffer.from('{"metadata":{"title":"Pinned upload"}}'),
	headers: { 'if-match': '"7"', 'idempotency-key': 'submission' }
};
const secret = 'a-test-bridge-secret-of-at-least-32-bytes';

describe('request-bound Raw delegation', () => {
	it('cryptographically binds body, actor, target, operation and retry/concurrency headers', () => {
		const token = signRawDelegation(request, secret, 10_000);
		const [header, claims, signature] = token.split('.');
		expect(signature).toBe(
			createHmac('sha256', secret).update(`${header}.${claims}`).digest('base64url')
		);
		const payload: unknown = JSON.parse(Buffer.from(claims, 'base64url').toString('utf8'));
		expect(payload).toEqual({
			iss: 'huron-web',
			aud: 'huron-raw',
			sub: 'huron-web:immutable-user-id',
			iat: 10_000,
			exp: 10_060,
			method: request.method,
			path: request.path,
			body_sha256: createHash('sha256').update(request.body).digest('hex'),
			headers: request.headers,
			target: request.target,
			permissions: ['read', 'write']
		});
		expect(
			signRawDelegation(
				{ ...request, headers: { ...request.headers, 'if-match': '"8"' } },
				secret,
				10_000
			)
		).not.toBe(token);
		expect(
			signRawDelegation({ ...request, body: Buffer.from('changed') }, secret, 10_000)
		).not.toBe(token);
	});

	it('forwards exact byte length and disallows redirects or browser-supplied authorization', async () => {
		const fetcher = vi.fn<typeof fetch>(async () => Response.json({ committed: true }));
		await rawBridgeRequest(request, { url: 'http://raw.test', secret }, fetcher);
		expect(fetcher).toHaveBeenCalledWith(
			'http://raw.test/api/raw-web/uploads/session/commit',
			expect.objectContaining({
				redirect: 'error',
				headers: expect.objectContaining({
					'Content-Length': String(request.body.byteLength),
					'if-match': '"7"',
					'idempotency-key': 'submission'
				})
			})
		);
	});

	it('does not leak infrastructure response bodies on malformed upstream failures', async () => {
		await expect(
			rawBridgeRequest(
				request,
				{ url: 'http://raw.test', secret },
				async () => new Response('private-path secret-stack', { status: 502 })
			)
		).rejects.toMatchObject({
			status: 502,
			message: 'The Raw service could not complete this operation.'
		});
	});
});
