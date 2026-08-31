<script lang="ts">
	import { Bell, Check, KeyRound, LogIn, Save, ShieldCheck, UserRound, X } from '@lucide/svelte';
	import { untrack } from 'svelte';
	import Badge from '$design/components/Badge.svelte';
	import DataTable from '$design/components/DataTable.svelte';
	import type { PageData } from './$types';

	type Tab = 'profile' | 'preferences' | 'api-keys' | 'access';
	let { data }: { data: PageData } = $props();
	let active = $state<Tab>(untrack(() => (data.initialTab as Tab) ?? 'profile'));
	let saved = $state(false);
	const tabs: { id: Tab; label: string }[] = [
		{ id: 'profile', label: 'Profile' },
		{ id: 'preferences', label: 'Preferences' },
		{ id: 'api-keys', label: 'API keys' },
		{ id: 'access', label: 'Effective access' }
	];

	function signIn() {
		sessionStorage.removeItem('huron-preview-signed-out');
		window.location.assign('/account');
	}
</script>

<svelte:head><title>User settings · Huron</title></svelte:head>

{#if data.signedOut}
	<section
		class="mx-auto mt-10 max-w-lg rounded-xl border border-app-line bg-app-card p-8 text-center shadow-[var(--shadow-sm)]"
	>
		<span
			class="mx-auto grid size-12 place-items-center rounded-full bg-brand-soft text-brand-strong"
			><LogIn size={21} /></span
		>
		<h1 class="mt-5">You’re signed out</h1>
		<p class="mt-2 text-sm text-app-muted">
			Your fixture workspace session has ended. Production deployments will continue through the
			configured OIDC provider.
		</p>
		<button
			type="button"
			onclick={signIn}
			class="mt-6 inline-flex h-9 items-center gap-2 rounded-md bg-brand px-4 text-sm font-semibold text-[#062d29]"
			><LogIn size={15} /> Sign in again</button
		>
	</section>
{:else}
	<div class="mb-6 flex items-center gap-3">
		<span
			class="grid size-11 place-items-center rounded-full bg-[#26333b] text-sm font-semibold text-white"
			>KS</span
		>
		<div>
			<p class="text-xs font-medium text-app-muted">Personal workspace</p>
			<h1>User settings</h1>
		</div>
	</div>

	<nav
		class="mb-6 flex gap-1 overflow-x-auto border-b border-app-line"
		aria-label="User settings sections"
	>
		{#each tabs as tab}<button
				type="button"
				onclick={() => (active = tab.id)}
				class="relative shrink-0 px-3 py-2.5 text-sm font-medium"
				class:text-brand-strong={active === tab.id}
				class:text-app-muted={active !== tab.id}
				>{tab.label}{#if active === tab.id}<span
						class="absolute inset-x-2 bottom-[-1px] h-0.5 bg-brand"
					></span>{/if}</button
			>{/each}
	</nav>

	{#if saved}<div
			class="mb-4 flex items-center gap-2 rounded-md border border-[var(--note-line)] bg-[var(--note-bg)] px-3 py-2.5 text-sm"
		>
			<Check size={16} class="text-app-success" /> Settings saved.<button
				type="button"
				onclick={() => (saved = false)}
				class="ml-auto"
				aria-label="Dismiss"><X size={15} class="text-app-muted" /></button
			>
		</div>{/if}

	{#if active === 'profile'}
		<div class="grid gap-5 xl:grid-cols-[minmax(0,1fr)_320px]">
			<section class="rounded-lg border border-app-line bg-app-card">
				<div class="border-b border-app-line p-5">
					<div class="flex items-center gap-3">
						<span class="grid size-9 place-items-center rounded-md bg-brand-soft text-brand-strong"
							><UserRound size={18} /></span
						>
						<div>
							<h2 class="m-0 border-0 p-0 text-base font-semibold">Profile</h2>
							<p class="mt-0.5 text-sm text-app-muted">
								Your identity and catalog display details.
							</p>
						</div>
					</div>
				</div>
				<div class="grid gap-4 p-5 sm:grid-cols-2">
					<label class="grid gap-1.5 text-xs font-semibold text-app-muted"
						>Display name<input
							value={data.whoami.displayName}
							class="h-10 rounded-md border border-app-line bg-app-bg px-3 text-sm font-normal text-app-fg"
						/></label
					><label class="grid gap-1.5 text-xs font-semibold text-app-muted"
						>Email / subject<input
							value={data.whoami.subject}
							disabled
							class="h-10 rounded-md border border-app-line bg-app-bg px-3 text-sm font-normal text-app-muted"
						/></label
					><label class="grid gap-1.5 text-xs font-semibold text-app-muted"
						>Default organization<select
							class="h-10 rounded-md border border-app-line bg-app-bg px-3 text-sm font-normal text-app-fg"
							><option>Example Organization</option><option>Second Organization</option></select
						></label
					><label class="grid gap-1.5 text-xs font-semibold text-app-muted"
						>Time zone<select
							class="h-10 rounded-md border border-app-line bg-app-bg px-3 text-sm font-normal text-app-fg"
							><option>America/Denver</option><option>UTC</option></select
						></label
					>
				</div>
				<div class="flex justify-end border-t border-app-line p-4">
					<button
						type="button"
						onclick={() => (saved = true)}
						class="inline-flex h-9 items-center gap-2 rounded-md bg-brand px-3.5 text-sm font-semibold text-[#062d29]"
						><Save size={15} /> Save profile</button
					>
				</div>
			</section>
			<aside class="rounded-lg border border-app-line bg-app-card p-5">
				<h2 class="m-0 border-0 p-0 text-sm font-semibold">Identity provider</h2>
				<dl class="mt-4 grid gap-3 text-xs">
					<div class="flex justify-between">
						<dt class="text-app-muted">Provider</dt>
						<dd class="font-semibold">OpenShift OIDC</dd>
					</div>
					<div class="flex justify-between">
						<dt class="text-app-muted">Status</dt>
						<dd class="flex items-center gap-1.5 font-semibold text-app-success">
							<span class="size-1.5 rounded-full bg-app-success"></span>Connected
						</dd>
					</div>
					<div class="flex justify-between">
						<dt class="text-app-muted">Session</dt>
						<dd class="font-semibold">Browser cookie</dd>
					</div>
				</dl>
				<p class="mt-5 border-t border-app-line pt-4 text-xs leading-5 text-app-muted">
					Your email and group membership are controlled by the identity provider.
				</p>
			</aside>
		</div>
	{:else if active === 'preferences'}
		<section class="max-w-3xl rounded-lg border border-app-line bg-app-card">
			<div class="border-b border-app-line p-5">
				<div class="flex items-center gap-3">
					<span class="grid size-9 place-items-center rounded-md bg-brand-soft text-brand-strong"
						><Bell size={18} /></span
					>
					<div>
						<h2 class="m-0 border-0 p-0 text-base font-semibold">Preferences</h2>
						<p class="mt-0.5 text-sm text-app-muted">
							Personalize notifications and default views.
						</p>
					</div>
				</div>
			</div>
			<div class="divide-y divide-app-line p-5">
				<label class="flex items-start gap-3 py-3"
					><input type="checkbox" checked class="mt-0.5 size-4 accent-[var(--brand-strong)]" /><span
						><strong class="block text-sm">Ingest completion</strong><span
							class="text-xs text-app-muted"
							>Notify me when an ingest session commits or fails.</span
						></span
					></label
				><label class="flex items-start gap-3 py-3"
					><input type="checkbox" checked class="mt-0.5 size-4 accent-[var(--brand-strong)]" /><span
						><strong class="block text-sm">Permission changes</strong><span
							class="text-xs text-app-muted">Notify me when my effective access changes.</span
						></span
					></label
				><label class="flex items-start gap-3 py-3"
					><input type="checkbox" class="mt-0.5 size-4 accent-[var(--brand-strong)]" /><span
						><strong class="block text-sm">Publication queue</strong><span
							class="text-xs text-app-muted">Daily summary of candidates awaiting review.</span
						></span
					></label
				>
			</div>
			<div class="flex justify-end border-t border-app-line p-4">
				<button
					type="button"
					onclick={() => (saved = true)}
					class="h-9 rounded-md bg-brand px-3.5 text-sm font-semibold text-[#062d29]"
					>Save preferences</button
				>
			</div>
		</section>
	{:else if active === 'api-keys'}
		<section>
			<div class="mb-4 flex items-end justify-between">
				<div>
					<h2 class="m-0 border-0 p-0 text-base font-semibold">API keys</h2>
					<p class="mt-1 text-sm text-app-muted">
						Programmatic access for HPC nodes, scripts, and clients.
					</p>
				</div>
				<button
					type="button"
					class="inline-flex h-9 items-center gap-2 rounded-md bg-brand px-3.5 text-sm font-semibold text-[#062d29]"
					><KeyRound size={15} /> Create API key</button
				>
			</div>
			<div class="rounded-lg border border-app-line bg-app-card p-4">
				<DataTable caption="Keys issued to you."
					>{#snippet head()}<tr
							><th>Name</th><th>Scopes</th><th>Restricted to</th><th>Last used</th><th>Expires</th
							></tr
						>{/snippet}{#each data.keys as key}<tr
							><td>{key.name}</td><td
								>{#each key.scopes as scope}<Badge>{scope}</Badge>{/each}</td
							><td class="mono">{key.projectRestriction ?? '—'}</td><td class="mono"
								>{key.lastUsedAt?.slice(0, 10) ?? 'never'}</td
							><td class="mono">{key.expiresAt?.slice(0, 10) ?? '—'}</td></tr
						>{/each}</DataTable
				>
			</div>
			<p class="mt-3 text-xs text-app-muted">
				New secrets are shown exactly once. Browser sessions never use API keys.
			</p>
		</section>
	{:else}
		<section>
			<div class="mb-4">
				<h2 class="m-0 border-0 p-0 text-base font-semibold">Effective access</h2>
				<p class="mt-1 text-sm text-app-muted">Why you can see and act on resources in Huron.</p>
			</div>
			<div class="overflow-hidden rounded-lg border border-app-line bg-app-card">
				<div
					class="grid grid-cols-[minmax(0,1fr)_minmax(180px,1fr)] border-b border-app-line bg-app-bg px-4 py-2.5 text-[10px] font-semibold uppercase tracking-wider text-app-muted"
				>
					<span>Role</span><span>Scope</span>
				</div>
				{#each data.whoami.bindings as binding}<div
						class="grid grid-cols-[minmax(0,1fr)_minmax(180px,1fr)] items-center border-b border-app-line px-4 py-3 last:border-0"
					>
						<div class="flex items-center gap-2">
							<ShieldCheck size={16} class="text-brand-strong" /><span
								class="text-sm font-semibold capitalize">{binding.role.replace('_', ' ')}</span
							>
						</div>
						<span class="font-mono text-xs text-app-muted">{binding.scope}</span>
					</div>{/each}
			</div>
		</section>
	{/if}
{/if}
