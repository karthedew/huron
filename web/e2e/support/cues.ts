/**
 * Checks of what a page draws, beyond its accessibility tree: that a current item stands out by
 * more than color, that labels and controls are drawn where people see them, and where a label
 * breaks into lines.
 */
import { expect, type Locator } from '@playwright/test';

/**
 * The current section's link stands out by more than its color, which grayscale and forced
 * colors take away: its label is heavier and it draws a bar, a border (forced colors keep
 * borders, not fills).
 */
export async function expectMarkedCurrent(current: Locator, other: Locator): Promise<void> {
	await expect(current).toHaveAttribute('aria-current');
	await expect(other).not.toHaveAttribute('aria-current');
	const [marked, plain] = await Promise.all([nonColorCues(current), nonColorCues(other)]);
	expect(marked.weight).toBeGreaterThan(plain.weight);
	expect(marked.bar).toBe(true);
	expect(plain.bar).toBe(false);
}

function nonColorCues(link: Locator): Promise<{ weight: number; bar: boolean }> {
	return link.evaluate((element) => {
		const drawsBar = (node: Element) => {
			const style = getComputedStyle(node);
			return ['top', 'right', 'bottom', 'left'].some(
				(side) =>
					style.getPropertyValue(`border-${side}-style`) !== 'none' &&
					parseFloat(style.getPropertyValue(`border-${side}-width`)) >= 2
			);
		};
		return {
			weight: Number(getComputedStyle(element).fontWeight),
			bar: [element, ...element.querySelectorAll('*')].some(drawsBar)
		};
	});
}

/** Whether a link draws its label inside its own box, where everyone sees it. */
export function drawsLabelInside(link: Locator): Promise<boolean> {
	return link.evaluate((element) => {
		const box = element.getBoundingClientRect();
		const texts = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
		const range = document.createRange();
		let label: DOMRect | null = null;
		for (let node = texts.nextNode(); node !== null; node = texts.nextNode()) {
			if (node.textContent?.trim()) {
				range.selectNodeContents(node);
				label = range.getBoundingClientRect();
			}
		}
		return (
			label !== null &&
			label.width > 0 &&
			label.left >= box.left &&
			label.right <= box.right &&
			label.top >= box.top &&
			label.bottom <= box.bottom
		);
	});
}

/** The text an element draws on each of its lines, top to bottom. */
export function drawnLines(locator: Locator): Promise<string[]> {
	return locator.evaluate((element) => {
		const lines: { top: number; text: string }[] = [];
		const texts = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
		const range = document.createRange();
		for (let node = texts.nextNode(); node !== null; node = texts.nextNode()) {
			if (!(node instanceof Text)) continue;
			for (let offset = 0; offset < node.data.length; offset += 1) {
				range.setStart(node, offset);
				range.setEnd(node, offset + 1);
				const { top, height } = range.getBoundingClientRect();
				if (height === 0) continue;
				const line = lines.find((drawn) => Math.abs(drawn.top - top) < 2);
				if (line === undefined) lines.push({ top, text: node.data[offset] });
				else line.text += node.data[offset];
			}
		}
		return lines.sort((a, b) => a.top - b.top).map(({ text }) => text);
	});
}

/**
 * Whether every character an element draws lies inside its border, rounded corners included: a
 * box rounded by half its height draws an ellipse round several lines, which crosses their ends.
 */
export function drawnInsideBorder(locator: Locator): Promise<boolean> {
	return locator.evaluate((element) => {
		const box = element.getBoundingClientRect();
		const style = getComputedStyle(element);
		const border = parseFloat(style.borderTopWidth);
		// Corners are drawn no rounder than half the box's shorter side.
		const outer = Math.min(parseFloat(style.borderTopLeftRadius), box.width / 2, box.height / 2);
		const radius = Math.max(0, outer - border);
		const inner = {
			left: box.left + border,
			top: box.top + border,
			right: box.right - border,
			bottom: box.bottom - border
		};
		// Inside a rounded box: within its radius of the box that the corners' centres span.
		const inside = (x: number, y: number) => {
			const nearestX = Math.min(Math.max(x, inner.left + radius), inner.right - radius);
			const nearestY = Math.min(Math.max(y, inner.top + radius), inner.bottom - radius);
			return Math.hypot(x - nearestX, y - nearestY) <= radius + 0.5;
		};
		const texts = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
		const range = document.createRange();
		for (let node = texts.nextNode(); node !== null; node = texts.nextNode()) {
			if (!(node instanceof Text)) continue;
			for (let offset = 0; offset < node.data.length; offset += 1) {
				range.setStart(node, offset);
				range.setEnd(node, offset + 1);
				const { left, top, right, bottom, width } = range.getBoundingClientRect();
				// A space that ends a line may hang past it, drawing nothing.
				if (width === 0 || /\s/u.test(node.data[offset])) continue;
				const corners: Array<[number, number]> = [
					[left, top],
					[right, top],
					[left, bottom],
					[right, bottom]
				];
				if (!corners.every(([x, y]) => inside(x, y))) return false;
			}
		}
		return true;
	});
}

/** Whether nothing is drawn over the element, at its middle and along its bottom edge. */
export function drawnOnTop(locator: Locator): Promise<boolean> {
	return locator.evaluate((element) => {
		const box = element.getBoundingClientRect();
		const x = box.left + box.width / 2;
		return [box.top + box.height / 2, box.bottom - 1].every((y) => {
			const hit = document.elementFromPoint(x, y);
			return hit !== null && element.contains(hit);
		});
	});
}
