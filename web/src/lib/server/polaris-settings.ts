import { env } from '$env/dynamic/private';

export function polarisSettings(
	configuration: { POLARIS_URL?: string; POLARIS_REALM?: string } = {
		POLARIS_URL: env.POLARIS_URL,
		POLARIS_REALM: env.POLARIS_REALM
	}
): { url: string; realm: string } {
	const configured = configuration.POLARIS_URL ?? 'http://127.0.0.1:8181';
	let url: URL;
	try {
		url = new URL(configured);
	} catch {
		throw new Error('POLARIS_URL must be an HTTP origin without credentials or a path.');
	}
	if (
		!['http:', 'https:'].includes(url.protocol) ||
		url.username ||
		url.password ||
		url.search ||
		url.hash ||
		url.pathname !== '/'
	)
		throw new Error('POLARIS_URL must be an HTTP origin without credentials or a path.');
	const realm = configuration.POLARIS_REALM ?? 'POLARIS';
	if (!realm.trim() || /[\r\n]/.test(realm))
		throw new Error('POLARIS_REALM must be a nonempty realm name.');
	return { url: url.origin, realm };
}
