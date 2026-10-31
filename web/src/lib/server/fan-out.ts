/**
 * Running many API reads with only a few in flight at once: an organization's search over its
 * catalogs, the explorer's levels on the way to a deep page. Each task settles on its own, so one
 * failure fails no other.
 */

/** How one task of a fan-out ended. */
export type Settlement<T> =
	{ status: 'answered'; value: T } | { status: 'failed'; failure: unknown } | { status: 'late' };

const LATE = { status: 'late' } as const;

/**
 * Run `task` for each item, at most `concurrency` at once and in the items' order, until every
 * task has settled or `signal` aborts. The settlements come in the items' order; a task that has
 * not settled when `signal` aborts, started or not, is `late`. Each task gets `signal` to abort
 * its requests with. Whatever a task does once the fan-out is over is ignored: it changes no
 * settlement, and its failure is neither reported nor left unhandled.
 */
export function fanOut<I, T>(
	items: readonly I[],
	task: (item: I, signal: AbortSignal) => Promise<T>,
	{ concurrency, signal }: { concurrency: number; signal: AbortSignal }
): Promise<Array<Settlement<T>>> {
	const width = Math.max(1, concurrency);
	return new Promise((resolve) => {
		const settlements: Array<Settlement<T> | undefined> = items.map(() => undefined);
		let started = 0;
		let settled = 0;
		let finished = false;
		const finish = () => {
			if (finished) return;
			finished = true;
			signal.removeEventListener('abort', finish);
			resolve(settlements.map((settlement) => settlement ?? LATE));
		};
		const run = async (index: number) => {
			let settlement: Settlement<T>;
			try {
				settlement = { status: 'answered', value: await task(items[index], signal) };
			} catch (failure) {
				settlement = { status: 'failed', failure };
			}
			if (finished) return;
			settlements[index] = settlement;
			settled += 1;
			if (settled === items.length) finish();
			else startMore();
		};
		const startMore = () => {
			while (!finished && started < items.length && started - settled < width) {
				const index = started;
				started += 1;
				void run(index);
			}
		};
		if (signal.aborted || items.length === 0) {
			finish();
			return;
		}
		signal.addEventListener('abort', finish, { once: true });
		startMore();
	});
}
