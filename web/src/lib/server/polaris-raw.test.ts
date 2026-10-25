import { describe, expect, it, vi } from 'vitest';
import { PolarisClient } from './polaris-client';
import { rawTable } from './polaris-raw';

function clientWith(handler: (url: URL, init?: RequestInit) => Response) {
	const fetcher = vi.fn<typeof fetch>(async (input, init) => {
		const url = new URL(String(input));
		if (url.pathname.endsWith('/oauth/tokens'))
			return Response.json({ access_token: 'private-token', expires_in: 3600 });
		return handler(url, init);
	});
	return {
		client: new PolarisClient(
			{ url: 'http://polaris.test', realm: 'POLARIS', clientId: 'alice', clientSecret: 'secret' },
			fetcher
		),
		fetcher
	};
}

describe('Polaris generic-table projection', () => {
	it('preserves actual registered metadata without credential configurations or signed locators', () => {
		const result = rawTable(
			{
				table: {
					name: 'source_files',
					format: 'parquet',
					'base-location': 'https://user:password@storage.test/files?token=private#private',
					doc: 'ACE downloaded source files',
					properties: {
						'huron.layer': 'bronze',
						'huron.dataset-type': 'table',
						'huron.raw.dataset-id': 'dataset-1',
						'huron.raw.service': 'https://service.test',
						'source.sha256': 'actual-checksum',
						'source.url': 'https://data.test/source?secret=private',
						's3.secret-access-key': 'private-credential'
					}
				},
				'storage-access-configs': [{ config: { token: 'private-token' } }]
			},
			['solar', 'bronze'],
			'source_files'
		);
		expect(result).toMatchObject({
			format: 'raw',
			storageFormat: 'parquet',
			location: 'https://storage.test/files',
			properties: {
				'huron.layer': 'bronze',
				'source.sha256': 'actual-checksum',
				'source.url': 'https://data.test/source'
			}
		});
		expect(Object.keys(result.properties).sort()).toEqual([
			'huron.layer',
			'source.sha256',
			'source.url'
		]);
		expect(JSON.stringify(result)).not.toMatch(/private|password|credentials/);
		expect(result).not.toHaveProperty('files');
		expect(result).not.toHaveProperty('revisions');
	});

	it('decodes every generic format to the same identifier shape', () => {
		for (const storageFormat of ['delta', 'csv', 'parquet'])
			expect(
				rawTable({ table: { name: 'asset', format: storageFormat } }, ['science'], 'asset')
			).toEqual({
				name: 'asset',
				namespace: ['science'],
				format: 'raw',
				storageFormat,
				location: null,
				doc: '',
				properties: {}
			});
		expect(() =>
			rawTable({ table: { name: 'different', format: 'delta' } }, ['science'], 'asset')
		).toThrow();
	});

	it('accepts absent optional location and documentation when Polaris serializes them as null', () => {
		expect(
			rawTable(
				{
					table: {
						name: 'source_files',
						format: 'parquet',
						'base-location': null,
						doc: null,
						properties: null
					}
				},
				['bronze'],
				'source_files'
			)
		).toMatchObject({ location: null, doc: '', properties: {} });
	});

	it('reads actual generic metadata for listed identifiers and keeps undiscoverable metadata concealed', async () => {
		const { client, fetcher } = clientWith((url) => {
			if (url.pathname.endsWith('/generic-tables')) {
				expect(url.searchParams.get('pageToken')).toBe('opaque+/page');
				return Response.json({
					identifiers: ['parquet_files', 'delta_table', 'listed_only'].map((name) => ({
						name,
						namespace: ['Earth.data', 'bronze']
					})),
					'next-page-token': 'opaque-next'
				});
			}
			if (url.pathname.endsWith('/listed_only')) return new Response(null, { status: 403 });
			const name = url.pathname.endsWith('/parquet_files') ? 'parquet_files' : 'delta_table';
			return Response.json({
				table: {
					name,
					format: name === 'parquet_files' ? 'parquet' : 'delta',
					properties: { 'huron.layer': 'bronze' }
				}
			});
		});
		const result = await client.rawTables('NASA science', ['Earth.data', 'bronze'], 'opaque+/page');
		expect(result.tables.map(({ name, storageFormat }) => ({ name, storageFormat }))).toEqual([
			{ name: 'parquet_files', storageFormat: 'parquet' },
			{ name: 'delta_table', storageFormat: 'delta' },
			{ name: 'listed_only', storageFormat: null }
		]);
		expect(result.nextPageToken).toBe('opaque-next');
		expect(result.tables[0].properties).toEqual({ 'huron.layer': 'bronze' });
		for (const [input, init] of fetcher.mock.calls.slice(1)) {
			expect(String(input)).toContain(
				'/NASA%20science/namespaces/Earth.data%1Fbronze/generic-tables'
			);
			expect(new Headers(init?.headers).get('Authorization')).toBe('Bearer private-token');
			expect(new Headers(init?.headers).has('Polaris-Generic-Table-Access-Delegation')).toBe(false);
		}
	});

	it('conceals a direct generic-table denial as not found', async () => {
		const { client } = clientWith(() => new Response(null, { status: 403 }));
		await expect(client.rawTable('science', ['bronze'], 'private')).rejects.toMatchObject({
			status: 404
		});
	});
});
