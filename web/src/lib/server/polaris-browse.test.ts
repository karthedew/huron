import { describe, expect, it, vi } from 'vitest';
import type { PolarisCatalog } from '$api/types';
import { branchFolders, browseHref, selectCatalog } from '$lib/stores/workspace';
import { PolarisClient } from './polaris-client';
import { loadPolarisBrowse, searchCatalogs } from './polaris-browse';

const catalogs: PolarisCatalog[] = [
	{
		name: 'NASA science',
		type: 'INTERNAL',
		properties: { description: 'Earth observations', 'default-base-location': 'file:///science/' },
		storageConfigInfo: { storageType: 'FILE' }
	},
	{
		name: 'Ocean.catalog',
		type: 'INTERNAL',
		properties: { description: 'Ocean temperatures' },
		storageConfigInfo: { storageType: 'S3' }
	}
];
const settings = { url: 'http://127.0.0.1:8181', realm: 'POLARIS' };

function clientWith(handler: (url: URL) => Response) {
	const fetcher = vi.fn<typeof fetch>(async (input) => {
		const url = new URL(String(input));
		if (url.pathname.endsWith('/oauth/tokens'))
			return Response.json({ access_token: 'private-token', expires_in: 3600 });
		return handler(url);
	});
	const client = new PolarisClient(
		{ ...settings, clientId: 'scientist', clientSecret: 'private-secret' },
		fetcher
	);
	return { client, fetcher };
}

describe('Authenticated Polaris catalog navigation', () => {
	it('keeps arbitrary catalog names and multipart namespaces intact in stable URLs', () => {
		const url = new URL(
			browseHref('Ocean.catalog & maps', ['Climate.data', 'daily observations'], 'temp+salinity'),
			'http://localhost'
		);
		expect(url.searchParams.get('catalog')).toBe('Ocean.catalog & maps');
		expect(JSON.parse(url.searchParams.get('namespace') ?? '')).toEqual([
			'Climate.data',
			'daily observations'
		]);
		expect(url.searchParams.get('table')).toBe('temp+salinity');
		expect(browseHref('')).toBe('/browse');
	});

	it('selects only a catalog disclosed in the current response without a shared default identity', () => {
		expect(selectCatalog(catalogs, 'Ocean.catalog')).toBe('Ocean.catalog');
		expect(selectCatalog(catalogs, 'private')).toBe('NASA science');
		expect(selectCatalog([], 'NASA science')).toBe('');
	});

	it('searches disclosed names, storage types and catalog properties', () => {
		expect(searchCatalogs(catalogs, 'earth').map((entry) => entry.name)).toEqual(['NASA science']);
		expect(searchCatalogs(catalogs, ' s3 ').map((entry) => entry.name)).toEqual(['Ocean.catalog']);
		expect(searchCatalogs(catalogs, '')).toEqual(catalogs);
		expect(searchCatalogs([], 'NASA')).toEqual([]);
	});
});

describe('Polaris browse server projection', () => {
	it('browses generic, Icechunk and Iceberg assets together using their native identifiers and pagination', async () => {
		const { client } = clientWith((url) => {
			if (url.pathname.endsWith('/generic-tables/source_files'))
				return Response.json({
					table: {
						name: 'source_files',
						format: 'parquet',
						'base-location': 'file:///science/raw/ace',
						properties: { 'huron.layer': 'bronze' }
					}
				});
			if (url.pathname.endsWith('/generic-tables')) {
				expect(url.searchParams.get('pageToken')).toBe('raw/current');
				return Response.json({
					identifiers: [{ name: 'source_files', namespace: ['bronze'] }],
					'next-page-token': 'raw/next'
				});
			}
			if (url.pathname.endsWith('/icechunk-tables'))
				return Response.json({ identifiers: [{ name: 'observations', namespace: ['bronze'] }] });
			if (url.pathname.endsWith('/tables'))
				return Response.json({ identifiers: [{ name: 'summary', namespace: ['bronze'] }] });
			if (url.pathname.endsWith('/namespaces')) return Response.json({ namespaces: [] });
			return Response.json({ properties: {} });
		});
		const data = await loadPolarisBrowse(
			client,
			catalogs,
			new URL(
				'http://localhost/browse?catalog=NASA+science&namespace=%5B%22bronze%22%5D&table=source_files&format=generic&genericPageToken=raw%2Fcurrent'
			),
			settings
		);
		expect(data.loadedGenericTable).toMatchObject({
			name: 'source_files',
			format: 'generic',
			storageFormat: 'parquet'
		});
		expect(data.loadedTable).toBeNull();
		expect(data.loadedIcebergTable).toBeNull();
		expect(data.genericTables[0].properties).toEqual({ 'huron.layer': 'bronze' });
		expect(data.branches.at(-1)?.repositories.map((entry) => entry.name)).toEqual([
			'observations',
			'summary',
			'source_files'
		]);
		expect(data.branches.at(-1)).toMatchObject({
			genericPageToken: 'raw/current',
			nextGenericPageToken: 'raw/next'
		});
	});

	it('keeps an exact generic asset readable when its namespace listing is undiscoverable', async () => {
		const { client } = clientWith((url) =>
			url.pathname.endsWith('/generic-tables/source_files')
				? Response.json({ table: { name: 'source_files', format: 'parquet' } })
				: new Response(null, { status: 403 })
		);
		const data = await loadPolarisBrowse(
			client,
			catalogs,
			new URL(
				'http://localhost/browse?catalog=NASA+science&namespace=%5B%22bronze%22%5D&table=source_files&format=generic'
			),
			settings
		);
		expect(data.loadedGenericTable?.name).toBe('source_files');
		expect(data.errors.genericTables).toBe('Resource not found.');
		expect(data.namespaces).toEqual([]);
	});

	it.each(['branch=main', 'snapshot=revision-1'])(
		'rejects unsupported generic-table version selectors instead of implying a published revision: %s',
		async (selection) => {
			const { client } = clientWith(() =>
				Response.json({ table: { name: 'source_files', format: 'parquet' } })
			);
			await expect(
				loadPolarisBrowse(
					client,
					catalogs,
					new URL(
						`http://localhost/browse?catalog=NASA+science&namespace=%5B%22bronze%22%5D&table=source_files&format=generic&${selection}`
					),
					settings
				)
			).rejects.toMatchObject({ status: 404 });
		}
	);

	it.each(['branch=missing', 'branch=baseline', 'snapshot=2'])(
		'rejects invalid Iceberg selections instead of falling back to current metadata: %s',
		async (selection) => {
			const { client } = clientWith(() =>
				Response.json({
					metadata: {
						location: 'file:///science/observations',
						'format-version': 2,
						'current-schema-id': 0,
						'current-snapshot-id': 1,
						schemas: [],
						snapshots: [{ 'snapshot-id': 1, 'timestamp-ms': 1 }],
						refs: {
							main: { type: 'branch', 'snapshot-id': 1 },
							baseline: { type: 'tag', 'snapshot-id': 1 }
						}
					}
				})
			);
			await expect(
				loadPolarisBrowse(
					client,
					catalogs,
					new URL(
						`http://localhost/browse?catalog=NASA+science&namespace=%5B%22climate%22%5D&table=observations&format=iceberg&${selection}`
					),
					settings
				)
			).rejects.toMatchObject({ status: 404 });
		}
	);

	it('loads nested namespaces, repository metadata and pagination through the current principal only', async () => {
		const { client, fetcher } = clientWith((url) => {
			expect(url.pathname).not.toContain('/management/');
			expect(decodeURIComponent(url.pathname)).toContain('/NASA science/');
			if (url.pathname.endsWith('/namespaces')) {
				if (!url.searchParams.has('parent')) return Response.json({ namespaces: [['climate']] });
				if (url.searchParams.get('parent') === 'climate')
					return Response.json({ namespaces: [['climate', 'daily']] });
				expect(url.searchParams.get('parent')).toBe('climate\x1fdaily');
				expect(url.searchParams.get('pageToken')).toBe('child/page');
				return Response.json({
					namespaces: [['climate', 'daily', 'next']],
					'next-page-token': 'child/next'
				});
			}
			if (url.pathname.endsWith('/tables')) return Response.json({ identifiers: [] });
			if (url.pathname.endsWith('/generic-tables')) return Response.json({ identifiers: [] });
			if (url.pathname.endsWith('/icechunk-tables')) {
				if (url.pathname.includes('/namespaces/climate/'))
					return Response.json({ identifiers: [] });
				expect(url.searchParams.get('pageToken')).toBe('repo/page');
				return Response.json({
					identifiers: [{ namespace: ['climate', 'daily'], name: 'temperature' }],
					'next-page-token': 'repo/next'
				});
			}
			if (url.pathname.endsWith('/temperature'))
				return Response.json({
					table: {
						name: 'temperature',
						location: 's3://data/repo',
						properties: { variable: 'temperature' }
					},
					'storage-access-configs': [{ config: { 's3.secret-access-key': 'never-display' } }]
				});
			return Response.json({ properties: { description: 'Daily climate' } });
		});
		const url = new URL(
			browseHref('NASA science', ['climate', 'daily'], 'temperature'),
			'http://localhost'
		);
		url.searchParams.set('pageToken', 'repo/page');
		url.searchParams.set('namespacePageToken', 'child/page');
		const data = await loadPolarisBrowse(client, catalogs, url, settings);
		expect(data.catalog?.name).toBe('NASA science');
		expect(data.namespaces).toEqual([['climate', 'daily', 'next']]);
		expect(data.tables[0].name).toBe('temperature');
		expect(data.loadedTable?.properties.variable).toBe('temperature');
		expect(data.nextNamespacePageToken).toBe('child/next');
		expect(data.nextPageToken).toBe('repo/next');
		expect(data.principals).toEqual([]);
		expect(JSON.stringify(data)).not.toContain('never-display');
		expect(JSON.stringify(data)).not.toContain('private-token');
		expect(data.branches.map((branch) => branch.namespace)).toEqual([
			[],
			['climate'],
			['climate', 'daily']
		]);
		expect(data.branches[0].folders).toEqual([['climate']]);
		expect(data.branches[1].folders).toEqual([['climate', 'daily']]);
		expect(data.branches[2].repositoryPageToken).toBe('repo/page');
		expect(fetcher.mock.calls).toHaveLength(12);
	});

	it('lists an organization root without implicitly selecting or loading its first catalog', async () => {
		const { client, fetcher } = clientWith(() => Response.json({}));
		const data = await loadPolarisBrowse(
			client,
			catalogs,
			new URL('http://localhost/browse?organization=research'),
			settings
		);
		expect(data.catalogs).toEqual(catalogs);
		expect(data.catalog).toBeNull();
		expect(data.selected.catalog).toBe('');
		expect(data.branches).toEqual([]);
		expect(fetcher).not.toHaveBeenCalled();
	});

	it('returns an empty workspace for an account without catalog membership', async () => {
		const { client, fetcher } = clientWith(() => Response.json({}));
		const data = await loadPolarisBrowse(client, [], new URL('http://localhost/browse'), settings);
		expect(data.catalogs).toEqual([]);
		expect(data.selected.catalog).toBe('');
		expect(fetcher).not.toHaveBeenCalled();
	});

	it('loads native Iceberg metadata under its explicit format without an Icechunk table read', async () => {
		const { client, fetcher } = clientWith((url) => {
			if (url.pathname.endsWith('/tables/observations'))
				return Response.json({
					metadata: {
						'format-version': 2,
						location: 's3://science/observations/',
						'current-schema-id': 0,
						'current-snapshot-id': 42,
						schemas: [
							{
								'schema-id': 0,
								fields: [{ id: 1, name: 'temperature', required: false, type: 'double' }]
							}
						],
						snapshots: [
							{
								'snapshot-id': 42,
								'timestamp-ms': 1704067200000,
								'schema-id': 0,
								summary: { operation: 'append' }
							}
						],
						refs: { main: { type: 'branch', 'snapshot-id': 42 } }
					}
				});
			if (url.pathname.endsWith('/tables'))
				return Response.json({ identifiers: [{ namespace: ['climate'], name: 'observations' }] });
			if (url.pathname.endsWith('/icechunk-tables')) return Response.json({ identifiers: [] });
			if (url.pathname.endsWith('/generic-tables')) return Response.json({ identifiers: [] });
			if (url.pathname.endsWith('/namespaces')) return Response.json({ namespaces: [] });
			return Response.json({ properties: {} });
		});
		const url = new URL(
			browseHref('NASA science', ['climate'], 'observations'),
			'http://localhost'
		);
		url.searchParams.set('format', 'iceberg');
		const data = await loadPolarisBrowse(client, catalogs, url, settings);
		expect(data.loadedTable).toBeNull();
		expect(data.loadedIcebergTable?.schemas[0].fields[0].name).toBe('temperature');
		expect(data.loadedIcebergTable?.currentSnapshotId).toBe('42');
		expect(data.branches.at(-1)?.repositories).toEqual([
			{ name: 'observations', namespace: ['climate'], format: 'iceberg' }
		]);
		expect(
			fetcher.mock.calls.some(([input]) => String(input).includes('/icechunk-tables/observations'))
		).toBe(false);
	});

	it('opens an authorized exact repository when namespace properties and lists are undiscoverable', async () => {
		const { client } = clientWith((url) => {
			if (url.pathname.endsWith('/temperature'))
				return Response.json({
					table: {
						name: 'temperature',
						location: 's3://data/repo',
						properties: { variable: 'temperature' }
					}
				});
			return Response.json({ message: 'PRIVATE' }, { status: 403 });
		});
		const data = await loadPolarisBrowse(
			client,
			catalogs,
			new URL(browseHref('NASA science', ['climate'], 'temperature'), 'http://localhost'),
			settings
		);
		expect(data.loadedTable?.name).toBe('temperature');
		expect(data.loadedTable?.properties.variable).toBe('temperature');
		expect(data.namespaceProperties).toBeNull();
		expect(data.namespaces).toEqual([]);
		expect(data.tables).toEqual([]);
		expect(Object.keys(data.errors).sort()).toEqual([
			'genericTables',
			'icebergTables',
			'namespaceProperties',
			'namespaces',
			'tables'
		]);
		expect(JSON.stringify(data)).not.toContain('PRIVATE');
		expect(branchFolders(data.branches[0], data.selected.namespace)).toEqual([['climate']]);
	});

	it('conceals an inaccessible catalog deep link without querying a guessed name', async () => {
		const { client, fetcher } = clientWith(() => Response.json({}));
		await expect(
			loadPolarisBrowse(
				client,
				catalogs,
				new URL('http://localhost/browse?catalog=private'),
				settings
			)
		).rejects.toMatchObject({ status: 404 });
		expect(fetcher).not.toHaveBeenCalled();
	});

	it.each(['namespace', 'repository'])(
		'conceals an inaccessible direct %s selection as not found',
		async (selection) => {
			const { client } = clientWith((url) => {
				if (selection === 'namespace' || url.pathname.endsWith('/hidden'))
					return Response.json({ message: 'PRIVATE' }, { status: 403 });
				if (url.pathname.endsWith('/namespaces')) return Response.json({ namespaces: [] });
				if (url.pathname.endsWith('/icechunk-tables')) return Response.json({ identifiers: [] });
				return Response.json({ properties: {} });
			});
			await expect(
				loadPolarisBrowse(
					client,
					catalogs,
					new URL(
						browseHref('NASA science', ['climate'], selection === 'repository' ? 'hidden' : ''),
						'http://localhost'
					),
					settings
				)
			).rejects.toMatchObject({ status: 404, message: 'Resource not found.' });
		}
	);

	it('rejects unsupported browse selections before reading upstream metadata', async () => {
		const { client, fetcher } = clientWith(() => Response.json({}));
		await expect(
			loadPolarisBrowse(
				client,
				catalogs,
				new URL('http://localhost/browse?catalog=NASA+science&namespace=bad'),
				settings
			)
		).rejects.toMatchObject({ status: 400 });
		const url = new URL('http://localhost/browse?catalog=NASA+science');
		url.searchParams.set('format', 'raw');
		await expect(loadPolarisBrowse(client, catalogs, url, settings)).rejects.toMatchObject({
			status: 400,
			message: 'Choose a supported table format.'
		});
		expect(fetcher).not.toHaveBeenCalled();
	});
});
