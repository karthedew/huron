<script lang="ts">
	import { page } from '$app/state';
	import Callout from './Callout.svelte';

	// The guard sends a list whose cursor the API no longer accepts back to its first page.
	const expired = $derived(page.url.searchParams.get('notice') === 'page_expired');
</script>

{#if expired}
	<Callout>That page link expired; showing the first page.</Callout>
{/if}
