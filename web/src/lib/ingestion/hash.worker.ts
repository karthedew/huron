import { hashBlob } from './hash';
self.onmessage = async (event: MessageEvent<Blob>) => {
	try {
		const sha256 = await hashBlob(event.data, (bytes) => self.postMessage({ bytes }));
		self.postMessage({ sha256 });
	} catch (error) {
		self.postMessage({
			error: error instanceof Error ? error.message : 'Unable to read the source file.'
		});
	}
};
