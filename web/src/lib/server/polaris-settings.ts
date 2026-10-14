import { env } from '$env/dynamic/private';

interface PolarisConfiguration {
	POLARIS_URL?: string;
	POLARIS_REALM?: string;
	POLARIS_CONNECTIONS_JSON?: string;
}

export interface PolarisRealm {
	url: string;
	realm: string;
}

interface ConfiguredConnection extends PolarisRealm {
	clientId: string;
	clientSecret: string;
}

export function polarisSettings(
	configuration: PolarisConfiguration = {
		POLARIS_URL: env.POLARIS_URL,
		POLARIS_REALM: env.POLARIS_REALM
	}
): PolarisRealm {
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

function configuredConnections(configuration: PolarisConfiguration): ConfiguredConnection[] {
	if (!configuration.POLARIS_CONNECTIONS_JSON) return [];
	let values: unknown;
	try {
		values = JSON.parse(configuration.POLARIS_CONNECTIONS_JSON);
	} catch {
		throw new Error('POLARIS_CONNECTIONS_JSON must be a JSON array of realm connections.');
	}
	if (!Array.isArray(values))
		throw new Error('POLARIS_CONNECTIONS_JSON must be a JSON array of realm connections.');
	const result = values.map((value: unknown) => {
		if (!value || typeof value !== 'object' || Array.isArray(value))
			throw new Error('Invalid Polaris realm connection.');
		const item = Object.fromEntries(Object.entries(value));
		if (
			typeof item.url !== 'string' ||
			typeof item.realm !== 'string' ||
			typeof item.clientId !== 'string' ||
			!item.clientId ||
			typeof item.clientSecret !== 'string' ||
			!item.clientSecret
		)
			throw new Error('Each Polaris realm connection needs url, realm, clientId and clientSecret.');
		return {
			...polarisSettings({ POLARIS_URL: item.url, POLARIS_REALM: item.realm }),
			clientId: item.clientId,
			clientSecret: item.clientSecret
		};
	});
	if (new Set(result.map((entry) => entry.realm)).size !== result.length)
		throw new Error('Configure each Polaris realm only once.');
	const primary = polarisSettings(configuration);
	if (result.some((entry) => entry.realm === primary.realm && entry.url !== primary.url))
		throw new Error('The default Polaris realm must use POLARIS_URL.');
	return result;
}

/** Public connection labels only; credentials stay inside the server registry. */
export function polarisRealms(configuration: PolarisConfiguration = env): PolarisRealm[] {
	const primary = polarisSettings(configuration);
	return [
		primary,
		...configuredConnections(configuration)
			.filter((entry) => entry.realm !== primary.realm)
			.map(({ url, realm }) => ({ url, realm }))
	];
}

/** Resolve an explicit realm without falling back to the default connection. */
export function polarisRealmSettings(
	realm: string,
	configuration: PolarisConfiguration = env
): PolarisRealm {
	const result = polarisRealms(configuration).find((entry) => entry.realm === realm);
	if (!result) throw new Error('This Polaris realm is not configured.');
	return result;
}

/** Server-only bootstrap override; the default realm may use the existing credentials file. */
export function polarisConfiguredConnection(
	realm: string,
	configuration: PolarisConfiguration = env
): ConfiguredConnection | null {
	polarisRealmSettings(realm, configuration);
	return configuredConnections(configuration).find((entry) => entry.realm === realm) ?? null;
}
