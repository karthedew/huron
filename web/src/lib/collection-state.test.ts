import { describe, expect, it } from 'vitest';
import { listBadge, statePresentation } from './collection-state';

describe('statePresentation', () => {
	it('presents the three states of a collection', () => {
		expect(statePresentation('active')).toEqual({ label: 'Active', tone: 'ok', explanation: null });
		expect(statePresentation('incomplete')).toEqual({
			label: 'Incomplete',
			tone: 'warn',
			explanation:
				"The catalog's schema now requires fields this collection lacks. Its files are unaffected."
		});
		expect(statePresentation('draft')).toMatchObject({ label: 'Draft', tone: 'neutral' });
		expect(statePresentation('draft').explanation).toBe(
			'Reserved, not yet activated: no directory or files on the share; visible to contributors only.'
		);
	});

	it('explains an incomplete collection whose schema override no longer fits', () => {
		expect(statePresentation('incomplete', { overrideIncompatible: true })).toEqual({
			label: 'Incomplete',
			tone: 'warn',
			explanation:
				"Its schema override no longer fits the catalog's schema. Its files are unaffected."
		});
		expect(statePresentation('draft', { overrideIncompatible: true }).label).toBe('Draft');
		expect(statePresentation('incomplete', { overrideIncompatible: false }).explanation).toBe(
			"The catalog's schema now requires fields this collection lacks. Its files are unaffected."
		);
	});

	it('shows an unknown state by its name', () => {
		expect(statePresentation('archived')).toEqual({
			label: 'archived',
			tone: 'neutral',
			explanation: null
		});
		expect(statePresentation('constructor').label).toBe('constructor');
	});
});

describe('listBadge', () => {
	it('marks every collection that is not active', () => {
		expect(listBadge('active')).toBeNull();
		expect(listBadge('draft')?.label).toBe('Draft');
		expect(listBadge('incomplete')?.tone).toBe('warn');
	});
});
