<script lang="ts">
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import Badge from '$design/components/Badge.svelte';
	import SectionNav from '$design/components/SectionNav.svelte';
	import { statePresentation } from '$lib/collection-state';
	import { identifierInCatalog } from '$lib/explorer';
	import type { LayoutProps } from './$types';

	let { data, children }: LayoutProps = $props();

	const collection = $derived(data.collection);
	const shown = $derived(
		statePresentation(collection.state, {
			overrideIncompatible: collection.overrideIncompatible
		})
	);
	const params = $derived({
		catalog: collection.catalog,
		identifier: identifierInCatalog(collection.identifier)
	});
	const sections = $derived([
		{
			label: 'Overview',
			href: resolve('/(app)/catalogs/[catalog=segment]/collections/[identifier=dotted]', params),
			current: page.route.id === '/(app)/catalogs/[catalog=segment]/collections/[identifier=dotted]'
		},
		{
			label: 'Files',
			href: resolve(
				'/(app)/catalogs/[catalog=segment]/collections/[identifier=dotted]/files',
				params
			),
			current:
				page.route.id === '/(app)/catalogs/[catalog=segment]/collections/[identifier=dotted]/files',
			// A draft has no files to count.
			count: collection.state === 'draft' ? undefined : collection.fileCount
		},
		{
			label: 'Commits',
			href: resolve(
				'/(app)/catalogs/[catalog=segment]/collections/[identifier=dotted]/commits',
				params
			),
			current:
				page.route.id ===
				'/(app)/catalogs/[catalog=segment]/collections/[identifier=dotted]/commits'
		},
		{
			label: 'Activity',
			href: resolve(
				'/(app)/catalogs/[catalog=segment]/collections/[identifier=dotted]/activity',
				params
			),
			current:
				page.route.id ===
				'/(app)/catalogs/[catalog=segment]/collections/[identifier=dotted]/activity'
		},
		{
			label: 'Schema',
			href: resolve(
				'/(app)/catalogs/[catalog=segment]/collections/[identifier=dotted]/schema',
				params
			),
			current:
				page.route.id === '/(app)/catalogs/[catalog=segment]/collections/[identifier=dotted]/schema'
		}
	]);
</script>

<header class="border-b border-app-line">
	<p class="m-0 text-xs font-semibold tracking-wide text-app-muted uppercase">Collection</p>
	<h1 class="mt-1 wrap-anywhere">{collection.title ?? collection.identifier}</h1>
	{#if collection.title !== null}
		<p class="mono mt-1 mb-0 text-sm break-all text-app-muted">{collection.identifier}</p>
	{/if}
	<p class="mt-3 mb-0 flex flex-wrap items-baseline gap-x-3 gap-y-1 text-sm">
		<Badge tone={shown.tone}>{shown.label}</Badge>
		{#if shown.explanation}<span class="min-w-0 text-app-muted">{shown.explanation}</span>{/if}
	</p>
	{#if collection.description}
		<p class="mt-3 mb-0 max-w-3xl whitespace-pre-line wrap-anywhere">{collection.description}</p>
	{/if}
	<SectionNav label="Collection" {sections} />
</header>

<div class="mt-6">{@render children()}</div>
