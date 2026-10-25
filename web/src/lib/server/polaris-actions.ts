import type { PolarisActionResult, PolarisGrant } from '$api/types';
import {
	credentialSummary,
	icechunkPath,
	management,
	namespacePath,
	object,
	PolarisApiError,
	PolarisClient,
	table
} from './polaris-client';
import {
	accessMode,
	checked,
	confirm,
	field,
	formProperties,
	formStorageConfig,
	namespace,
	PolarisInputError,
	required,
	version
} from './polaris-forms';
import { POLARIS_PRIVILEGES } from './polaris-privileges';
import { registerIcebergTable } from './polaris-iceberg-actions';

export const POLARIS_ACTION_NAMES = [
	'createCatalog',
	'updateCatalog',
	'deleteCatalog',
	'createNamespace',
	'updateNamespace',
	'deleteNamespace',
	'createTable',
	'registerIcebergTable',
	'loadTable',
	'deleteTable',
	'tableCredentials',
	'createPrincipal',
	'updatePrincipal',
	'deletePrincipal',
	'rotatePrincipal',
	'resetPrincipal',
	'createPrincipalRole',
	'updatePrincipalRole',
	'deletePrincipalRole',
	'assignPrincipalRole',
	'revokePrincipalRole',
	'createCatalogRole',
	'updateCatalogRole',
	'deleteCatalogRole',
	'assignCatalogRole',
	'revokeCatalogRole',
	'addGrant',
	'revokeGrant'
] as const;

export type PolarisActionName = (typeof POLARIS_ACTION_NAMES)[number];

export async function executePolarisAction(
	client: PolarisClient,
	action: PolarisActionName,
	form: FormData
): Promise<PolarisActionResult> {
	const result: PolarisActionResult = { action, success: true, message: 'Saved in Polaris.' };
	const request = (
		path: string,
		method: string,
		body?: unknown,
		headers?: Record<string, string>
	) => client.request(path, method, body, headers);
	const selectedCatalog = () => required(form, 'catalog');
	const named = () => ({ name: required(form, 'name'), properties: formProperties(form) });
	const update = () => ({ currentEntityVersion: version(form), properties: formProperties(form) });
	const deleteEntity = async (path: string, expected: string) => {
		confirm(form, expected);
		await request(path, 'DELETE');
		result.message = 'Deleted from Polaris.';
	};

	switch (action) {
		case 'registerIcebergTable':
			return registerIcebergTable(client, form);
		case 'createCatalog': {
			const entity = named();
			const location =
				field(form, 'defaultBaseLocation') || entity.properties['default-base-location'];
			if (!location) throw new PolarisInputError('defaultBaseLocation is required.');
			await request(management('catalogs'), 'POST', {
				catalog: {
					...entity,
					type: 'INTERNAL',
					properties: { ...entity.properties, 'default-base-location': location },
					storageConfigInfo: formStorageConfig(form)
				}
			});
			break;
		}
		case 'updateCatalog': {
			const body = update();
			const location = field(form, 'defaultBaseLocation');
			if (location) body.properties['default-base-location'] = location;
			await request(management('catalogs', selectedCatalog()), 'PUT', {
				...body,
				...(field(form, 'storageConfigInfo') ? { storageConfigInfo: formStorageConfig(form) } : {})
			});
			break;
		}
		case 'deleteCatalog':
			await deleteEntity(management('catalogs', selectedCatalog()), selectedCatalog());
			break;
		case 'createNamespace':
			await request(namespacePath(selectedCatalog()), 'POST', {
				namespace: namespace(form),
				properties: formProperties(form)
			});
			break;
		case 'updateNamespace': {
			const removals = field(form, 'removals')
				.split('\n')
				.map((part) => part.trim())
				.filter(Boolean);
			const updates = formProperties(form, 'updates');
			if (removals.some((key) => Object.hasOwn(updates, key)))
				throw new PolarisInputError(
					'A property cannot be updated and removed in the same request.'
				);
			await request(namespacePath(selectedCatalog(), namespace(form)) + '/properties', 'POST', {
				updates,
				removals
			});
			break;
		}
		case 'deleteNamespace':
			await deleteEntity(
				namespacePath(selectedCatalog(), namespace(form)),
				namespace(form).join('.')
			);
			break;
		case 'createTable':
		case 'loadTable':
		case 'tableCredentials': {
			const mode = action === 'createTable' ? 'read-write' : accessMode(form);
			const delegate = action === 'tableCredentials' || checked(form, 'delegate');
			const headers =
				delegate && action !== 'tableCredentials'
					? { 'Polaris-Icechunk-Table-Access-Delegation': 'vended-credentials' }
					: undefined;
			let path = icechunkPath(
				selectedCatalog(),
				namespace(form),
				action === 'createTable' ? '' : required(form, 'name')
			);
			if (action === 'tableCredentials') path += '/credentials';
			if (action !== 'createTable') path += `?access-mode=${mode}`;
			let body: unknown;
			if (action === 'createTable') {
				const entity = named();
				if ('location' in entity.properties)
					throw new PolarisInputError(
						'Use the location field for the repository root, rather than a location property.'
					);
				const location = field(form, 'location');
				if (!location) throw new PolarisInputError('location is required.');
				body = { ...entity, location };
			}
			let value: unknown;
			try {
				value = await client.request(
					path,
					action === 'createTable' ? 'POST' : 'GET',
					body,
					headers,
					action === 'loadTable' && !delegate
				);
			} catch (error) {
				if (action === 'createTable' && delegate && error instanceof PolarisApiError)
					throw new PolarisApiError(
						error.status,
						`${error.message} Polaris may already have registered the repository before credential vending failed. Refresh or load it before retrying registration.`
					);
				throw error;
			}
			if (action !== 'tableCredentials') result.table = table(object(value).table);
			result.credentialSummary = credentialSummary(value, mode, delegate);
			result.message =
				action === 'createTable'
					? 'Repository registered in Polaris. Polaris does not initialize or modify its contents.'
					: action === 'tableCredentials'
						? 'Storage credential check completed.'
						: 'Repository loaded from Polaris.';
			break;
		}
		case 'deleteTable':
			await deleteEntity(
				icechunkPath(selectedCatalog(), namespace(form), required(form, 'name')),
				required(form, 'name')
			);
			result.message = 'Repository registration dropped. Storage contents remain untouched.';
			break;
		case 'createPrincipal':
		case 'rotatePrincipal':
		case 'resetPrincipal': {
			const entity = named();
			const path =
				action === 'createPrincipal'
					? management('principals')
					: management(
							'principals',
							entity.name,
							action === 'rotatePrincipal' ? 'rotate' : 'reset'
						);
			const value = object(
				await request(
					path,
					'POST',
					action === 'createPrincipal'
						? {
								principal: entity,
								credentialRotationRequired: checked(form, 'credentialRotationRequired')
							}
						: action === 'resetPrincipal'
							? {}
							: undefined
				)
			);
			const credentials = object(value.credentials);
			if (typeof credentials.clientId !== 'string' || typeof credentials.clientSecret !== 'string')
				throw new PolarisInputError('Polaris did not return the new principal credentials.');
			result.credentials = {
				clientId: credentials.clientId,
				clientSecret: credentials.clientSecret,
				principal: entity.name
			};
			result.message =
				'Principal credentials changed. Save the displayed secret now; it is shown only in this action response.';
			break;
		}
		case 'updatePrincipal':
			await request(management('principals', required(form, 'name')), 'PUT', update());
			break;
		case 'deletePrincipal':
			await deleteEntity(management('principals', required(form, 'name')), required(form, 'name'));
			break;
		case 'createPrincipalRole':
			await request(management('principal-roles'), 'POST', {
				principalRole: { ...named(), federated: checked(form, 'federated') }
			});
			break;
		case 'updatePrincipalRole':
			await request(management('principal-roles', required(form, 'name')), 'PUT', update());
			break;
		case 'deletePrincipalRole':
			await deleteEntity(
				management('principal-roles', required(form, 'name')),
				required(form, 'name')
			);
			break;
		case 'assignPrincipalRole':
			await request(
				management('principals', required(form, 'principal'), 'principal-roles'),
				'PUT',
				{ principalRole: { name: required(form, 'principalRole') } }
			);
			break;
		case 'revokePrincipalRole':
			await request(
				management(
					'principals',
					required(form, 'principal'),
					'principal-roles',
					required(form, 'principalRole')
				),
				'DELETE'
			);
			break;
		case 'createCatalogRole':
			await request(management('catalogs', selectedCatalog(), 'catalog-roles'), 'POST', {
				catalogRole: named()
			});
			break;
		case 'updateCatalogRole':
			await request(
				management('catalogs', selectedCatalog(), 'catalog-roles', required(form, 'name')),
				'PUT',
				update()
			);
			break;
		case 'deleteCatalogRole':
			await deleteEntity(
				management('catalogs', selectedCatalog(), 'catalog-roles', required(form, 'name')),
				required(form, 'name')
			);
			break;
		case 'assignCatalogRole':
			await request(
				management(
					'principal-roles',
					required(form, 'principalRole'),
					'catalog-roles',
					selectedCatalog()
				),
				'PUT',
				{ catalogRole: { name: required(form, 'catalogRole') } }
			);
			break;
		case 'revokeCatalogRole':
			await request(
				management(
					'principal-roles',
					required(form, 'principalRole'),
					'catalog-roles',
					selectedCatalog(),
					required(form, 'catalogRole')
				),
				'DELETE'
			);
			break;
		case 'addGrant':
		case 'revokeGrant': {
			const type = field(form, 'type');
			if (type !== 'catalog' && type !== 'namespace' && type !== 'table')
				throw new PolarisInputError('Grant type must be catalog, namespace or table.');
			const privilege = required(form, 'privilege');
			if (!POLARIS_PRIVILEGES[type].includes(privilege))
				throw new PolarisInputError('Select a privilege valid for this grant type.');
			const grant: PolarisGrant = { type, privilege };
			if (type !== 'catalog') grant.namespace = namespace(form);
			if (type === 'table') grant.tableName = required(form, 'tableName');
			const path =
				management(
					'catalogs',
					selectedCatalog(),
					'catalog-roles',
					required(form, 'catalogRole'),
					'grants'
				) + (action === 'revokeGrant' ? `?cascade=${checked(form, 'cascade')}` : '');
			await request(path, action === 'addGrant' ? 'PUT' : 'POST', { grant });
			break;
		}
	}
	return result;
}
