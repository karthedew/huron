import { afterEach, describe, expect, it, vi } from 'vitest';
import type { HuronUser, PolarisCatalog } from '$api/types';
import { getBootstrapPolarisClient } from './huron-accounts';
import { visibleCatalogs } from './polaris-catalogs';
import { PolarisClient } from './polaris-client';

vi.mock('./huron-accounts', () => ({ getBootstrapPolarisClient: vi.fn() }));

const scientist: HuronUser = {
	id: 'alice',
	username: 'alice',
	displayName: 'Alice',
	isAdmin: false,
	disabled: false,
	polarisPrincipal: 'huron-alice',
	polarisPrincipalRole: 'huron-role-alice',
	createdAt: '2026-10-12T00:00:00Z'
};

function catalog(name: string, properties: Record<string, string>): PolarisCatalog {
	return { name, properties, type: 'INTERNAL', storageConfigInfo: { storageType: 'FILE' } };
}

function client(clientId: string, handler: (url: URL) => Response) {
	const fetcher = vi.fn<typeof fetch>(async (input, init) => {
		const url = new URL(String(input));
		if (url.pathname.endsWith('/oauth/tokens')) {
			expect(String(init?.body)).toContain(`client_id=${clientId}`);
			return Response.json({ access_token: `${clientId}-private-token`, expires_in: 3600 });
		}
		expect(new Headers(init?.headers).get('Authorization')).toBe(
			`Bearer ${clientId}-private-token`
		);
		return handler(url);
	});
	return {
		value: new PolarisClient(
			{
				url: 'http://localhost:8181',
				realm: 'POLARIS',
				clientId,
				clientSecret: `${clientId}-private-secret`
			},
			fetcher
		),
		fetcher
	};
}

afterEach(() => vi.clearAllMocks());

describe('Polaris catalog directory visibility', () => {
	it('excludes unassigned catalogs and publishes metadata returned by the user’s own principal', async () => {
		const directory = client('root', (url) => {
			if (url.pathname.endsWith('/catalogs'))
				return Response.json({
					catalogs: [
						catalog('public', { privateDirectoryValue: 'never-show' }),
						catalog('hidden', { description: 'hidden-secret' })
					]
				});
			expect(url.pathname).toContain('/principal-roles/huron-role-alice/catalog-roles/');
			return Response.json({
				roles: url.pathname.endsWith('/public') ? [{ name: 'reader', properties: {} }] : []
			});
		});
		vi.mocked(getBootstrapPolarisClient).mockResolvedValue(directory.value);
		const own = client('alice', (url) => {
			expect(url.pathname).toBe('/api/management/v1/catalogs/public');
			return Response.json(catalog('public', { description: 'Visible through Alice' }));
		});
		const visible = await visibleCatalogs(scientist, own.value);
		expect(visible).toEqual([catalog('public', { description: 'Visible through Alice' })]);
		expect(JSON.stringify(visible)).not.toMatch(
			/never-show|hidden-secret|private-token|private-secret/
		);
		expect(own.fetcher.mock.calls.some(([url]) => String(url).includes('/hidden'))).toBe(false);
	});

	it.each([403, 404])(
		'hides a catalog whose membership exists but own-principal read returns %s',
		async (status) => {
			const directory = client('root', (url) =>
				url.pathname.endsWith('/catalogs')
					? Response.json({ catalogs: [catalog('restricted', { description: 'hidden-details' })] })
					: Response.json({ roles: [{ name: 'reader', properties: {} }] })
			);
			vi.mocked(getBootstrapPolarisClient).mockResolvedValue(directory.value);
			const own = client('alice', () =>
				Response.json({ message: 'secret-denial-details' }, { status })
			);
			expect(await visibleCatalogs(scientist, own.value)).toEqual([]);
		}
	);

	it('rechecks Polaris assignments on each request and excludes revoked membership', async () => {
		let granted = true;
		const directory = client('root', (url) =>
			url.pathname.endsWith('/catalogs')
				? Response.json({ catalogs: [catalog('research', {})] })
				: Response.json({ roles: granted ? [{ name: 'reader', properties: {} }] : [] })
		);
		vi.mocked(getBootstrapPolarisClient).mockResolvedValue(directory.value);
		const own = client('alice', () => Response.json(catalog('research', {})));
		expect(await visibleCatalogs(scientist, own.value)).toHaveLength(1);
		granted = false;
		expect(await visibleCatalogs(scientist, own.value)).toEqual([]);
		expect(
			own.fetcher.mock.calls.filter(([url]) => String(url).endsWith('/catalogs/research'))
		).toHaveLength(1);
	});

	it('excludes a catalog removed during directory enumeration', async () => {
		const directory = client('root', (url) =>
			url.pathname.endsWith('/catalogs')
				? Response.json({ catalogs: [catalog('removed', {})] })
				: Response.json({}, { status: 404 })
		);
		vi.mocked(getBootstrapPolarisClient).mockResolvedValue(directory.value);
		const own = client('alice', () => Response.json({}, { status: 404 }));
		expect(await visibleCatalogs(scientist, own.value)).toEqual([]);
		expect(own.fetcher).not.toHaveBeenCalled();
	});

	it('reports upstream failure instead of returning privileged metadata or a misleading empty directory', async () => {
		const directory = client('root', (url) =>
			url.pathname.endsWith('/catalogs')
				? Response.json({ catalogs: [catalog('research', {})] })
				: Response.json({ roles: [{ name: 'reader', properties: {} }] })
		);
		vi.mocked(getBootstrapPolarisClient).mockResolvedValue(directory.value);
		const own = client('alice', () => Response.json({}, { status: 503 }));
		await expect(visibleCatalogs(scientist, own.value)).rejects.toMatchObject({ status: 503 });
	});

	it('uses the administrator’s authenticated principal for catalog listing without the bootstrap directory', async () => {
		const own = client('admin', () => Response.json({ catalogs: [catalog('research', {})] }));
		expect(await visibleCatalogs({ ...scientist, isAdmin: true }, own.value)).toEqual([
			catalog('research', {})
		]);
		expect(getBootstrapPolarisClient).not.toHaveBeenCalled();
	});
});
