// @vitest-environment node
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { AUDIT_ACTIONS, ROLES, ROLE_SCOPES, isAuditAction, isRole } from './types';

const SOURCE = new URL('../../../../src/huron/', import.meta.url);

/** The string values of a Python `StrEnum` class, in declaration order. */
function enumValues(file: string, className: string): string[] {
	const text = readFileSync(new URL(file, SOURCE), 'utf8');
	const start = text.indexOf(`class ${className}(StrEnum):`);
	expect(start).toBeGreaterThanOrEqual(0);
	const rest = text.slice(start).split('\n').slice(1);
	const end = rest.findIndex((line) => line !== '' && !line.startsWith(' '));
	const body = rest.slice(0, end === -1 ? rest.length : end).join('\n');
	return [...body.matchAll(/^\s+[A-Z_]+ = "([^"]+)"$/gm)].map((match) => match[1]);
}

describe('UI unions', () => {
	it('list the closed audit vocabulary of the API', () => {
		expect([...AUDIT_ACTIONS]).toEqual(enumValues('core/lake/audit/models.py', 'Action'));
	});

	it('list the roles and scopes of the API', () => {
		expect([...ROLES]).toEqual(enumValues('core/security/rbac/roles.py', 'Role'));
		expect([...ROLE_SCOPES]).toEqual(enumValues('core/security/rbac/roles.py', 'ScopeType'));
	});

	it('narrow strings to the unions', () => {
		expect(isRole('catalog_admin')).toBe(true);
		expect(isRole('admin')).toBe(false);
		expect(isAuditAction('collection.commit')).toBe(true);
		expect(isAuditAction('collection.push')).toBe(false);
	});
});
