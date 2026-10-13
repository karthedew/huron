import { describe, expect, it } from 'vitest';
import { polarisSettings } from './polaris-settings';

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
});
