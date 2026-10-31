<script lang="ts">
	import { resolve } from '$app/paths';
	import { Folder } from '@lucide/svelte';
	import type { Namespace } from '$api/types';
	import { namespaceContents, namespaceKind } from '$lib/namespaces';
	import Badge from './Badge.svelte';

	interface Props {
		/** The list's name, e.g. "Namespaces". */
		label: string;
		namespaces: readonly Namespace[];
	}

	let { label, namespaces }: Props = $props();
</script>

<ul class="m-0 grid list-none gap-2 p-0" aria-label={label}>
	{#each namespaces as namespace (namespace.id)}
		{@const kind = namespaceKind(namespace)}
		<!-- With room, what the namespace holds stands on the right of its name. -->
		<li
			class="@container rounded-card border border-app-line bg-app-card px-4 py-3 hover:border-app-line-strong"
		>
			<div
				class="flex flex-col gap-1 @2xl:flex-row @2xl:items-start @2xl:justify-between @2xl:gap-4"
			>
				<div class="flex min-w-0 gap-3">
					<Folder size={18} class="mt-0.5 shrink-0 text-brand-strong" aria-hidden="true" />
					<p class="m-0 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
						<a
							href={resolve('/(app)/catalogs/[catalog=segment]/namespaces/[path=dotted]', {
								catalog: namespace.catalog,
								path: namespace.path
							})}
							class="font-semibold wrap-anywhere text-app-fg no-underline hover:underline"
							>{namespace.name}</a
						>
						<Badge tone={kind.tone}>{kind.label}</Badge>
					</p>
				</div>
				<p class="m-0 pl-7.5 text-xs text-app-muted @2xl:shrink-0 @2xl:pt-1 @2xl:pl-0">
					{namespaceContents(namespace)}
				</p>
			</div>
		</li>
	{/each}
</ul>
