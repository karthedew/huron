<script lang="ts">
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import SectionNav from '$design/components/SectionNav.svelte';
	import { countLabel } from '$lib/format';
	import { displayName, secondaryName } from '$lib/names';
	import { visibleOrganization } from '$lib/organizations';
	import type { LayoutProps } from './$types';

	let { data, children }: LayoutProps = $props();

	const catalog = $derived(data.catalog);
	const name = $derived(secondaryName(catalog));
	const owner = $derived(visibleOrganization(catalog.organization, data.organizations));
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
			label: 'Search',
			href: resolve('/(app)/catalogs/[catalog=segment]/(overview)/search', params),
			current: page.route.id === '/(app)/catalogs/[catalog=segment]/(overview)/search'
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
		}
	]);
</script>

<header class="border-b border-app-line">
	<p class="m-0 text-xs font-semibold tracking-wide text-app-muted uppercase">Catalog</p>
	<h1 class="mt-1 wrap-anywhere">{displayName(catalog)}</h1>
	{#if name}
		<p class="mono mt-1 mb-0 text-sm wrap-anywhere text-app-muted">{name}</p>
	{/if}
	{#if catalog.description}
		<p class="mt-3 mb-0 max-w-3xl wrap-anywhere">{catalog.description}</p>
	{/if}
	<p class="mt-3 mb-0 flex flex-wrap gap-x-5 gap-y-1 text-sm text-app-muted">
		<span class="min-w-0 wrap-anywhere"
			>Organization <a
				href={resolve('/(app)/orgs/[org=segment]', { org: catalog.organization })}
				class="font-semibold underline underline-offset-2"
				>{owner ? displayName(owner) : catalog.organization}</a
			></span
		>
		<span class="min-w-0 wrap-anywhere"
			>Schema <a href={schemaHref} class="mono font-semibold underline underline-offset-2"
				>{catalog.schema.name} v{catalog.schema.version}</a
			></span
		>
		<span>{countLabel(catalog.namespace_count, 'namespace')} in total</span>
	</p>
	<SectionNav label="Catalog" {sections} />
</header>

<div class="mt-6">{@render children()}</div>
