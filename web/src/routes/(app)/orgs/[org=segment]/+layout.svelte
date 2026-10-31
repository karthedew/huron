<script lang="ts">
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import SectionNav from '$design/components/SectionNav.svelte';
	import { displayName, secondaryName } from '$lib/names';
	import type { LayoutProps } from './$types';

	let { data, children }: LayoutProps = $props();

	const organization = $derived(data.organizationDetails);
	const name = $derived(secondaryName(organization));
	const sections = $derived([
		{
			label: 'Catalogs',
			href: resolve('/(app)/orgs/[org=segment]', { org: organization.name }),
			current: page.route.id === '/(app)/orgs/[org=segment]',
			count: organization.catalog_count
		},
		{
			label: 'Search',
			href: resolve('/(app)/orgs/[org=segment]/search', { org: organization.name }),
			current: page.route.id === '/(app)/orgs/[org=segment]/search'
		}
	]);
</script>

<header class="border-b border-app-line">
	<p class="m-0 text-xs font-semibold tracking-wide text-app-muted uppercase">Organization</p>
	<h1 class="mt-1 wrap-anywhere">{displayName(organization)}</h1>
	{#if name}
		<p class="mono mt-1 mb-0 text-sm wrap-anywhere text-app-muted">{name}</p>
	{/if}
	{#if organization.description}
		<p class="mt-3 mb-0 max-w-3xl wrap-anywhere">{organization.description}</p>
	{/if}
	<SectionNav label="Organization" {sections} />
</header>

<div class="mt-6">{@render children()}</div>
