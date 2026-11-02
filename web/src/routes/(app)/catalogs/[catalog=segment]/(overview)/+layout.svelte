<script lang="ts">
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import SectionNav from '$design/components/SectionNav.svelte';
	import CopyIdentifier from '$design/components/CopyIdentifier.svelte';
	import { displayName } from '$lib/names';
	import type { LayoutProps } from './$types';

	let { data, children }: LayoutProps = $props();

	const catalog = $derived(data.catalog);
	const params = $derived({ catalog: catalog.name });
	const schemaHref = $derived(
		resolve('/(app)/catalogs/[catalog=segment]/(overview)/schema', params)
	);
	const sections = $derived([
		{
			label: 'Overview',
			href: resolve('/(app)/catalogs/[catalog=segment]/(overview)', params),
			current: page.route.id === '/(app)/catalogs/[catalog=segment]/(overview)'
		},
		{
			label: 'Access',
			href: resolve('/(app)/catalogs/[catalog=segment]/(overview)/access', params),
			current: page.route.id === '/(app)/catalogs/[catalog=segment]/(overview)/access'
		},
		{
			label: 'Activity',
			href: resolve('/(app)/catalogs/[catalog=segment]/(overview)/activity', params),
			current: page.route.id === '/(app)/catalogs/[catalog=segment]/(overview)/activity'
		},
		{
			label: 'Schema',
			href: schemaHref,
			current: page.route.id === '/(app)/catalogs/[catalog=segment]/(overview)/schema'
		},
		{
			label: 'CLI',
			href: resolve('/(app)/catalogs/[catalog=segment]/(overview)/cli', params),
			current: page.route.id === '/(app)/catalogs/[catalog=segment]/(overview)/cli'
		}
	]);
</script>

<header class="border-b border-app-line">
	<div class="relative flex min-w-0 items-start gap-2">
		<h1 class="m-0 min-w-0 text-xl leading-8 font-semibold wrap-anywhere">
			{displayName(catalog)}
		</h1>
		<CopyIdentifier value={catalog.name} />
	</div>
	<SectionNav label="Catalog" {sections} />
</header>

<div class="mt-6">{@render children()}</div>
