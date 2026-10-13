import type { PolarisProperties, PolarisStorageConfig } from '$api/types';
import { PolarisApiError, object, properties, storageConfig, strings } from './polaris-client';

export class PolarisInputError extends PolarisApiError {
	constructor(message: string) {
		super(400, message);
	}
}

export function field(form: FormData, name: string): string {
	const value = form.get(name);
	if (value === null) return '';
	if (typeof value !== 'string') throw new PolarisInputError(`${name} must be text.`);
	return value.trim();
}

export function required(form: FormData, name: string): string {
	const value = field(form, name);
	if (!value) throw new PolarisInputError(`${name} is required.`);
	if (value.length > 256 || value === '.' || value === '..' || /[\x00-\x1f\x7f]/.test(value))
		throw new PolarisInputError(
			`${name} must be a name of at most 256 characters without control characters.`
		);
	return value;
}

function json(form: FormData, name: string, fallback: string): unknown {
	try {
		const value: unknown = JSON.parse(field(form, name) || fallback);
		return value;
	} catch {
		throw new PolarisInputError(`${name} must be valid JSON.`);
	}
}

export function formProperties(form: FormData, name = 'properties'): PolarisProperties {
	try {
		return properties(object(json(form, name, '{}')));
	} catch (error) {
		if (error instanceof PolarisInputError) throw error;
		throw new PolarisInputError(`${name} must be a JSON object with string values.`);
	}
}

export function formStorageConfig(form: FormData): PolarisStorageConfig {
	try {
		return storageConfig(json(form, 'storageConfigInfo', '{}'));
	} catch (error) {
		if (error instanceof PolarisInputError) throw error;
		throw new PolarisInputError(
			'storageConfigInfo must be a JSON storage configuration with FILE, S3, GCS or AZURE storageType.'
		);
	}
}

export function namespace(form: FormData, allowEmpty = false): string[] {
	try {
		const value = strings(json(form, 'namespace', '[]'));
		if (
			(!allowEmpty && !value.length) ||
			value.some(
				(part) =>
					!part ||
					part.length > 256 ||
					part === '.' ||
					part === '..' ||
					/[\x00-\x1f\x7f]/.test(part)
			)
		)
			throw new PolarisInputError('namespace must be a JSON array of nonempty namespace names.');
		return value;
	} catch (error) {
		if (error instanceof PolarisInputError) throw error;
		throw new PolarisInputError('namespace must be a JSON array of namespace names.');
	}
}

export function version(form: FormData): number {
	const value = field(form, 'currentEntityVersion');
	if (!/^\d+$/.test(value) || !Number.isSafeInteger(Number(value)))
		throw new PolarisInputError(
			'currentEntityVersion is required and must be a nonnegative integer.'
		);
	return Number(value);
}

export function checked(form: FormData, name: string): boolean {
	return ['on', 'true', '1'].includes(field(form, name));
}

export function accessMode(form: FormData): 'read' | 'read-write' {
	const mode = field(form, 'accessMode') || 'read';
	if (mode !== 'read' && mode !== 'read-write')
		throw new PolarisInputError('accessMode must be read or read-write.');
	return mode;
}

export function confirm(form: FormData, expected: string): void {
	if (field(form, 'confirmation') !== expected)
		throw new PolarisInputError(`Type ${expected} to confirm deletion.`);
}
