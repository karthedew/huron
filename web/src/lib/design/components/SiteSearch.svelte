<script lang="ts">
	import { Search as SearchIcon } from '@lucide/svelte';
	import { MAX_TEXT_LENGTH, tidySearchForm } from '$lib/search';

	interface Props {
		/** The search page it submits to, without a query: what it searches (see `searchScope`). */
		action: string;
		/** The name of the catalog or organization it searches; `null` where the page asks which. */
		name: string | null;
		/** The text of the search a search page shows, else `''`. */
		q: string;
	}

	let { action, name, q }: Props = $props();

	const id = $props.id();
	const label = $derived(name === null ? 'Search' : `Search ${name}`);

	/** With scripts, it leads to the search's canonical address, the text trimmed or left out. */
	function tidy(event: FormDataEvent) {
		tidySearchForm(event.formData, { drafts: false });
	}
</script>

<!--
	One field, no scope to choose: it searches what the page belongs to, which its name says. Below
	md the bottom navigation's Search leads to the same page instead.
-->
<form
	role="search"
	aria-label="Site search"
	method="GET"
	{action}
	onformdata={tidy}
	class="hidden min-w-0 flex-1 md:block md:max-w-md"
>
	<label for="{id}-q" class="sr-only">{label}</label>
	<div class="relative">
		<SearchIcon
			size={16}
			class="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-app-muted"
			aria-hidden="true"
		/>
		<input
			id="{id}-q"
			name="q"
			type="search"
			value={q}
			maxlength={MAX_TEXT_LENGTH}
			placeholder="{label}…"
			spellcheck="false"
			autocomplete="off"
			class="block h-9 w-full min-w-0 rounded-md border border-app-line bg-app-card pr-3 pl-9 text-sm text-app-fg placeholder:text-app-muted hover:border-app-line-strong"
		/>
	</div>
</form>
