import { execFile } from 'node:child_process';
import { existsSync } from 'node:fs';
import { lstat, realpath } from 'node:fs/promises';
import { dirname, isAbsolute, relative, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { env } from '$env/dynamic/private';
import type { IcechunkArraySchema, IcechunkInspection, IcechunkSnapshot } from '$api/types';
import { icechunkPath, object, PolarisApiError, type PolarisClient } from './polaris-client';

const LINEAGE_MESSAGE =
	'Icechunk snapshot ancestry and recorded source provenance are available. Scientific derivation lineage is not implemented.';

function unavailable(
	message: string,
	storage: IcechunkInspection['storage'] = 'unknown'
): IcechunkInspection {
	return {
		state: 'unavailable',
		message,
		storage,
		selectedBranch: null,
		branches: [],
		tags: [],
		snapshot: null,
		groups: [],
		arrays: [],
		history: [],
		historyNextSnapshotId: null,
		provenance: null,
		lineage: { state: 'unavailable', message: LINEAGE_MESSAGE },
		truncated: false,
		redacted: false,
		limits: { references: 100, history: 100, schema: 200 }
	};
}

function repositoryRoot(): string {
	let directory = dirname(fileURLToPath(import.meta.url));
	while (directory !== dirname(directory)) {
		if (
			existsSync(resolve(directory, 'scripts/inspect_icechunk.py')) &&
			existsSync(resolve(directory, 'web/package.json'))
		)
			return directory;
		directory = dirname(directory);
	}
	throw new Error('Icechunk inspection runtime is unavailable.');
}

function settings() {
	const root = repositoryRoot();
	const web = resolve(root, 'web');
	const configured = env.HURON_ICECHUNK_READ_ROOTS;
	let roots: unknown = configured?.trim().startsWith('[')
		? JSON.parse(configured)
		: configured?.split(':').filter(Boolean);
	if (roots === undefined)
		roots = [resolve(root, '.local/polaris/nasa-storage'), resolve(root, '.local/polaris/storage')];
	if (
		!Array.isArray(roots) ||
		!roots.length ||
		roots.length > 32 ||
		roots.some((entry) => typeof entry !== 'string' || !entry.trim())
	)
		throw new Error('Invalid local Icechunk read roots.');
	return {
		python: resolve(web, env.HURON_ICECHUNK_PYTHON || '../.local/polaris/icechunk-venv/bin/python'),
		helper: resolve(root, 'scripts/inspect_icechunk.py'),
		roots: roots.map((entry: string) => resolve(web, entry))
	};
}

function inside(path: string, root: string): boolean {
	const suffix = relative(root, path);
	return (
		suffix === '' || (!suffix.startsWith(`..${sep}`) && suffix !== '..' && !isAbsolute(suffix))
	);
}

async function localPath(
	location: string,
	roots: string[]
): Promise<{ path: string; roots: string[] }> {
	const url = new URL(location);
	if (
		url.protocol !== 'file:' ||
		(url.hostname && url.hostname !== 'localhost') ||
		url.username ||
		url.password ||
		url.search ||
		url.hash
	)
		throw new Error('Unsafe repository URL.');
	const path = fileURLToPath(url);
	if (!isAbsolute(path) || path.includes('\0')) throw new Error('Unsafe repository path.');
	const approved: { original: string; canonical: string }[] = [];
	for (const root of roots) {
		try {
			approved.push({ original: root, canonical: await realpath(root) });
		} catch (error) {
			if (!(error instanceof Error && 'code' in error && error.code === 'ENOENT')) throw error;
		}
	}
	for (const root of approved) {
		const matched = inside(path, root.original)
			? root.original
			: inside(path, root.canonical)
				? root.canonical
				: null;
		if (!matched) continue;
		let current = matched;
		for (const part of relative(matched, path).split(sep).filter(Boolean)) {
			current = resolve(current, part);
			if ((await lstat(current)).isSymbolicLink())
				throw new Error('Repository symlinks are not permitted.');
		}
		const canonical = await realpath(path);
		if (!inside(canonical, root.canonical) || !(await lstat(canonical)).isDirectory())
			throw new Error('Unsafe repository path.');
		return { path: canonical, roots: approved.map((root) => root.canonical) };
	}
	throw new Error('Repository is outside configured local read roots.');
}

function text(value: unknown): string {
	if (typeof value !== 'string') throw new Error('Invalid inspector response.');
	return value;
}
function nullableText(value: unknown): string | null {
	return value === null ? null : text(value);
}
function numbers(value: unknown): number[] {
	if (
		!Array.isArray(value) ||
		value.some((entry) => !Number.isSafeInteger(entry) || Number(entry) < 0)
	)
		throw new Error('Invalid inspector dimensions.');
	return value.map(Number);
}
function entries<T>(value: unknown, decode: (entry: unknown) => T): T[] {
	if (!Array.isArray(value)) throw new Error('Invalid inspector collection.');
	return value.map(decode);
}
function snapshot(value: unknown): IcechunkSnapshot {
	const entry = object(value);
	const writtenAt = new Date(text(entry.writtenAt));
	if (!Number.isFinite(writtenAt.getTime())) throw new Error('Invalid snapshot timestamp.');
	return {
		id: text(entry.id),
		parentId: nullableText(entry.parentId),
		writtenAt: writtenAt.toISOString(),
		message: text(entry.message),
		metadata: object(entry.metadata)
	};
}
function array(value: unknown): IcechunkArraySchema {
	const entry = object(value);
	return {
		path: text(entry.path),
		dtype: text(entry.dtype),
		shape: numbers(entry.shape),
		chunks: numbers(entry.chunks),
		dimensions: entries(entry.dimensions, nullableText),
		attributes: object(entry.attributes)
	};
}
function decode(value: unknown): IcechunkInspection {
	const entry = object(value);
	if (entry.error === 'reference-not-found')
		throw new PolarisApiError(404, 'Icechunk branch or snapshot not found.');
	if (entry.error === 'not-initialized')
		return unavailable(
			'This registered location does not contain an initialized Icechunk repository.',
			'FILE'
		);
	if (entry.error === 'no-zarr-group')
		return unavailable('This Icechunk snapshot contains no Zarr group metadata.', 'FILE');
	if (entry.error || entry.state !== 'available')
		return unavailable('Repository metadata could not be inspected safely.', 'FILE');
	const reference = (value: unknown) => {
		const row = object(value);
		return { name: text(row.name), snapshotId: text(row.snapshotId) };
	};
	const provenance = entry.provenance === null ? null : object(entry.provenance);
	return {
		state: 'available',
		message: nullableText(entry.message),
		storage: 'FILE',
		selectedBranch: nullableText(entry.selectedBranch),
		branches: entries(entry.branches, reference),
		tags: entries(entry.tags, reference),
		snapshot: entry.snapshot === null ? null : snapshot(entry.snapshot),
		groups: entries(entry.groups, (value) => {
			const row = object(value);
			return { path: text(row.path), attributes: object(row.attributes) };
		}),
		arrays: entries(entry.arrays, array),
		history: entries(entry.history, snapshot),
		historyNextSnapshotId: nullableText(entry.historyNextSnapshotId),
		provenance: provenance
			? {
					importReceipt:
						provenance.importReceipt === null ? null : object(provenance.importReceipt),
					source: object(provenance.source)
				}
			: null,
		lineage: { state: 'unavailable', message: LINEAGE_MESSAGE },
		truncated: entry.truncated === true,
		redacted: entry.redacted === true,
		limits: { references: 100, history: 100, schema: 200 }
	};
}

function inspectLocal(
	configuration: ReturnType<typeof settings>,
	path: string,
	roots: string[],
	branch: string,
	snapshotId: string
): Promise<unknown> {
	return new Promise((accept, reject) => {
		const child = execFile(
			configuration.python,
			['-I', configuration.helper],
			{
				timeout: 15_000,
				maxBuffer: 1_500_000,
				encoding: 'utf8',
				env: { PATH: process.env.PATH || '/usr/bin:/bin', RUST_LOG: 'off' }
			},
			(error, stdout) => {
				if (error) {
					reject(new Error('Local metadata inspection runtime failed.'));
					return;
				}
				try {
					const result: unknown = JSON.parse(stdout);
					accept(result);
				} catch {
					reject(new Error('Invalid local metadata response.'));
				}
			}
		);
		child.stdin?.end(JSON.stringify({ path, roots, branch, snapshot: snapshotId }));
	});
}

/** Read as the current Polaris principal before starting the fixed local metadata helper. */
export async function inspectIcechunk(
	client: PolarisClient,
	catalog: string,
	namespace: string[],
	tableName: string,
	branch = '',
	snapshotId = ''
): Promise<IcechunkInspection> {
	const table = await client.table(catalog, namespace, tableName);
	try {
		await client.request(
			icechunkPath(catalog, namespace, tableName) + '/credentials?access-mode=read',
			'GET'
		);
	} catch (error) {
		if (error instanceof PolarisApiError && (error.status === 403 || error.status === 404))
			return unavailable(
				'Your Polaris grants do not permit reading this repository’s stored metadata.'
			);
		throw error;
	}
	if (!table.location.startsWith('file:'))
		return unavailable(
			'Stored schema and snapshot inspection requires an approved local FILE repository. Remote storage inspection is not configured.',
			'remote'
		);
	if (
		branch.length > 256 ||
		/[\x00-\x1f\x7f]/.test(branch) ||
		(snapshotId && !/^[A-Z0-9]{20}$/.test(snapshotId))
	)
		throw new PolarisApiError(404, 'Icechunk branch or snapshot not found.');
	try {
		const configuration = settings();
		const location = await localPath(table.location, configuration.roots);
		const result = decode(
			await inspectLocal(configuration, location.path, location.roots, branch, snapshotId)
		);
		if (result.state === 'available') {
			const current = await client.table(catalog, namespace, tableName);
			if (current.location !== table.location)
				return unavailable(
					'The repository registration changed during inspection. Refresh to read its current location.',
					'FILE'
				);
			try {
				await client.request(
					icechunkPath(catalog, namespace, tableName) + '/credentials?access-mode=read',
					'GET'
				);
			} catch (error) {
				if (error instanceof PolarisApiError && (error.status === 403 || error.status === 404))
					return unavailable(
						'Your Polaris grants no longer permit reading this repository’s stored metadata.'
					);
				throw error;
			}
		}
		return result;
	} catch (error) {
		if (error instanceof PolarisApiError && error.status === 404) throw error;
		return unavailable(
			'Stored metadata inspection is unavailable for this location or server runtime. The repository must be inside an approved local root without symlinks.',
			'FILE'
		);
	}
}
