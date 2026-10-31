<script lang="ts">
	import { Copy, Terminal } from '@lucide/svelte';
	import { Clipboard } from './clipboard.svelte';

	interface Props {
		/** What the command does, e.g. "Create a catalog in this organization". */
		title: string;
		/** The command line, or several lines to run in order. */
		command: string;
	}

	let { title, command }: Props = $props();

	const id = $props.id();
	/**
	 * The command's lines, each as its words. The code block breaks a line between words only, never
	 * after a hyphen inside one (`--allow-` over `collections`); a word wider than the whole block
	 * still breaks inside itself. What a line wraps onto is indented under it, so a piece of one
	 * command never reads as the next command. The count is also the field's rows.
	 */
	const lines = $derived(command.split('\n').map((line) => line.split(' ')));
	/**
	 * Unknown until mounted, so the server and a browser without scripts render the plain code
	 * block. Without a clipboard (an insecure origin) a field that selects itself on focus
	 * replaces the copy button where the hint is wide.
	 */
	const clipboard = new Clipboard();

	function selectAll(event: FocusEvent & { currentTarget: HTMLTextAreaElement }) {
		event.currentTarget.select();
	}
</script>

<section
	aria-labelledby="{id}-title"
	class="@container rounded-card border border-app-line bg-app-card p-4 text-left"
>
	<p id="{id}-title" class="m-0 flex items-center gap-2 text-sm font-semibold text-app-fg">
		<Terminal size={16} class="shrink-0 text-brand-strong" aria-hidden="true" />{title}
	</p>
	<!--
		Its own color and size: the hint's context (an empty state's muted text) has others. The
		words of a fixed command never reorder, and the text stays the command, spaces and line
		breaks included. Each line is a block that ends in its line break, where the break draws no
		empty line (between two blocks it would). Words reset the hanging indent, which would
		otherwise shift their own text.
	-->
	{#snippet codeBlock(shown: string)}
		<pre class={['m-0 min-w-0 flex-1 text-xs whitespace-pre-wrap text-app-fg', shown]}><code
				>{#each lines as words, row}<span class="block pl-hang -indent-hang"
						>{#each words as word, index}{#if index > 0}{' '}{/if}<span
								class="inline-block max-w-full indent-0 wrap-anywhere">{word}</span
							>{/each}{#if row < lines.length - 1}{'\n'}{/if}</span
					>{/each}</code
			></pre>
	{/snippet}
	<div class="mt-3 flex flex-col gap-2 @md:flex-row @md:items-start">
		{#if clipboard.available === false}
			<!--
				Where the hint is narrow, as on a phone, the code block shows every word of a command,
				which a field would cut off at its edge: there commands are read, not run. Where it is
				wide, a field that selects the whole command on focus. A field cannot indent what a line
				wraps onto, so it never wraps: each command keeps its own row, and the field scrolls
				sideways where a command is wider. Sized to its content, it also makes room for a
				horizontal scrollbar that would otherwise cover the last row; where `field-sizing` is
				unsupported, the rows are the commands.
			-->
			{@render codeBlock('@md:hidden')}
			<textarea
				readonly
				wrap="off"
				rows={lines.length}
				value={command}
				aria-labelledby="{id}-title"
				onfocus={selectAll}
				class="mono hidden min-w-0 flex-1 resize-none field-sizing-content rounded-md border border-app-line bg-app-code px-3 py-2 text-xs text-app-fg @md:block"
			></textarea>
		{:else}
			{@render codeBlock('')}
		{/if}
		{#if clipboard.available}
			<button
				type="button"
				onclick={() => clipboard.copy(command, "Couldn't copy; select the command instead.")}
				aria-label="Copy: {title}"
				class="inline-flex h-9 shrink-0 items-center justify-center gap-2 self-start rounded-md border border-app-line bg-app-card px-3 text-sm font-semibold text-app-fg hover:border-app-line-strong"
				><Copy size={15} aria-hidden="true" />Copy</button
			>
		{/if}
	</div>
	<!-- Always rendered, so screen readers know the live region before it speaks. -->
	<p role="status" class="m-0 text-xs font-semibold text-brand-strong not-empty:mt-2">
		{clipboard.status}
	</p>
	<p class="mt-2 mb-0 text-xs text-app-muted">
		This website is read-only; changes are made with the huron CLI on a machine that mounts the
		share.
	</p>
</section>
