<script lang="ts">
	import { afterNavigate } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { ChevronRight, Database, FileText, Folder, FolderOpen } from '@lucide/svelte';
	import { onMount, tick } from 'svelte';
	import { SvelteMap } from 'svelte/reactivity';
	import {
		currentNamespace,
		fetchLevel,
		identifierInCatalog,
		isCurrentCollection,
		isCurrentNamespace,
		isEmptyLevel,
		isFailedLevel,
		lastSegment,
		opensByDefault,
		pathPrefixes,
		pinnedNode,
		type ExplorerCollection,
		type ExplorerCurrent,
		type ExplorerLevel,
		type ExplorerNamespace,
		type TrailLevel
	} from '$lib/explorer';
	import { displayName, type Named } from '$lib/names';
	import { signInAgain } from '$lib/sign-in-again';

	interface Props {
		organization: string;
		/** The organization's catalogs: the explorer's top level. */
		catalogs: readonly Named[];
		/** Whether the organization has more catalogs than `catalogs` holds. */
		moreCatalogs: boolean;
		/** The catalog the page belongs to; the explorer opens it. */
		catalog: Named;
		/**
		 * The levels the server loaded: the catalog root and those on the way to the page, where
		 * one it could not load is failed.
		 */
		levels: readonly TrailLevel[];
		current: ExplorerCurrent;
	}

	let { organization, catalogs, moreCatalogs, catalog, levels, current }: Props = $props();

	const id = $props.id();
	/** Levels this browser fetched after the page loaded, by parent path. */
	const fetched = new SvelteMap<string, ExplorerLevel>();
	/** Folders the user opened (true) or closed (false); the others follow the page. */
	const toggled = new SvelteMap<string, boolean>();
	/** Folders whose contents are on their way, or did not arrive. */
	const pending = new SvelteMap<string, 'loading' | 'failed'>();
	/** Opening and closing needs scripts; until they run, the tree is links to what is loaded. */
	let mounted = $state(false);
	/** What the explorer last said about loading a folder, for screen readers. */
	let announcement = $state('');
	/** The explorer itself: from lg it scrolls on its own. */
	let scroller = $state<HTMLElement>();

	const ROW =
		'relative flex min-w-0 flex-1 items-start gap-1.5 rounded-md py-1 pr-1.5 pl-2 no-underline';
	const PLAIN = 'font-normal text-app-fg hover:bg-app-sidebar-hover';
	/** The current row stands out by more than its color: a heavier label and a bar. */
	const MARKED = 'bg-brand-soft font-semibold text-brand-strong';
	const QUIET = 'font-normal text-app-muted hover:bg-app-sidebar-hover hover:text-app-fg';

	const serverLevels = $derived(
		new Map(
			levels.flatMap((level): Array<[string, ExplorerLevel]> =>
				isFailedLevel(level) ? [] : [[level.parent, level]]
			)
		)
	);
	/** Folders on the way to the page whose contents the server could not load. */
	const serverFailed = $derived(new Set(levels.filter(isFailedLevel).map(({ parent }) => parent)));
	/** The catalog is listed even when it is beyond the first page of the organization's. */
	const catalogRows = $derived(
		catalogs.some(({ name }) => name === catalog.name) ? catalogs : [...catalogs, catalog]
	);

	/**
	 * The nesting of a folder's contents a level indents by: a level more each, up to a few. The
	 * explorer's column is narrow, and identifiers may nest over a hundred namespaces deep:
	 * indented further, the deepest rows would leave the column and lie over the page.
	 */
	const MAX_INDENT = 8;

	onMount(() => {
		mounted = true;
		void revealCurrent();
	});

	/**
	 * Scroll the explorer, never the window, until the page's node shows: on a long tree it may lie
	 * far below the explorer's top. Where the explorer does not scroll (below lg it is not drawn),
	 * or the node shows already, nothing moves.
	 */
	async function revealCurrent() {
		await tick();
		if (scroller === undefined || scroller.scrollHeight <= scroller.clientHeight) return;
		const node = scroller.querySelector('[aria-current]');
		if (node === null) return;
		const view = scroller.getBoundingClientRect();
		const row = node.getBoundingClientRect();
		if (row.top >= view.top && row.bottom <= view.bottom) return;
		scroller.scrollTop += row.top - view.top - (view.height - row.height) / 2;
	}

	afterNavigate(() => {
		// The way to a page opens again after navigating there, also where the user had closed it.
		for (const path of ['', ...pathPrefixes(currentNamespace(current) ?? '')]) {
			toggled.delete(path);
		}
		// A folder reopened over contents only the previous page brought has nothing to show now
		// and nothing on its way: it closes, and opening it again fetches its contents.
		for (const [path, open] of [...toggled]) {
			if (open && levelOf(path) === undefined && !pending.has(path)) toggled.delete(path);
		}
		void revealCurrent();
	});

	function levelOf(parent: string): ExplorerLevel | undefined {
		return fetched.get(parent) ?? serverLevels.get(parent);
	}

	function isOpen(path: string): boolean {
		return toggled.get(path) ?? opensByDefault(path, current);
	}

	/** Where loading an open folder stands, while nothing else fills it. */
	function progressOf(path: string): 'loading' | 'failed' | undefined {
		if (!isOpen(path) || levelOf(path) !== undefined) return undefined;
		return pending.get(path) ?? (serverFailed.has(path) ? 'failed' : undefined);
	}

	/** Whether a folder may hold something: its loaded level says, else its parent's entry. */
	function hasContents(path: string, empty: boolean): boolean {
		const known = levelOf(path);
		return known === undefined ? !empty : !isEmptyLevel(known);
	}

	async function toggle(path: string) {
		if (isOpen(path)) {
			toggled.set(path, false);
			return;
		}
		toggled.set(path, true);
		if (levelOf(path) === undefined) await load(path);
	}

	async function load(path: string) {
		if (pending.get(path) === 'loading') return;
		const name = lastSegment(path);
		pending.set(path, 'loading');
		announcement = `Loading ${name}…`;
		const outcome = await fetchLevel(fetch, treeUrl(path), path);
		if (outcome.kind === 'signed-out') {
			signInAgain();
			return;
		}
		if (outcome.kind === 'failed') {
			pending.set(path, 'failed');
			announcement = `Couldn't load ${name}.`;
			return;
		}
		fetched.set(path, outcome.level);
		pending.delete(path);
		announcement = `Loaded ${name}.`;
	}

	function retry(path: string) {
		// The Retry button goes while the contents load: focus waits on the folder's toggle.
		document.getElementById(toggleId(path))?.focus();
		void load(path);
	}

	/** Namespace paths never hold `:`, so the root cannot collide with one. */
	function toggleId(path: string): string {
		return path === '' ? `${id}-catalog` : `${id}-folder:${path}`;
	}

	function treeUrl(parent: string): string {
		const endpoint = resolve('/(app)/catalogs/[catalog=segment]/tree', { catalog: catalog.name });
		return `${endpoint}?parent=${encodeURIComponent(parent)}`;
	}

	function catalogHref(name: string): string {
		return resolve('/(app)/catalogs/[catalog=segment]', { catalog: name });
	}

	function namespaceHref(path: string): string {
		return resolve('/(app)/catalogs/[catalog=segment]/namespaces/[path=dotted]', {
			catalog: catalog.name,
			path
		});
	}

	function collectionHref(identifier: string): string {
		return resolve('/(app)/catalogs/[catalog=segment]/collections/[identifier=dotted]', {
			catalog: catalog.name,
			identifier: identifierInCatalog(identifier)
		});
	}

	/** The page that lists what follows a level's first page: the catalog's or the namespace's. */
	function moreHref(parent: string, list: 'namespaces' | 'collections', cursor: string): string {
		const query = encodeURIComponent(cursor);
		if (parent === '') return `${catalogHref(catalog.name)}?cursor=${query}`;
		return `${namespaceHref(parent)}?${list}_cursor=${query}`;
	}

	function catalogCurrent(): 'page' | 'true' | undefined {
		if (current.kind !== 'catalog') return undefined;
		return current.overview ? 'page' : 'true';
	}

	/** A collection's leaf is the page on its overview; on its other tabs it marks their section. */
	function collectionCurrent(identifier: string): 'page' | 'true' | undefined {
		if (!isCurrentCollection(identifier, catalog.name, current)) return undefined;
		return current.kind === 'collection' && current.overview ? 'page' : 'true';
	}
</script>

{#snippet bar()}
	<span class="absolute inset-y-1 left-0 border-l-2 border-brand-strong" aria-hidden="true"></span>
{/snippet}

{#snippet spacer()}
	<span class="size-6 shrink-0" aria-hidden="true"></span>
{/snippet}

{#snippet toggleButton(path: string, name: string, open: boolean)}
	<button
		id={toggleId(path)}
		type="button"
		aria-expanded={open}
		aria-label="Contents of {name}"
		onclick={() => toggle(path)}
		class="grid size-6 shrink-0 place-items-center rounded-md text-app-muted hover:bg-app-sidebar-hover hover:text-app-fg"
		><ChevronRight
			size={14}
			class={['transition-transform motion-reduce:transition-none', open && 'rotate-90']}
			aria-hidden="true"
		/></button
	>
{/snippet}

<!-- What sighted users see; the explorer's live region tells screen readers. -->
{#snippet status(path: string, name: string)}
	{@const progress = progressOf(path)}
	{#if progress === 'loading'}
		<p class="m-0 py-1 pl-8 text-xs text-app-muted">Loading…</p>
	{:else if progress === 'failed'}
		<!-- Retrying needs scripts; without them the folder's link still leads to its page. -->
		<p class="m-0 py-1 pl-8 text-xs">
			{#if mounted}
				<span class="text-app-muted">Couldn't load ·</span>{' '}<button
					type="button"
					aria-label="Retry loading {name}"
					onclick={() => retry(path)}
					class="font-semibold text-brand-strong underline underline-offset-2">Retry</button
				>
			{:else}
				<span class="text-app-muted">Couldn't load</span>
			{/if}
		</p>
	{/if}
{/snippet}

{#snippet folder(node: ExplorerNamespace)}
	{@const open = isOpen(node.path)}
	{@const marked = isCurrentNamespace(node.path, current)}
	<li class="min-w-0" aria-busy={progressOf(node.path) === 'loading' ? 'true' : undefined}>
		<div class="flex min-w-0 items-start gap-0.5">
			{#if mounted && hasContents(node.path, node.empty)}
				{@render toggleButton(node.path, node.name, open)}
			{:else}
				{@render spacer()}
			{/if}
			<a
				href={namespaceHref(node.path)}
				aria-current={marked ? 'page' : undefined}
				class={[ROW, marked ? MARKED : PLAIN]}
			>
				{#if marked}{@render bar()}{/if}
				{#if open && levelOf(node.path)}
					<FolderOpen size={15} class="mt-0.5 shrink-0 text-brand-strong" aria-hidden="true" />
				{:else}
					<Folder size={15} class="mt-0.5 shrink-0 text-brand-strong" aria-hidden="true" />
				{/if}
				<span class="min-w-0 wrap-anywhere">{node.name}</span>
			</a>
		</div>
		{#if open}{@render level(node.path, node.name)}{/if}
		{@render status(node.path, node.name)}
	</li>
{/snippet}

{#snippet leaf(node: ExplorerCollection)}
	{@const marked = collectionCurrent(node.identifier)}
	<li class="min-w-0">
		<div class="flex min-w-0 items-start gap-0.5">
			{@render spacer()}
			<a
				href={collectionHref(node.identifier)}
				aria-current={marked}
				class={[ROW, marked ? MARKED : PLAIN]}
			>
				{#if marked}{@render bar()}{/if}
				<FileText size={15} class="mt-0.5 shrink-0 text-app-muted" aria-hidden="true" />
				<span class="min-w-0 wrap-anywhere">{node.name}</span>
			</a>
		</div>
	</li>
{/snippet}

{#snippet more(parent: string, name: string, list: 'namespaces' | 'collections', cursor: string)}
	<li class="min-w-0">
		<div class="flex min-w-0 items-start gap-0.5">
			{@render spacer()}
			<a
				href={moreHref(parent, list, cursor)}
				aria-label="More {list} in {name}"
				class={[ROW, QUIET]}>More…</a
			>
		</div>
	</li>
{/snippet}

{#snippet level(parent: string, name: string)}
	{@const known = levelOf(parent)}
	{@const extra = known ? pinnedNode(known, catalog.name, current) : null}
	{@const depth = parent === '' ? 1 : parent.split('.').length + 1}
	{#if known && (extra || !isEmptyLevel(known))}
		<!-- Set in by a line under its folder's chevron, but deeper than a few levels no further. -->
		<ul
			class={[
				'm-0 grid list-none gap-px p-0',
				depth <= MAX_INDENT && 'ml-3 border-l border-app-line'
			]}
		>
			{#each known.namespaces as node (node.path)}
				{@render folder(node)}
			{/each}
			{#if known.namespacesNext}
				{@render more(parent, name, 'namespaces', known.namespacesNext)}
			{/if}
			{#if extra?.kind === 'namespace'}
				{@render folder(extra.node)}
			{/if}
			{#each known.collections as node (node.identifier)}
				{@render leaf(node)}
			{/each}
			{#if known.collectionsNext}
				{@render more(parent, name, 'collections', known.collectionsNext)}
			{/if}
			{#if extra?.kind === 'collection'}
				{@render leaf(extra.node)}
			{/if}
		</ul>
	{/if}
{/snippet}

<!--
	From lg it stays in view and scrolls on its own: a tree of many folders would otherwise make
	the page many times its content's height and leave the page's node out of sight. No tabindex
	or region role: every row is a link, so Tab already scrolls it, and the landmark stays a
	navigation. Its padding keeps the focus rings of the rows at its edges inside it.
-->
<nav
	bind:this={scroller}
	aria-labelledby="{id}-heading"
	class="text-sm lg:sticky lg:top-20 lg:max-h-explorer lg:scroll-py-1 lg:overflow-y-auto lg:p-1 lg:scrollbar-thin"
>
	<h2
		id="{id}-heading"
		class="m-0 mb-2 border-0 p-0 px-1.5 text-xs font-semibold tracking-wide text-app-muted uppercase"
	>
		Explorer
	</h2>
	<ul class="m-0 grid list-none gap-px p-0">
		{#each catalogRows as row (row.name)}
			{@const label = displayName(row)}
			<li class="min-w-0">
				{#if row.name === catalog.name}
					{@const open = isOpen('')}
					{@const marked = catalogCurrent()}
					<div class="flex min-w-0 items-start gap-0.5">
						{#if mounted && hasContents('', false)}
							{@render toggleButton('', label, open)}
						{:else}
							{@render spacer()}
						{/if}
						<a
							href={catalogHref(row.name)}
							aria-current={marked}
							class={[ROW, marked ? MARKED : PLAIN]}
						>
							{#if marked}{@render bar()}{/if}
							<Database size={15} class="mt-0.5 shrink-0 text-brand-strong" aria-hidden="true" />
							<span class="min-w-0 wrap-anywhere">{label}</span>
						</a>
					</div>
					{#if open}{@render level('', label)}{/if}
				{:else}
					<div class="flex min-w-0 items-start gap-0.5">
						{@render spacer()}
						<a href={catalogHref(row.name)} class={[ROW, PLAIN]}>
							<Database size={15} class="mt-0.5 shrink-0 text-app-muted" aria-hidden="true" />
							<span class="min-w-0 wrap-anywhere">{label}</span>
						</a>
					</div>
				{/if}
			</li>
		{/each}
		{#if moreCatalogs}
			<li class="min-w-0">
				<div class="flex min-w-0 items-start gap-0.5">
					{@render spacer()}
					<a
						href={resolve('/(app)/orgs/[org=segment]', { org: organization })}
						aria-label="More catalogs of this organization"
						class={[ROW, QUIET]}>More…</a
					>
				</div>
			</li>
		{/if}
	</ul>
	<!--
		Always rendered and outside the folders, which are busy while they load: screen readers know
		the live region before it speaks, and focus stays on the folder's toggle meanwhile.
	-->
	<p role="status" class="sr-only">{announcement}</p>
</nav>
