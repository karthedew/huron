<script lang="ts">
	import { resolve } from '$app/paths';
	import { FileText } from '@lucide/svelte';
	import { listBadge } from '$lib/collection-state';
	import { identifierInCatalog } from '$lib/explorer';
	import { countLabel, formatTimestamp, timestampAttribute } from '$lib/format';
	import {
		filtersBy,
		withLabel,
		type LabelFilter,
		type Search,
		type SearchResult
	} from '$lib/search';
	import Badge from './Badge.svelte';
	import Highlighted from './Highlighted.svelte';
	import LabelChips from './LabelChips.svelte';

	interface Props {
		/** The list's name, e.g. "Results". */
		label: string;
		results: readonly SearchResult[];
		/** The search they answer: its text is marked, and label chips add to it. */
		search: Search;
		/**
		 * The address of this search page for another search, which label chips lead to; without
		 * it, label chips are text.
		 */
		href?: (search: Search) => string;
	}

	let { label, results, search, href }: Props = $props();

	const adding = $derived.by(() => {
		if (href === undefined) return undefined;
		const to = href;
		return (filter: LabelFilter) => to(withLabel(search, filter));
	});

	function searchedFor(filter: LabelFilter): boolean {
		return filtersBy(search, filter);
	}
</script>

<!-- A row is no link: its title is, and its label chips are links of their own. -->
<ul class="m-0 grid list-none gap-2 p-0" aria-label={label}>
	{#each results as result (result.id)}
		{@const badge = listBadge(result.state)}
		<li class="rounded-card border border-app-line bg-app-card px-4 py-3">
			<div class="flex min-w-0 gap-3">
				<FileText size={18} class="mt-0.5 shrink-0 text-app-muted" aria-hidden="true" />
				<div class="grid min-w-0 flex-1 gap-2">
					<div class="min-w-0">
						<!-- Each title is a heading, so the results read from one to the next. -->
						<div class="flex flex-wrap items-center gap-x-2 gap-y-1">
							<h3
								class={[
									'm-0 min-w-0 text-sm font-semibold',
									result.title === null ? 'mono break-all' : 'wrap-anywhere'
								]}
							>
								<a
									href={resolve(
										'/(app)/catalogs/[catalog=segment]/collections/[identifier=dotted]',
										{
											catalog: result.catalog,
											identifier: identifierInCatalog(result.identifier)
										}
									)}
									class="text-app-fg no-underline hover:underline"
									><Highlighted text={result.title ?? result.identifier} q={search.q} /></a
								>
							</h3>
							{#if badge}<Badge tone={badge.tone}>{badge.label}</Badge>{/if}
						</div>
						<!-- Without a title, the link above is the identifier already. -->
						{#if result.title !== null}
							<p class="mono mt-0.5 mb-0 text-xs break-all text-app-fg">
								<Highlighted text={result.identifier} q={search.q} />
							</p>
						{/if}
					</div>
					{#if result.description !== null}
						<p class="m-0 line-clamp-2 text-sm wrap-anywhere text-app-fg">
							<Highlighted text={result.description} q={search.q} />
						</p>
					{/if}
					{#if result.labels.length > 0}
						<LabelChips
							label="Labels"
							chips={result.labels}
							more={result.moreLabels}
							href={adding}
							action="add this label to the search"
							active={searchedFor}
						/>
					{/if}
					<p class="m-0 flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-app-muted">
						<span>{countLabel(result.fileCount, 'file')}</span>
						<span
							>Updated <time datetime={timestampAttribute(result.updatedAt)}
								>{formatTimestamp(result.updatedAt)}</time
							></span
						>
					</p>
				</div>
			</div>
		</li>
	{/each}
</ul>
