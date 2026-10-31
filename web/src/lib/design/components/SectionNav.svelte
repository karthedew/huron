<script lang="ts">
	import { formatCount } from '$lib/format';

	interface Section {
		label: string;
		href: string;
		current: boolean;
		/** A count to show with the label, e.g. an organization's catalogs. */
		count?: number;
	}

	interface Props {
		/** The navigation's name, e.g. "Organization". */
		label: string;
		sections: readonly Section[];
	}

	let { label, sections }: Props = $props();
</script>

<!--
	Links, not ARIA tabs: every section is its own page. Where the row has room they are tabs, the
	current one underlined on the header's bottom border. Where it may not, as on a phone, they are
	pills that wrap, the current one framed: a tab on a first row would draw its underline across
	the middle of the header. Only the current tab draws its line, never a transparent one for the
	others: forced colors draw every border in the text's color, which marked them all alike.
-->
<div class="@container mt-5">
	<nav aria-label={label} class="flex flex-wrap gap-1 @max-lg:pb-3">
		{#each sections as section (section.label)}
			<a
				href={section.href}
				aria-current={section.current ? 'page' : undefined}
				class={[
					'relative inline-flex items-center gap-2 text-sm font-semibold no-underline',
					'@lg:-mb-px @lg:px-3 @lg:pt-2.5 @lg:pb-3 @max-lg:rounded-md',
					section.current
						? 'text-app-fg @max-lg:border-2 @max-lg:border-brand-strong @max-lg:bg-brand-soft @max-lg:px-2.5 @max-lg:py-1'
						: 'text-app-muted hover:text-app-fg @max-lg:px-3 @max-lg:py-1.5 @max-lg:hover:bg-app-code'
				]}
				>{#if section.current}<span
						class="absolute inset-x-0 bottom-0 hidden border-b-2 border-brand-strong @lg:block"
						aria-hidden="true"
					></span>{/if}{section.label}{#if section.count !== undefined}<span
						class="rounded-full bg-app-code px-2 text-xs font-semibold text-app-muted"
						>{formatCount(section.count)}</span
					>{/if}</a
			>
		{/each}
	</nav>
</div>
