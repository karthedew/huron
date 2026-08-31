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

<button
	type="button"
	onclick={toggleTheme}
	class="grid size-9 place-items-center rounded-md border border-app-line bg-app-card text-app-muted transition hover:border-app-line-strong hover:text-app-fg"
	aria-label={dark ? 'Use light mode' : 'Use dark mode'}
	title={dark ? 'Use light mode' : 'Use dark mode'}
>
	{#if dark}<Sun size={17} />{:else}<Moon size={17} />{/if}
</button>
