import { describe, expect, it, vi } from 'vitest';
import { PolarisClient } from './polaris-client';
import { icebergTable, parseIcebergResponseJson } from './polaris-iceberg';

const metadata = `{
 "metadata-location":"s3://science/table/metadata.json?token=metadata-secret",
 "config":{"token":"oauth-secret","s3.secret-access-key":"storage-secret"},
 "metadata":{
  "format-version":2,"table-uuid":"real-table-uuid","location":"s3://science/table/",
  "properties":{"description":"Measured observations","s3.secret-access-key":"property-secret","unreviewed.setting":"other-secret"},
  "current-schema-id":3,"schemas":[{"schema-id":3,"identifier-field-ids":[1],"fields":[
   {"id":1,"name":"time","required":true,"type":"timestamp"},
   {"id":2,"name":"values","required":false,"type":{"type":"list","element-id":4,"element-required":false,"element":"double"}}
  ]}],
  "current-snapshot-id":9007199254740993,
  "snapshots":[{"snapshot-id":9007199254740993,"parent-snapshot-id":9007199254740992,"timestamp-ms":1704067200000,"schema-id":3,"manifest-list":"s3://science/manifests/one.avro","summary":{"operation":"append","added-records":"24","token":"summary-secret"}}],
  "refs":{"main":{"type":"branch","snapshot-id":9007199254740993}},
  "snapshot-log":[{"timestamp-ms":1704067200000,"snapshot-id":9007199254740993}],
  "metadata-log":[{"timestamp-ms":1704067100000,"metadata-file":"https://user:password@science.test/previous.json?signature=secret"}]
 }
}`;

describe('native Iceberg scientific metadata', () => {
	it('preserves exact int64 snapshot identities and retains actual schema and history', () => {
		const table = icebergTable(parseIcebergResponseJson(metadata), ['science', 'ocean'], 'energy');
		expect(table.format).toBe('iceberg');
		expect(table.currentSnapshotId).toBe('9007199254740993');
		expect(table.snapshots[0].parentSnapshotId).toBe('9007199254740992');
		expect(table.refs.main.snapshotId).toBe('9007199254740993');
		expect(table.snapshotLog[0].snapshotId).toBe('9007199254740993');
		expect(table.schemas[0].fields[1].type).toEqual({
			type: 'list',
			elementId: 4,
			elementRequired: false,
			element: 'double'
		});
	});

	it('excludes response credentials, unknown properties and signed locator secrets', () => {
		const table = icebergTable(parseIcebergResponseJson(metadata), ['science'], 'energy');
		expect(table.properties).toEqual({ description: 'Measured observations' });
		expect(table.metadataLocation).toBe('s3://science/table/metadata.json');
		expect(table.metadataLog[0].metadataFile).toBe('https://science.test/previous.json');
		expect(table.snapshots[0].summary).toEqual({ operation: 'append', 'added-records': '24' });
		expect(JSON.stringify(table)).not.toMatch(/secret|password|config/);
	});

	it('does not rewrite key-shaped text or escaped quotes inside JSON strings', () => {
		const doc =
			'Description with "snapshot-id": 9007199254740993 and slash \\ followed by quotes "".';
		const input = JSON.stringify({ doc }) + '\n';
		expect(parseIcebergResponseJson(input)).toEqual({ doc });
		expect(
			parseIcebergResponseJson('{"snapshot\\u002did":9007199254740993,"timestamp-ms":1234}')
		).toEqual({ 'snapshot-id': '9007199254740993', 'timestamp-ms': 1234 });
	});

	it('refuses already-rounded unsafe identities rather than claiming a different snapshot', () => {
		const value: unknown = JSON.parse(metadata);
		expect(() => icebergTable(value, ['science'], 'energy')).toThrow(
			'unsafe Iceberg metadata integer'
		);
	});

	it('does not repair malformed leading-zero JSON snapshot numbers into valid identities', () => {
		expect(() => parseIcebergResponseJson('{"snapshot-id":09007199254740993}')).toThrow();
	});

	it('lists and loads Iceberg separately without requesting delegated storage credentials', async () => {
		const fetcher = vi.fn<typeof fetch>(async (input) => {
			const url = new URL(String(input));
			if (url.pathname.endsWith('/oauth/tokens')) return Response.json({ access_token: 'token' });
			if (url.pathname.endsWith('/tables/energy'))
				return new Response(metadata, { headers: { 'Content-Type': 'application/json' } });
			return Response.json({
				identifiers: [{ namespace: ['ocean', 'monthly'], name: 'energy' }],
				'next-page-token': 'next-real-page'
			});
		});
		const client = new PolarisClient(
			{
				url: 'http://polaris.test',
				realm: 'POLARIS',
				clientId: 'reader',
				clientSecret: 'reader-secret'
			},
			fetcher
		);
		expect(await client.icebergTables('science', ['ocean', 'monthly'], 'previous-page')).toEqual({
			tables: [{ name: 'energy', namespace: ['ocean', 'monthly'], format: 'iceberg' }],
			nextPageToken: 'next-real-page'
		});
		expect(
			(await client.icebergTable('science', ['ocean', 'monthly'], 'energy')).currentSnapshotId
		).toBe('9007199254740993');
		const reads = fetcher.mock.calls.filter(([input]) => !String(input).endsWith('/oauth/tokens'));
		expect(String(reads[0][0])).toContain(
			'/namespaces/ocean%1Fmonthly/tables?pageSize=100&pageToken=previous-page'
		);
		for (const [, init] of reads)
			expect(new Headers(init?.headers).has('X-Iceberg-Access-Delegation')).toBe(false);
	});
});
