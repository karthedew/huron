import { describe, expect, it } from 'vitest';
import { LINKED_COLLECTION_GONE, errorCopy } from './error-copy';

describe('errorCopy', () => {
	it.each([
		[400, 'Invalid request', 'That request is not valid.', false],
		[403, 'No permission', "You don't have permission to see this.", false],
		[404, 'Not found', "Not found, or you don't have access.", false],
		[503, 'Service unavailable', "The Huron service isn't responding.", true],
		[500, 'Error', 'Something went wrong.', true],
		[502, 'Error', 'Something went wrong.', true],
		[418, 'Error', 'Something went wrong.', false]
	])('gives %i fixed copy', (status, title, heading, retry) => {
		expect(errorCopy(status)).toMatchObject({ title, heading, retry });
	});

	it('reminds people that groups are read at sign-in when something is not found', () => {
		expect(errorCopy(404).detail).toContain('sign out and sign in again');
	});

	it('says that a collection linked by its id may have been deleted', () => {
		expect(errorCopy(404, LINKED_COLLECTION_GONE)).toMatchObject({
			title: 'Not found',
			heading: 'Not found, deleted, or you do not have access.',
			retry: false
		});
		expect(errorCopy(404, LINKED_COLLECTION_GONE).detail).toContain('sign out and sign in again');
		expect(errorCopy(404, 'NOT_FOUND').heading).toBe("Not found, or you don't have access.");
		expect(errorCopy(500, LINKED_COLLECTION_GONE).heading).toBe('Something went wrong.');
	});
});
