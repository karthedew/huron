import { afterEach, describe, it, expect, vi } from 'vitest';
import { beginRawUpload, RawApiError } from './raw-ingestion-client';
afterEach(() => vi.unstubAllGlobals());
describe('Raw preflight failure responses', () => {
	it('recognizes only an explicit boolean marker that no Raw upload began', async () => {
		vi.stubGlobal(
			'fetch',
			vi.fn(
				async () =>
					new Response(
						JSON.stringify({
							message: 'Select the intended dataset again.',
							uploadNotStarted: true
						}),
						{ status: 409 }
					)
			)
		);
		await expect(
			beginRawUpload(
				{ catalog: 'science', namespace: ['raw'], name: 'new' },
				{ title: 'Title', creators: ['Scientist'] },
				[],
				'key',
				null
			)
		).rejects.toMatchObject({ status: 409, uploadNotStarted: true });
	});
	it('keeps unknown and malformed outcomes uncertain', async () => {
		for (const body of [
			{ message: 'Unavailable' },
			{ message: 'Unavailable', uploadNotStarted: 'true' }
		]) {
			vi.stubGlobal(
				'fetch',
				vi.fn(async () => new Response(JSON.stringify(body), { status: 503 }))
			);
			await expect(
				beginRawUpload(
					{ catalog: 'science', namespace: ['raw'], name: 'new' },
					{ title: 'Title', creators: ['Scientist'] },
					[],
					'key',
					null
				)
			).rejects.toMatchObject({ uploadNotStarted: false });
		}
	});
	it('keeps network failures uncertain rather than asserting that no upload began', async () => {
		vi.stubGlobal(
			'fetch',
			vi.fn(async () => {
				throw new TypeError('Connection reset');
			})
		);
		await expect(
			beginRawUpload(
				{ catalog: 'science', namespace: ['raw'], name: 'new' },
				{ title: 'Title', creators: ['Scientist'] },
				[],
				'key',
				null
			)
		).rejects.not.toBeInstanceOf(RawApiError);
	});
});
