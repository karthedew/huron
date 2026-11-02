<script lang="ts">
	import type { Commit } from '$api/types';
	import { formatCount, formatTimestamp, shortId, timestampAttribute } from '$lib/format';
	import CopyText from './CopyText.svelte';

	interface Props {
		/** The list's name, e.g. "Commits of ACE MAG level 2, 2024". */
		label: string;
		commits: readonly Commit[];
	}

	let { label, commits }: Props = $props();
</script>

<!-- A log, newest first: with room, the time stands in its own column beside the commit. -->
<ol class="@container m-0 list-none p-0" aria-label={label}>
	{#each commits as commit (commit.id)}
		{@const short = shortId(commit.id)}
		<li
			class="grid min-w-0 gap-x-4 gap-y-0.5 border-b border-app-line py-3 first:pt-0 last:border-b-0 @2xl:grid-cols-log"
		>
			<time
				class="text-xs text-app-muted @2xl:pt-0.5"
				datetime={timestampAttribute(commit.created_at)}>{formatTimestamp(commit.created_at)}</time
			>
			<div class="min-w-0">
				{#if commit.message}
					<p class="m-0 text-sm font-semibold whitespace-pre-line wrap-anywhere">
						{commit.message}
					</p>
				{:else}
					<p class="m-0 text-sm text-app-muted italic">No message</p>
				{/if}
				<p class="mt-1 mb-0 flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-app-muted">
					<span
						><span aria-hidden="true"
							><span class="text-app-success">+{formatCount(commit.adds)}</span> /
							<span class="text-app-danger">−{formatCount(commit.removes)}</span></span
						><span class="sr-only"
							>{formatCount(commit.adds)} added, {formatCount(commit.removes)} removed</span
						></span
					>
					<span
						><span aria-hidden="true"
							>revision {formatCount(commit.base_version)} → {formatCount(commit.new_version)}</span
						><span class="sr-only"
							>revision {formatCount(commit.base_version)} to {formatCount(
								commit.new_version
							)}</span
						></span
					>
					<span class="min-w-0 wrap-anywhere">by {commit.actor}</span>
					<span class="min-w-0 wrap-anywhere">from {commit.host}</span>
				</p>
				<p class="mt-1 mb-0 flex min-w-0 flex-wrap items-center gap-x-1.5 text-sm">
					<span class="text-xs text-app-muted">Commit</span>
					<CopyText label="id of commit {short}" value={commit.id} shown={short} />
				</p>
			</div>
		</li>
	{/each}
</ol>
