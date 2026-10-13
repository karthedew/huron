/** The worker receives an immutable Blob handle, never a whole-file byte buffer. */
export function hashFile(file: File, progress: (bytes: number) => void): Promise<string> {
	return new Promise((resolve, reject) => {
		const worker = new Worker(new URL('./hash.worker.ts', import.meta.url), { type: 'module' });
		worker.onmessage = (event: MessageEvent<unknown>) => {
			const message = event.data;
			if (!message || typeof message !== 'object') return;
			if ('bytes' in message && typeof message.bytes === 'number') progress(message.bytes);
			if ('sha256' in message && typeof message.sha256 === 'string') {
				worker.terminate();
				resolve(message.sha256);
			}
			if ('error' in message && typeof message.error === 'string') {
				worker.terminate();
				reject(new Error(message.error));
			}
		};
		worker.onerror = () => {
			worker.terminate();
			reject(
				new Error('Unable to hash this source file. Retry after checking the file is readable.')
			);
		};
		worker.postMessage(file);
	});
}
