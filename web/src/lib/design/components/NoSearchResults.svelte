<script lang="ts">
	import { X } from '@lucide/svelte';
	import {
		STATE_NAMES,
		labelText,
		textWords,
		withDefaultStates,
		withText,
		withoutLabel,
		withoutText,
		type Search
	} from '$lib/search';
	import { REMOVE_CHIP } from '../chips';
	import EmptyState from './EmptyState.svelte';

	interface Props {
		/** The search that found nothing. */
		search: Search;
		/** The address of this search page for another search. */
		href: (search: Search) => string;
		/** A wider search to offer instead, such as all of the organization. */
		wider: { label: string; href: string } | null;
		/** What it says where "No collections match this search." would claim too much. */
		title?: string;
	}

	let { search, href, wider, title }: Props = $props();

	/** Each filter of the search, as a link to the same search without it. */
	const filters = $derived.by(() => {
		const states = (search.states ?? []).map((state) => STATE_NAMES[state]).join(', ');
		return [
			...(search.q === ''
				? []
				: [
						{
							key: 'q',
							shown: `“${search.q}”`,
							name: `Remove text “${search.q}”`,
							href: href(withoutText(search))
						}
					]),
			...search.labels.map((label) => ({
				key: `label ${labelText(label)}`,
				shown: `${label.key} = ${label.value}`,
				name: `Remove filter ${label.key} = ${label.value}`,
				href: href(withoutLabel(search, label))
			})),
			...(search.states === null
				? []
				: [
						{
							key: 'states',
							shown: `States: ${states}`,
							name: `Remove state filter ${states}`,
							href: href(withDefaultStates(search))
						}
					])
		];
	});
	/** A text of several words may find something by one of them. */
	const words = $derived(textWords(search.q));
</script>

<EmptyState
	title={title ??
		(filters.length > 0 ? 'No collections match this search.' : 'No collections yet.')}
>
	{#if filters.length > 0}
		<p class="mt-3 mb-2 text-sm">Remove a filter:</p>
		<ul class="m-0 flex list-none flex-wrap justify-center gap-1.5 p-0" aria-label="Filters">
			{#each filters as filter (filter.key)}
				<li class="max-w-full">
					<a href={filter.href} aria-label={filter.name} class={REMOVE_CHIP}
						><span class="min-w-0">{filter.shown}</span><X
							size={12}
							class="shrink-0"
							aria-hidden="true"
						/></a
					>
				</li>
			{/each}
		</ul>
	{/if}
	{#if words.length > 1}
		<p class="mt-4 mb-2 text-sm">Search for one of its words:</p>
		<ul class="m-0 flex list-none flex-wrap justify-center gap-x-4 gap-y-1 p-0" aria-label="Words">
			{#each words as word (word)}
				<li class="max-w-full wrap-anywhere">
					<a href={href(withText(search, word))} class="font-semibold underline underline-offset-2"
						>{word}</a
					>
				</li>
			{/each}
		</ul>
	{/if}
	{#if wider}
		<p class="mt-4 mb-0 text-sm">
			<a href={wider.href} class="font-semibold underline underline-offset-2">{wider.label}</a>
		</p>
	{/if}
</EmptyState>
