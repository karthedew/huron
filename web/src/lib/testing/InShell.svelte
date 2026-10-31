<script lang="ts">
	import type { Component } from 'svelte';
	import type { Organization } from '$api/types';
	import { setShellOrganization } from '$lib/shell';

	// For component tests of pages inside the shell: gives them what `(app)/+layout.svelte` does.
	interface Props {
		page: Component;
		/** What the shell shows as the current organization. */
		organization?: Organization | null;
	}

	let { page: Page, organization = null }: Props = $props();

	setShellOrganization(() => organization);
</script>

<Page />
