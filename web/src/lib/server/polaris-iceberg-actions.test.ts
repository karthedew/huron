import { describe, expect, it, vi } from 'vitest';
import { PolarisClient } from './polaris-client';
import { registerIcebergTable } from './polaris-iceberg-actions';

function form(): FormData {
	const value = new FormData();
	value.set('catalog', 'Earth science');
	value.set('namespace', '["ocean","gold"]');
	value.set('name', 'summary');
	value.set('metadataLocation', 's3://science/summary/metadata/v1.metadata.json');
	return value;
}

function clientWith(status = 200) {
	const fetcher = vi.fn<typeof fetch>(async (input) => {
		if (String(input).endsWith('/oauth/tokens'))
			return Response.json({ access_token: 'own-token' });
		return Response.json({ metadata: {} }, { status });
	});
	return {
		client: new PolarisClient(
			{ url: 'http://polaris.test', realm: 'POLARIS', clientId: 'alice', clientSecret: 'secret' },
			fetcher
		),
		fetcher
	};
}

describe('Native Iceberg metadata registration', () => {
	it('uses the native register operation with the user’s token and replacement disabled', async () => {
		const { client, fetcher } = clientWith();
		const result = await registerIcebergTable(client, form());
		expect(result.success).toBe(true);
		const [url, request] = fetcher.mock.calls[1];
		expect(String(url)).toBe(
			'http://polaris.test/api/catalog/v1/Earth%20science/namespaces/ocean%1Fgold/register'
		);
		expect(request?.method).toBe('POST');
		expect(new Headers(request?.headers).get('Authorization')).toBe('Bearer own-token');
		expect(JSON.parse(String(request?.body))).toEqual({
			name: 'summary',
			'metadata-location': 's3://science/summary/metadata/v1.metadata.json',
			overwrite: false
		});
	});

	it.each([
		'',
		's3://user:secret@science/metadata.json',
		'https://data.test/metadata.json?token=secret'
	])(
		'rejects missing or credential-bearing metadata locators before contacting Polaris: %s',
		async (metadataLocation) => {
			const { client, fetcher } = clientWith();
			const fields = form();
			fields.set('metadataLocation', metadataLocation);
			await expect(registerIcebergTable(client, fields)).rejects.toMatchObject({ status: 400 });
			expect(fetcher).not.toHaveBeenCalled();
		}
	);

	it.each([403, 409, 406])(
		'preserves Polaris permission, conflict and capability failures: %s',
		async (status) => {
			const { client } = clientWith(status);
			await expect(registerIcebergTable(client, form())).rejects.toMatchObject({ status });
		}
	);
});
