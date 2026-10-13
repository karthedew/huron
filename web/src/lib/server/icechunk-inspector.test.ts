// @vitest-environment node
import { mkdtemp, mkdir, realpath, rm, symlink } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { IcechunkInspection } from '$api/types';
import { inspectIcechunk } from './icechunk-inspector';
import { PolarisClient } from './polaris-client';

const mocks = vi.hoisted(() => {
	const env: Record<string, string> = {};
	return { env, commands: vi.fn(), output: '', failure: false };
});
vi.mock('$env/dynamic/private', () => ({ env: mocks.env }));
vi.mock('node:child_process', () => ({
	execFile: (
		file: string,
		args: string[],
		options: object,
		callback: (error: Error | null, stdout: string) => void
	) => ({
		stdin: {
			end: (input: string) => {
				mocks.commands(file, args, options, JSON.parse(input));
				callback(mocks.failure ? new Error('private runtime path and secret') : null, mocks.output);
			}
		}
	})
}));

const folders: string[] = [];
const inspected: IcechunkInspection = {
	state: 'available',
	message: null,
	storage: 'FILE',
	selectedBranch: 'main',
	branches: [{ name: 'main', snapshotId: 'ABCDEFGHIJKLMNOPQRST' }],
	tags: [],
	snapshot: {
		id: 'ABCDEFGHIJKLMNOPQRST',
		parentId: null,
		writtenAt: '2020-01-01T00:00:00+00:00',
		message: 'Real commit',
		metadata: {}
	},
	groups: [{ path: '/', attributes: { description: 'Authorized metadata' } }],
	arrays: [
		{
			path: 'temperature',
			dtype: 'float32',
			shape: [2, 3],
			dimensions: ['time', 'lat'],
			chunks: [1, 3],
			attributes: { units: 'kelvin' }
		}
	],
	history: [],
	historyNextSnapshotId: null,
	provenance: { importReceipt: { source: 'https://nasa.example/data' }, source: {} },
	lineage: { state: 'unavailable', message: 'Scientific lineage unavailable' },
	truncated: false,
	redacted: false,
	limits: { references: 100, history: 100, schema: 200 }
};

async function storage() {
	const folder = await mkdtemp(join(tmpdir(), 'icechunk-inspection-'));
	folders.push(folder);
	const root = await realpath(folder);
	const path = join(root, 'repository');
	await mkdir(path);
	mocks.env.HURON_ICECHUNK_READ_ROOTS = JSON.stringify([root]);
	mocks.env.HURON_ICECHUNK_PYTHON = '../.local/polaris/icechunk-venv/bin/python';
	return { root, path, location: pathToFileURL(path).href };
}

function principal(
	location: string,
	options: {
		denyMetadata?: boolean;
		denyRead?: boolean;
		revokeAfterRead?: boolean;
		changedLocation?: string;
	} = {}
) {
	let credentialReads = 0;
	let tableReads = 0;
	const fetcher = vi.fn<typeof fetch>(async (input, init) => {
		const url = new URL(String(input));
		if (url.pathname.endsWith('/oauth/tokens')) {
			expect(String(init?.body)).toContain('client_id=current-scientist');
			return Response.json({ access_token: 'scientist-private-token', expires_in: 3600 });
		}
		expect(new Headers(init?.headers).get('Authorization')).toBe('Bearer scientist-private-token');
		if (url.pathname.endsWith('/credentials')) {
			credentialReads += 1;
			expect(url.searchParams.get('access-mode')).toBe('read');
			if (options.denyRead || (options.revokeAfterRead && credentialReads > 1))
				return Response.json({ message: 'secret storage credentials' }, { status: 403 });
			return Response.json({
				'storage-access-configs': [
					{ config: { 's3.secret-access-key': 'never-forward-this-secret' } }
				]
			});
		}
		tableReads += 1;
		if (options.denyMetadata)
			return Response.json({ message: 'secret table exists' }, { status: 403 });
		return Response.json({
			table: {
				name: 'temperature',
				location: options.changedLocation && tableReads > 1 ? options.changedLocation : location,
				properties: {}
			}
		});
	});
	return {
		client: new PolarisClient(
			{
				url: 'http://localhost:8181',
				realm: 'POLARIS',
				clientId: 'current-scientist',
				clientSecret: 'actor-private-secret'
			},
			fetcher
		),
		fetcher
	};
}

beforeEach(() => {
	for (const key of Object.keys(mocks.env)) delete mocks.env[key];
	mocks.output = JSON.stringify(inspected);
	mocks.failure = false;
});
afterEach(async () => {
	vi.clearAllMocks();
	await Promise.all(
		folders.splice(0).map((folder) => rm(folder, { recursive: true, force: true }))
	);
});

describe('authorized Icechunk metadata inspection', () => {
	it('checks the actual actor before and after a bounded fixed local metadata process', async () => {
		const { location, root, path } = await storage();
		const { client, fetcher } = principal(location);
		const result = await inspectIcechunk(
			client,
			'science',
			['nested', 'folder'],
			'temperature',
			'main'
		);
		expect(result.state).toBe('available');
		expect(result.arrays[0].dimensions).toEqual(['time', 'lat']);
		expect(result.snapshot?.writtenAt).toBe('2020-01-01T00:00:00.000Z');
		expect(fetcher.mock.calls.filter(([url]) => String(url).includes('/credentials'))).toHaveLength(
			2
		);
		expect(mocks.commands).toHaveBeenCalledOnce();
		const [python, args, options, input] = mocks.commands.mock.calls[0];
		expect(python).toContain('/.local/polaris/icechunk-venv/bin/python');
		expect(args).toEqual(['-I', expect.stringContaining('/scripts/inspect_icechunk.py')]);
		expect(options).toMatchObject({ timeout: 15000, maxBuffer: 1500000 });
		expect(Object.keys(options.env)).toEqual(['PATH', 'RUST_LOG']);
		expect(input).toEqual({ path, roots: [root], branch: 'main', snapshot: '' });
		expect(JSON.stringify({ result, input, options })).not.toMatch(
			/never-forward|actor-private|scientist-private-token/
		);
	});

	it('conceals metadata denial and never starts an SDK process without data read authority', async () => {
		const { location } = await storage();
		await expect(
			inspectIcechunk(
				principal(location, { denyMetadata: true }).client,
				'science',
				['one'],
				'temperature'
			)
		).rejects.toMatchObject({ status: 404 });
		const result = await inspectIcechunk(
			principal(location, { denyRead: true }).client,
			'science',
			['one'],
			'temperature'
		);
		expect(result.state).toBe('unavailable');
		expect(result.arrays).toEqual([]);
		expect(mocks.commands).not.toHaveBeenCalled();
	});

	it('discards inspected metadata when read authority is revoked during the process', async () => {
		const { location } = await storage();
		const result = await inspectIcechunk(
			principal(location, { revokeAfterRead: true }).client,
			'science',
			['one'],
			'temperature'
		);
		expect(result.state).toBe('unavailable');
		expect(result.arrays).toEqual([]);
		expect(result.provenance).toBeNull();
		expect(JSON.stringify(result)).not.toContain('Authorized metadata');
	});

	it('does not return an old repository when the Polaris registration changes during inspection', async () => {
		const { location } = await storage();
		const result = await inspectIcechunk(
			principal(location, { changedLocation: 'file:///new-location' }).client,
			'science',
			['one'],
			'temperature'
		);
		expect(result.state).toBe('unavailable');
		expect(result.message).toContain('registration changed');
		expect(result.arrays).toEqual([]);
	});

	it('rejects escaped, symlinked and credential-bearing FILE locations before SDK reads', async () => {
		const { root, path, location } = await storage();
		const outside = await mkdtemp(join(tmpdir(), 'outside-inspector-'));
		folders.push(outside);
		const link = join(root, 'linked');
		await symlink(path, link);
		for (const uri of [
			pathToFileURL(outside).href,
			pathToFileURL(link).href,
			'file://other-host/secret',
			location + '?token=secret',
			location + '#secret'
		]) {
			const result = await inspectIcechunk(
				principal(uri).client,
				'science',
				['one'],
				'temperature'
			);
			expect(result.state).toBe('unavailable');
		}
		expect(mocks.commands).not.toHaveBeenCalled();
	});

	it('reports remote storage inspection honestly without executing a local SDK process', async () => {
		const result = await inspectIcechunk(
			principal('s3://science/repository').client,
			'science',
			['one'],
			'temperature'
		);
		expect(result.storage).toBe('remote');
		expect(result.state).toBe('unavailable');
		expect(mocks.commands).not.toHaveBeenCalled();
	});

	it('sanitizes runtime failures and preserves a real empty initial snapshot', async () => {
		const { location } = await storage();
		mocks.failure = true;
		const failed = await inspectIcechunk(
			principal(location).client,
			'science',
			['one'],
			'temperature'
		);
		expect(failed.state).toBe('unavailable');
		expect(JSON.stringify(failed)).not.toMatch(/private runtime|secret/);
		mocks.failure = false;
		mocks.output = JSON.stringify({
			...inspected,
			arrays: [],
			groups: [],
			message: 'This snapshot contains no Zarr group metadata.'
		});
		const empty = await inspectIcechunk(
			principal(location).client,
			'science',
			['one'],
			'temperature'
		);
		expect(empty.state).toBe('available');
		expect(empty.message).toContain('no Zarr group');
		expect(empty.snapshot?.id).toBe(inspected.snapshot?.id);
	});
});
