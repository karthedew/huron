<script lang="ts">
	import { Copy } from '@lucide/svelte';
	import { Clipboard } from './clipboard.svelte';

	/** Place inside a positioned header row so the selectable fallback stays within its width. */
	interface Props {
		value: string;
	}
	let { value }: Props = $props();
	const clipboard = new Clipboard();
	let failed = $state(false);
	async function copy() {
		await clipboard.copy(value, "Couldn't copy; select the full path below.");
		failed = clipboard.status !== 'Copied';
	}
</script>

<div class="min-w-0 shrink-0">
	{#if clipboard.available}
		<button
			type="button"
			aria-label="Copy full path"
			title="Copy full path: {value}"
			onclick={copy}
			class="inline-grid size-8 place-items-center rounded-md border border-transparent text-app-muted hover:border-app-line hover:bg-app-code hover:text-app-fg"
		>
			<Copy size={16} aria-hidden="true" />
		</button>
	{/if}
	{#if !clipboard.available || failed}
		<details open={failed}>
			<summary
				aria-label="Show full path"
				title="Show full path: {value}"
				class="grid size-8 cursor-pointer list-none place-items-center rounded-md border border-transparent text-app-muted hover:border-app-line hover:bg-app-code hover:text-app-fg marker:content-none"
			>
				<Copy size={16} aria-hidden="true" />
			</summary>
			<div
				class="absolute top-full left-0 z-10 mt-1 w-64 max-w-full rounded-md border border-app-line bg-app-card p-3 shadow-md"
			>
				<label class="block text-xs font-semibold text-app-muted"
					>Full path
					<input
						readonly
						{value}
						onfocus={(event) => event.currentTarget.select()}
						class="mono mt-1 w-full rounded-md border border-app-line bg-app-code px-2 py-1 text-xs text-app-fg"
					/>
				</label>
			</div>
		</details>
	{/if}
	<span role="status" class="sr-only">{clipboard.status}</span>
</div>
