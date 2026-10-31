<script lang="ts">
	import { resolve } from '$app/paths';
	import type { Organization } from '$api/types';
	import { countLabel } from '$lib/format';
	import { displayName, secondaryName } from '$lib/names';
	import Card from './Card.svelte';

	interface Props {
		organization: Organization;
	}

	let { organization }: Props = $props();

	const name = $derived(secondaryName(organization));
</script>

<Card href={resolve('/(app)/orgs/[org=segment]', { org: organization.name })}>
	<span class="block font-semibold wrap-anywhere text-app-fg">{displayName(organization)}</span>
	{#if name}
		<span class="mono block text-xs wrap-anywhere text-app-muted">{name}</span>
	{/if}
	{#if organization.description}
		<span class="mt-2 block text-sm wrap-anywhere text-app-muted">{organization.description}</span>
	{/if}
	<span class="mt-2 block text-xs text-app-muted"
		>{countLabel(organization.catalog_count, 'catalog')}</span
	>
</Card>
