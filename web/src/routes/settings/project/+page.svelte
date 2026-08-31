<script lang="ts">
	import {
		AlertTriangle,
		Archive,
		Check,
		ChevronDown,
		Database,
		FolderCog,
		HardDrive,
		Info,
		LockKeyhole,
		Save,
		ShieldCheck,
		Trash2,
		X
	} from '@lucide/svelte';
	import PermissionEditor from '$design/components/PermissionEditor.svelte';
	import type { PageData } from './$types';

	let { data }: { data: PageData } = $props();
	let active = $state<'general' | 'access' | 'storage' | 'advanced'>('access');
	let saved = $state(false);
	let rawRetention = $state('90');
	let objectRetention = $state('365');

	const tabs = [
		{ id: 'general', label: 'General' },
		{ id: 'access', label: 'Access' },
		{ id: 'storage', label: 'Storage & retention' },
		{ id: 'advanced', label: 'Advanced' }
	] as const;
	const gib = (bytes: number) => (bytes / 1_073_741_824).toFixed(1);
	const pct = (used: number, limit: number) => Math.round((used / limit) * 100);
</script>

<svelte:head><title>Project settings · Huron</title></svelte:head>

<div class="mb-6 flex flex-col justify-between gap-4 sm:flex-row sm:items-start">
	<div class="flex items-center gap-3">
		<span class="grid size-11 place-items-center rounded-lg bg-brand-soft text-brand-strong"
			><FolderCog size={21} /></span
		>
		<div>
			<p class="text-xs font-medium text-app-muted">Example Organization / Example Study</p>
			<h1>Project settings</h1>
		</div>
	</div>
	<label class="relative block self-start"
		><span class="visually-hidden">Select project</span><select
			class="h-9 appearance-none rounded-md border border-app-line bg-app-card pl-3 pr-9 text-sm font-medium text-app-fg"
			><option>Example Study</option><option>Empty Study</option></select
		><ChevronDown
			size={14}
			class="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-app-muted"
		/></label
	>
</div>

<nav
	class="mb-6 flex gap-1 overflow-x-auto border-b border-app-line"
	aria-label="Project settings sections"
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
		<Check size={16} class="text-app-success" /> Project settings saved.<button
			type="button"
			onclick={() => (saved = false)}
			class="ml-auto"><X size={15} class="text-app-muted" /></button
		>
	</div>{/if}

{#if active === 'access'}
	<section>
		<div class="mb-4 flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
			<div>
				<h2 class="m-0 border-0 p-0 text-base font-semibold">Project permissions</h2>
				<p class="mt-1 text-sm text-app-muted">
					Project grants combine with roles inherited from Example Organization.
				</p>
			</div>
			<div class="flex items-center gap-2 text-xs text-app-muted">
				<ShieldCheck size={15} class="text-brand-strong" /> You can manage bindings
			</div>
		</div>
		<PermissionEditor
			grants={data.permissions}
			scopeLabel="example-org/example-study"
			availableRoles={['reader', 'developer', 'data_steward', 'project_admin', 'pipeline']}
		/>
	</section>
{:else if active === 'general'}
	<div class="grid gap-5 xl:grid-cols-[minmax(0,1fr)_320px]">
		<section class="rounded-lg border border-app-line bg-app-card">
			<div class="border-b border-app-line p-5">
				<h2 class="m-0 border-0 p-0 text-base font-semibold">Project identity</h2>
				<p class="mt-1 text-sm text-app-muted">
					Catalog details and governance defaults for this project.
				</p>
			</div>
			<div class="grid gap-4 p-5 sm:grid-cols-2">
				<label class="grid gap-1.5 text-xs font-semibold text-app-muted sm:col-span-2"
					>Display name<input
						value={data.project.name}
						class="h-10 rounded-md border border-app-line bg-app-bg px-3 text-sm font-normal text-app-fg"
					/></label
				><label class="grid gap-1.5 text-xs font-semibold text-app-muted"
					>Slug<input
						value={data.project.slug}
						disabled
						class="h-10 rounded-md border border-app-line bg-app-bg px-3 font-mono text-sm font-normal text-app-muted"
					/></label
				><label class="grid gap-1.5 text-xs font-semibold text-app-muted"
					>Lifecycle<select
						class="h-10 rounded-md border border-app-line bg-app-bg px-3 text-sm font-normal text-app-fg"
						><option>Active</option><option>Draft</option><option>Retired</option></select
					></label
				><label class="grid gap-1.5 text-xs font-semibold text-app-muted"
					>Default classification<select
						class="h-10 rounded-md border border-app-line bg-app-bg px-3 text-sm font-normal text-app-fg"
						><option>Unclassified</option><option>Controlled</option></select
					></label
				><label class="grid gap-1.5 text-xs font-semibold text-app-muted"
					>Owner group<select
						class="h-10 rounded-md border border-app-line bg-app-bg px-3 text-sm font-normal text-app-fg"
						><option>Science Data Team</option><option>Modeling & Simulation</option></select
					></label
				><label class="grid gap-1.5 text-xs font-semibold text-app-muted sm:col-span-2"
					>Description<textarea
						rows="4"
						class="rounded-md border border-app-line bg-app-bg p-3 text-sm font-normal text-app-fg"
						>{data.project.description}</textarea
					></label
				>
			</div>
			<div class="flex justify-end border-t border-app-line p-4">
				<button
					type="button"
					onclick={() => (saved = true)}
					class="inline-flex h-9 items-center gap-2 rounded-md bg-brand px-3.5 text-sm font-semibold text-[#062d29]"
					><Save size={15} /> Save changes</button
				>
			</div>
		</section>
		<aside class="rounded-lg border border-app-line bg-app-card p-5">
			<h2 class="m-0 border-0 p-0 text-sm font-semibold">Project facts</h2>
			<dl class="mt-4 grid gap-3 text-xs">
				<div class="flex justify-between">
					<dt class="text-app-muted">Datasets</dt>
					<dd class="font-semibold">{data.project.datasetCount}</dd>
				</div>
				<div class="flex justify-between">
					<dt class="text-app-muted">Created</dt>
					<dd class="font-semibold">Aug 16, 2026</dd>
				</div>
				<div class="flex justify-between">
					<dt class="text-app-muted">Slug</dt>
					<dd class="font-mono font-semibold">{data.project.slug}</dd>
				</div>
				<div class="flex justify-between">
					<dt class="text-app-muted">Generation</dt>
					<dd class="font-semibold">4</dd>
				</div>
			</dl>
			<div class="mt-5 flex items-start gap-2 rounded-md border border-app-line bg-app-bg p-3">
				<LockKeyhole size={14} class="mt-0.5 shrink-0 text-app-muted" />
				<p class="text-xs leading-5 text-app-muted">
					The slug and storage locator are immutable after project creation.
				</p>
			</div>
		</aside>
	</div>
{:else if active === 'storage'}
	<div class="grid gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
		<div class="grid gap-5">
			<section class="rounded-lg border border-app-line bg-app-card">
				<div class="border-b border-app-line p-5">
					<h2 class="m-0 border-0 p-0 text-base font-semibold">Storage quotas</h2>
					<p class="mt-1 text-sm text-app-muted">
						Raw and derived layers are budgeted separately and are never summed.
					</p>
				</div>
				<div class="grid gap-5 p-5 sm:grid-cols-2">
					<div>
						<div class="mb-2 flex items-center justify-between text-xs">
							<span class="flex items-center gap-2 font-semibold"
								><HardDrive size={15} class="text-[var(--raw)]" /> Raw</span
							><span class="text-app-muted"
								>{pct(data.project.quota.rawUsed, data.project.quota.rawLimit)}%</span
							>
						</div>
						<div class="h-2 overflow-hidden rounded-full bg-app-bg">
							<div
								class="h-full rounded-full bg-[var(--raw)]"
								style={`width:${pct(data.project.quota.rawUsed, data.project.quota.rawLimit)}%`}
							></div>
						</div>
						<p class="mt-2 text-xs text-app-muted">
							{gib(data.project.quota.rawUsed)} / {gib(data.project.quota.rawLimit)} GiB
						</p>
					</div>
					<div>
						<div class="mb-2 flex items-center justify-between text-xs">
							<span class="flex items-center gap-2 font-semibold"
								><Database size={15} class="text-[var(--bronze)]" /> Derived</span
							><span class="text-app-muted"
								>{pct(data.project.quota.objectUsed, data.project.quota.objectLimit)}%</span
							>
						</div>
						<div class="h-2 overflow-hidden rounded-full bg-app-bg">
							<div
								class="h-full rounded-full bg-brand"
								style={`width:${pct(data.project.quota.objectUsed, data.project.quota.objectLimit)}%`}
							></div>
						</div>
						<p class="mt-2 text-xs text-app-muted">
							{gib(data.project.quota.objectUsed)} / {gib(data.project.quota.objectLimit)} GiB
						</p>
					</div>
				</div>
			</section>
			<section class="rounded-lg border border-app-line bg-app-card">
				<div class="border-b border-app-line p-5">
					<h2 class="m-0 border-0 p-0 text-base font-semibold">Retention policy</h2>
					<p class="mt-1 text-sm text-app-muted">
						Set category defaults for new dataset revisions.
					</p>
				</div>
				<div class="grid gap-4 p-5 sm:grid-cols-2">
					<label class="grid gap-1.5 text-xs font-semibold text-app-muted"
						>Raw bulk output TTL
						<div class="relative">
							<input
								bind:value={rawRetention}
								type="number"
								class="h-10 w-full rounded-md border border-app-line bg-app-bg px-3 pr-14 text-sm font-normal text-app-fg"
							/><span class="absolute right-3 top-1/2 -translate-y-1/2 font-normal">days</span>
						</div></label
					><label class="grid gap-1.5 text-xs font-semibold text-app-muted"
						>Derived snapshot TTL
						<div class="relative">
							<input
								bind:value={objectRetention}
								type="number"
								class="h-10 w-full rounded-md border border-app-line bg-app-bg px-3 pr-14 text-sm font-normal text-app-fg"
							/><span class="absolute right-3 top-1/2 -translate-y-1/2 font-normal">days</span>
						</div></label
					><label class="grid gap-1.5 text-xs font-semibold text-app-muted sm:col-span-2"
						>Essential inputs<select
							class="h-10 rounded-md border border-app-line bg-app-bg px-3 text-sm font-normal text-app-fg"
							><option>Retain indefinitely</option><option>365 days</option></select
						></label
					>
				</div>
				<div class="flex justify-end border-t border-app-line p-4">
					<button
						type="button"
						onclick={() => (saved = true)}
						class="h-9 rounded-md bg-brand px-3.5 text-sm font-semibold text-[#062d29]"
						>Save policy</button
					>
				</div>
			</section>
		</div>
		<aside class="rounded-lg border border-[var(--warn-line)] bg-[var(--warn-bg)] p-5">
			<div class="flex items-center gap-2 font-semibold text-[var(--accent2)]">
				<AlertTriangle size={17} /> Retention consequence
			</div>
			<p class="mt-3 text-sm leading-6 text-app-muted">
				Native MCNP replay becomes unavailable after {rawRetention} days for bulk output. Essential inputs
				remain, and the earliest retained analytical representation is Bronze.
			</p>
			<div class="mt-4 flex items-start gap-2 border-t border-[var(--warn-line)] pt-4">
				<Info size={15} class="mt-0.5 shrink-0" />
				<p class="text-xs leading-5 text-app-muted">
					Existing legal holds and pins override this policy. Saving does not retroactively purge
					data.
				</p>
			</div>
		</aside>
	</div>
{:else}
	<div class="grid gap-5 lg:grid-cols-2">
		<section class="rounded-lg border border-app-line bg-app-card p-5">
			<div class="flex items-start gap-3">
				<span class="grid size-9 place-items-center rounded-md bg-app-bg text-app-muted"
					><Archive size={18} /></span
				>
				<div>
					<h2 class="m-0 border-0 p-0 text-base font-semibold">Archive project</h2>
					<p class="mt-1 text-sm text-app-muted">
						Remove the project from active navigation while preserving all immutable data.
					</p>
				</div>
			</div>
			<button
				type="button"
				class="mt-5 h-9 rounded-md border border-app-line px-3 text-sm font-semibold text-app-muted"
				>Archive project</button
			>
		</section>
		<section
			class="rounded-lg border border-[color-mix(in_srgb,var(--del)_35%,var(--line))] bg-app-card p-5"
		>
			<div class="flex items-start gap-3">
				<span
					class="grid size-9 place-items-center rounded-md bg-[color-mix(in_srgb,var(--del)_10%,transparent)] text-app-danger"
					><Trash2 size={18} /></span
				>
				<div>
					<h2 class="m-0 border-0 p-0 text-base font-semibold">Delete project</h2>
					<p class="mt-1 text-sm text-app-muted">
						Only empty projects can be deleted. This project currently contains {data.project
							.datasetCount} datasets.
					</p>
				</div>
			</div>
			<button
				type="button"
				disabled
				class="mt-5 h-9 cursor-not-allowed rounded-md border border-app-line px-3 text-sm font-semibold text-app-muted opacity-50"
				>Delete project</button
			>
		</section>
	</div>
{/if}
