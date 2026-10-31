import type { ParamMatcher } from '@sveltejs/kit';

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** A canonical hex UUID in lowercase or uppercase. */
export const match = ((param: string): boolean => UUID.test(param)) satisfies ParamMatcher;
