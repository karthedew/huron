<script lang="ts">
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import CopyIdentifier from '$design/components/CopyIdentifier.svelte';
	import SectionNav from '$design/components/SectionNav.svelte';
	import { identifierInCatalog } from '$lib/explorer';
	import { formatTimestamp, timestampAttribute } from '$lib/format';
	import type { LayoutProps } from './$types';

	let { data, children }: LayoutProps = $props();

	const collection = $derived(data.collection);
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
			label: 'Metadata',
			href: resolve(
				'/(app)/catalogs/[catalog=segment]/collections/[identifier=dotted]/metadata',
				params
			),
			current:
				page.route.id ===
				'/(app)/catalogs/[catalog=segment]/collections/[identifier=dotted]/metadata'
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
		},
		{
			label: 'CLI',
			href: resolve(
				'/(app)/catalogs/[catalog=segment]/collections/[identifier=dotted]/cli',
				params
			),
			current:
				page.route.id === '/(app)/catalogs/[catalog=segment]/collections/[identifier=dotted]/cli'
		}
	]);
</script>

<header class="border-b border-app-line">
	<div class="relative flex min-w-0 items-start gap-2">
		<h1 class="m-0 min-w-0 text-xl leading-8 font-semibold wrap-anywhere">
			{collection.title ?? collection.identifier}
		</h1>
		<CopyIdentifier value={collection.identifier} />
	</div>
	{#if collection.pendingCommit}
		{@const pending = collection.pendingCommit}
		<p class="mt-1 mb-0 text-sm wrap-anywhere text-app-muted">
			A commit is {pending.state === 'blocked' ? 'blocked' : 'in progress'} since
			<time datetime={timestampAttribute(pending.since)}>{formatTimestamp(pending.since)}</time>.
			The files and the version show the last completed commit.
		</p>
	{/if}
	<SectionNav label="Collection" {sections} />
</header>

<div class="pt-5">{@render children()}</div>
