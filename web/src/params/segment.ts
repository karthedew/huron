import type { ParamMatcher } from '@sveltejs/kit';

const SEGMENT = /^[a-z0-9][a-z0-9_-]{0,62}$/;

/** An organization, catalog or namespace name: the API's segment rule. */
export const match = ((param: string): boolean => SEGMENT.test(param)) satisfies ParamMatcher;
