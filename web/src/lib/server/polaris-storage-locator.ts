import { PolarisInputError } from './polaris-forms';

/** Registration stores an unsigned storage locator; credentials belong to catalog configuration. */
export function validateStorageLocator(value: string, label: string): void {
	try {
		const parsed = new URL(value);
		if (parsed.username || parsed.password || parsed.search || parsed.hash)
			throw new TypeError('Storage locator contains credentials or query parameters.');
		if (!['file:', 's3:', 'gs:', 'gcs:', 'abfs:', 'abfss:', 'wasbs:'].includes(parsed.protocol))
			throw new TypeError('Unsupported storage locator scheme.');
	} catch {
		throw new PolarisInputError(
			`${label} must be a storage URI without credentials, query parameters or fragments.`
		);
	}
}
