import { describe, expect, it, vi } from 'vitest';
import { genericTablePath, PolarisClient } from './polaris-client';
import { rawTable } from './polaris-raw';
import { registerRawTable } from './polaris-raw-actions';

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

describe('Polaris generic-table Raw projection', () => {
	it('preserves actual registered metadata without credential configurations or signed locators', () => {
		const result = rawTable(
			{
				table: {
					name: 'source_files',
					format: 'raw',
					'base-location': 'https://user:password@storage.test/files?token=private#private',
					doc: 'ACE downloaded source files',
					properties: {
						'huron.layer': 'bronze',
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
			storageFormat: 'raw',
			isRaw: true,
			location: 'https://storage.test/files',
			properties: { 'huron.layer': 'bronze', 'source.sha256': 'actual-checksum' }
		});
		expect(result.properties['source.url']).toBe('https://data.test/source');
		expect(JSON.stringify(result)).not.toMatch(/private|password|credentials/);
		expect(result).not.toHaveProperty('files');
		expect(result).not.toHaveProperty('revisions');
	});

	it('keeps arbitrary generic formats distinct from recognized Raw collections', () => {
		expect(rawTable({ table: { name: 'asset', format: 'delta' } }, ['science'], 'asset')).toEqual({
			name: 'asset',
			namespace: ['science'],
			format: 'raw',
			storageFormat: 'delta',
			isRaw: false,
			location: null,
			doc: '',
			properties: {}
		});
		expect(
			rawTable(
				{ table: { name: 'asset', format: 'csv', properties: { 'huron.dataset-type': 'raw' } } },
				['science'],
				'asset'
			).isRaw
		).toBe(true);
		expect(() =>
			rawTable({ table: { name: 'different', format: 'raw' } }, ['science'], 'asset')
		).toThrow();
	});

	it('accepts absent optional location and documentation when Polaris serializes them as null', () => {
		expect(
			rawTable(
				{
					table: {
						name: 'source_files',
						format: 'raw',
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
					identifiers: ['raw_files', 'delta_table', 'listed_only'].map((name) => ({
						name,
						namespace: ['Earth.data', 'bronze']
					})),
					'next-page-token': 'opaque-next'
				});
			}
			if (url.pathname.endsWith('/listed_only')) return new Response(null, { status: 403 });
			const name = url.pathname.endsWith('/raw_files') ? 'raw_files' : 'delta_table';
			return Response.json({
				table: {
					name,
					format: name === 'raw_files' ? 'raw' : 'delta',
					properties: { 'huron.layer': 'bronze' }
				}
			});
		});
		const result = await client.rawTables('NASA science', ['Earth.data', 'bronze'], 'opaque+/page');
		expect(
			result.tables.map(({ name, storageFormat, isRaw }) => ({ name, storageFormat, isRaw }))
		).toEqual([
			{ name: 'raw_files', storageFormat: 'raw', isRaw: true },
			{ name: 'delta_table', storageFormat: 'delta', isRaw: false },
			{ name: 'listed_only', storageFormat: null, isRaw: null }
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

function registrationForm(): FormData {
	const form = new FormData();
	form.set('catalog', 'science');
	form.set('namespace', '["solar","bronze"]');
	form.set('name', 'source_files');
	form.set('location', 'file:///science/raw/ace');
	form.set('doc', 'ACE original source files');
	return form;
}

describe('Raw collection registration', () => {
	it('persists a genuine generic registration and matching layer without claiming an upload', async () => {
		const { client } = clientWith((url, init) => {
			expect(url.pathname).toBe(genericTablePath('science', ['solar', 'bronze']));
			expect(init?.method).toBe('POST');
			expect(JSON.parse(String(init?.body))).toEqual({
				name: 'source_files',
				format: 'raw',
				'base-location': 'file:///science/raw/ace',
				doc: 'ACE original source files',
				properties: { 'huron.dataset-type': 'raw', 'huron.layer': 'bronze' }
			});
			return Response.json({ table: { name: 'source_files', format: 'raw' } });
		});
		const result = await registerRawTable(client, registrationForm());
		expect(result.success).toBe(true);
		expect(result.message).toContain('No files were uploaded and no Raw revision was published');
	});

	it.each([
		['layer', 'silver'],
		['properties', '{"huron.layer":"platinum"}'],
		['location', 's3://user:secret@bucket/path'],
		['location', 'https://example.com/objects?signature=secret']
	])('rejects invalid %s before sending any mutation', async (key, value) => {
		const { client, fetcher } = clientWith(() => Response.json({}));
		const form = registrationForm();
		form.set(key, value);
		await expect(registerRawTable(client, form)).rejects.toMatchObject({ status: 400 });
		expect(fetcher).not.toHaveBeenCalled();
	});

	it('preserves upstream conflict and permission failures without reporting success', async () => {
		const { client } = clientWith(() => new Response(null, { status: 409 }));
		await expect(registerRawTable(client, registrationForm())).rejects.toMatchObject({
			status: 409
		});
	});
});
