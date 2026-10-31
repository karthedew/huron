<script lang="ts">
	import { cliCommand } from '$lib/cli';
	import CliHint from './CliHint.svelte';

	interface Props {
		catalog: string;
		/** The full identifier of the parent: the catalog, or `catalog.path`. */
		parent: string;
	}

	let { catalog, parent }: Props = $props();
</script>

<!-- For catalog administrators: where the tree grows, the CLI creates the next namespace. -->
<CliHint
	title="Create a namespace here"
	command={cliCommand({ verb: 'namespace create', catalog, parent, allowCollections: true })}
/>
<p class="mt-2 mb-0 text-xs text-app-muted">
	Without <code>--allow-collections</code> the new namespace holds only other namespaces.
</p>
