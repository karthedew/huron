import { createSHA256 } from 'hash-wasm';
export const HASH_CHUNK_BYTES = 4 * 1024 * 1024;
/** Fixed-size reads bound memory independently of source file size. */
export async function hashBlob(blob: Blob, progress: (bytes: number) => void): Promise<string> {
	const hash = await createSHA256();
	hash.init();
	for (let offset = 0; offset < blob.size; offset += HASH_CHUNK_BYTES) {
		const chunk = new Uint8Array(await blob.slice(offset, offset + HASH_CHUNK_BYTES).arrayBuffer());
		hash.update(chunk);
		progress(Math.min(offset + HASH_CHUNK_BYTES, blob.size));
	}
	return hash.digest('hex');
}
