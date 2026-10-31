<script lang="ts">
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import { LogOut } from '@lucide/svelte';
	import CliHint from '$design/components/CliHint.svelte';
	import { formatTimestamp, timestampAttribute } from '$lib/format';
	import type { RoleTarget } from '$lib/roles';
	import { pageTitle } from '$lib/title';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();

	const user = $derived(data.user);

	function targetHref(target: RoleTarget): string | null {
		if (target.kind === 'organization') {
			return resolve('/(app)/orgs/[org=segment]', { org: target.name });
		}
		if (target.kind === 'catalog') {
			return resolve('/(app)/catalogs/[catalog=segment]', { catalog: target.name });
		}
		return null;
	}
</script>

<svelte:head><title>{pageTitle('Account')}</title></svelte:head>

{#snippet time(iso: string)}
	<time datetime={timestampAttribute(iso)}>{formatTimestamp(iso)}</time>
{/snippet}

<h1>Account</h1>
<p class="mt-2 mb-0 text-sm text-app-muted">
	How Huron knows you in this browser. The website reads; the huron CLI makes changes.
</p>

<div class="mt-6 grid items-start gap-4 lg:grid-cols-2">
	<section
		aria-labelledby="account-identity"
		class="rounded-card border border-app-line bg-app-card p-5"
	>
		<h2 id="account-identity" class="m-0 border-0 p-0 text-base font-semibold">Signed in</h2>
		<dl class="mt-3 mb-0 grid gap-3 text-sm">
			<div>
				<dt class="text-xs font-semibold text-app-muted">Name</dt>
				<dd class="m-0 wrap-anywhere">{user.name || user.subject}</dd>
			</div>
			<div>
				<dt class="text-xs font-semibold text-app-muted">Subject</dt>
				<dd class="mono m-0 wrap-anywhere">{user.subject}</dd>
			</div>
			<div>
				<dt class="text-xs font-semibold text-app-muted">Session ends</dt>
				<dd class="m-0">{@render time(user.expiresAt)}</dd>
			</div>
		</dl>
		<form method="POST" action={resolve('/logout')} class="mt-4 mb-0">
			<button
				type="submit"
				class="inline-flex h-9 items-center gap-2 rounded-md border border-app-line bg-app-card px-3 text-sm font-semibold text-app-fg hover:border-app-line-strong"
				><LogOut size={15} aria-hidden="true" />Sign out</button
			>
		</form>
	</section>

	<section
		aria-labelledby="account-groups"
		class="rounded-card border border-app-line bg-app-card p-5"
	>
		<h2 id="account-groups" class="m-0 border-0 p-0 text-base font-semibold">Groups</h2>
		<p class="mt-3 mb-0 text-sm">As of sign-in at {@render time(user.signedInAt)}:</p>
		{#if user.groups.length > 0}
			<ul class="mt-2 mb-0 flex list-none flex-wrap gap-1.5 p-0">
				{#each user.groups as group (group)}
					<li><code class="break-all">{group}</code></li>
				{/each}
			</ul>
		{:else}
			<p class="mt-2 mb-0 text-sm">Huron received no groups for your account.</p>
		{/if}
		<p class="mt-3 mb-0 text-sm text-app-muted">
			Groups are read when you sign in; if you were just added to a group, sign out and sign in
			again.
		</p>
	</section>
</div>

<section
	aria-labelledby="account-roles"
	class="mt-4 rounded-card border border-app-line bg-app-card p-5"
>
	<h2 id="account-roles" class="m-0 border-0 p-0 text-base font-semibold">Roles</h2>
	{#if data.roleSentences === null}
		<p class="mt-3 mb-0 text-sm">
			Your roles couldn't be loaded.
			<a
				href={page.url.pathname + page.url.search}
				data-sveltekit-reload
				class="font-semibold underline underline-offset-2">Try again</a
			>
		</p>
	{:else if data.roleSentences.length === 0}
		<p class="mt-3 mb-0 text-sm">Your groups hold no roles in Huron.</p>
	{:else}
		<ul class="mt-3 mb-0 grid list-none gap-3 p-0">
			{#each data.roleSentences as sentence (sentence.key)}
				{@const target = sentence.target}
				{@const href = targetHref(target)}
				<li class="text-sm wrap-anywhere">
					<!-- Underlined: in a sentence, the link's color alone would not set it apart. -->
					<p class="m-0">
						{sentence.lead}{#if target.kind !== 'platform'}{' '}{#if href}<a
									{href}
									class="underline underline-offset-2 hover:decoration-2">{target.label}</a
								>{:else}{target.label}{/if}{#if target.kind === 'catalog' && target.context}{' '}in
								{target.context}{/if}{/if}.
					</p>
					{#if sentence.abilities}
						<p class="mt-0.5 mb-0 text-app-muted">{sentence.abilities}</p>
					{/if}
				</li>
			{/each}
		</ul>
	{/if}
</section>

<section aria-labelledby="account-cli" class="mt-4 max-w-3xl">
	<h2 id="account-cli" class="mt-6 border-0 p-0 text-base font-semibold">The huron CLI</h2>
	<p class="mt-2 mb-3 text-sm text-app-muted">
		The CLI signs in with the same company account. It finds the Huron service through its own
		configuration.
	</p>
	<CliHint
		title="Sign in and see what Huron knows about you"
		command={'huron login\nhuron whoami'}
	/>
</section>
