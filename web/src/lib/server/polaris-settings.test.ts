import { describe, expect, it } from 'vitest';
import {
	polarisConfiguredConnection,
	polarisRealms,
	polarisRealmSettings,
	polarisSettings
} from './polaris-settings';

describe('server Polaris deployment configuration', () => {
	it('uses the configured origin and realm and leaves configuration unchanged', () => {
		const configuration = Object.freeze({
			POLARIS_URL: 'https://catalog.example:8181/',
			POLARIS_REALM: 'science'
		});
		expect(polarisSettings(configuration)).toEqual({
			url: 'https://catalog.example:8181',
			realm: 'science'
		});
		expect(polarisSettings({})).toEqual({ url: 'http://127.0.0.1:8181', realm: 'POLARIS' });
	});

	it.each([
		'invalid',
		'file:///repo',
		'https://name:secret@catalog.example',
		'https://catalog.example/api',
		'https://catalog.example?token=secret',
		'https://catalog.example#fragment'
	])('rejects invalid or credential-bearing Polaris origins %s', (POLARIS_URL) => {
		expect(() => polarisSettings({ POLARIS_URL })).toThrow('POLARIS_URL');
	});

	it.each(['', ' ', 'realm\r\nInjected: header'])(
		'rejects an empty or malformed realm %s',
		(POLARIS_REALM) => {
			expect(() => polarisSettings({ POLARIS_REALM })).toThrow('POLARIS_REALM');
		}
	);

	it('lists configured roots without credentials and resolves only explicit registered realms', () => {
		const extra = {
			url: 'https://lab.example/',
			realm: 'LAB',
			clientId: 'lab-root',
			clientSecret: 'lab-private'
		};
		const configuration = { POLARIS_CONNECTIONS_JSON: JSON.stringify([extra]) };
		expect(polarisRealms(configuration)).toEqual([
			{ url: 'http://127.0.0.1:8181', realm: 'POLARIS' },
			{ url: 'https://lab.example', realm: 'LAB' }
		]);
		expect(polarisConfiguredConnection('LAB', configuration)).toEqual({
			...extra,
			url: 'https://lab.example'
		});
		expect(polarisConfiguredConnection('POLARIS', configuration)).toBeNull();
		expect(() => polarisRealmSettings('UNKNOWN', configuration)).toThrow('not configured');
		expect(() => polarisConfiguredConnection('UNKNOWN', configuration)).toThrow('not configured');
	});

	it.each(['{', '{}', '[null]', '[{"realm":"LAB"}]'])(
		'rejects malformed realm registry %s',
		(POLARIS_CONNECTIONS_JSON) => {
			expect(() => polarisRealms({ POLARIS_CONNECTIONS_JSON })).toThrow();
		}
	);

	it('rejects duplicate realm names and conflicting default origins', () => {
		const entry = {
			url: 'https://lab.example',
			realm: 'LAB',
			clientId: 'id',
			clientSecret: 'secret'
		};
		expect(() =>
			polarisRealms({ POLARIS_CONNECTIONS_JSON: JSON.stringify([entry, entry]) })
		).toThrow('only once');
		expect(() =>
			polarisRealms({
				POLARIS_CONNECTIONS_JSON: JSON.stringify([{ ...entry, realm: 'POLARIS' }])
			})
		).toThrow('POLARIS_URL');
	});
});
