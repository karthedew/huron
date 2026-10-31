<script lang="ts">
	import { Moon, Sun } from '@lucide/svelte';
	import { onMount } from 'svelte';

	let dark = $state(false);

	onMount(() => {
		dark = document.documentElement.classList.contains('dark');
	});

	function toggleTheme() {
		dark = !dark;
		document.documentElement.classList.toggle('dark', dark);
		localStorage.setItem('huron-theme', dark ? 'dark' : 'light');
	}
</script>

<!--
	Without scripts it could do nothing, so it does not show. Its icon follows the page's theme
	itself, which `app.html` sets before the page draws, so it is right before the page hydrates.
-->
<button
	type="button"
	onclick={toggleTheme}
	class="grid size-9 shrink-0 place-items-center rounded-md border border-app-line bg-app-card text-app-muted transition hover:border-app-line-strong hover:text-app-fg no-js:hidden"
	aria-label={dark ? 'Use light mode' : 'Use dark mode'}
	title={dark ? 'Use light mode' : 'Use dark mode'}
>
	<Moon size={17} class="dark:hidden" aria-hidden="true" /><Sun
		size={17}
		class="hidden dark:block"
		aria-hidden="true"
	/>
</button>
