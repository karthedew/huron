/**
 * What the header menus (organization switcher, account menu) share. Each is a `<details>`, so
 * it works without scripts; with them it closes on Escape (focusing its summary again), on a
 * click or focus outside it, and after a navigation. A click on another menu's summary is
 * outside, so one menu is open at a time. While focus is in the open menu, arrow keys, Home and
 * End move through its links and buttons.
 *
 * Wire it as `<svelte:window onkeydown={menu.keydown} onclick={menu.clickOutside} />` and
 * `<details bind:open={menu.open} bind:this={menu.details} onfocusout={menu.focusOut}>`, and
 * close it in `afterNavigate`.
 *
 * The element's own `open` decides: the browser sets it as the summary is activated, while
 * `bind:open` follows only with the `toggle` event a task later, so a key pressed right after
 * opening would otherwise meet a menu that still looks closed.
 */
export class HeaderMenu {
	open = $state(false);
	/** Set by `bind:this`, so state: Svelte expects a property that a binding writes to be one. */
	details = $state.raw<HTMLDetailsElement | null>(null);

	close = (): void => {
		this.open = false;
		if (this.details !== null) this.details.open = false;
	};

	keydown = (event: KeyboardEvent): void => {
		const details = this.details;
		if (details === null || !details.open) return;
		if (event.key === 'Escape') {
			this.close();
			details.querySelector('summary')?.focus();
			return;
		}
		if (this.#inside(document.activeElement)) move(details, event);
	};

	clickOutside = (event: MouseEvent): void => {
		if (this.details?.open && !this.#inside(event.target)) this.close();
	};

	focusOut = (event: FocusEvent): void => {
		// No related target: focus left the page, or a click landed on nothing focusable,
		// which `clickOutside` already handles.
		if (this.details?.open && event.relatedTarget !== null && !this.#inside(event.relatedTarget)) {
			this.close();
		}
	};

	#inside(target: EventTarget | null): boolean {
		return target instanceof Node && this.details !== null && this.details.contains(target);
	}
}

/** The menu's items, in the order Tab reaches them; the summary is not one. */
const ITEMS = 'a[href], button:not(:disabled)';

function move(details: HTMLDetailsElement, event: KeyboardEvent): void {
	const items = [...details.querySelectorAll<HTMLElement>(ITEMS)];
	const last = items.length - 1;
	const at = items.findIndex((item) => item === document.activeElement);
	let target: HTMLElement | undefined;
	switch (event.key) {
		case 'ArrowDown':
			target = items[at === last ? 0 : at + 1];
			break;
		case 'ArrowUp':
			target = items[at <= 0 ? last : at - 1];
			break;
		case 'Home':
			target = items[0];
			break;
		case 'End':
			target = items[last];
			break;
		default:
			return;
	}
	if (target === undefined) return;
	event.preventDefault();
	target.focus();
}
