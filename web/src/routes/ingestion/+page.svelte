<script lang="ts">
	import RawIngestWizard from '$lib/design/components/ingestion/RawIngestWizard.svelte';
	import type { PageData } from './$types';
	let { data }: { data: PageData } = $props();
</script>

<svelte:head><title>Raw ingestion · Huron</title></svelte:head>
{#key `${data.selectedOrganization}:${data.selectedCatalog}`}
	<RawIngestWizard {data} />
{/key}
