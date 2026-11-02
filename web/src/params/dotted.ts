import type { ParamMatcher } from '@sveltejs/kit';
import { match as isSegment } from './segment';

/** The API's identifier limit; segments are ASCII, so characters are bytes. */
const MAX_LENGTH = 255;

/** A dotted namespace path or identifier: segments joined by `.`. */
export const match = ((param: string): boolean =>
	param.length <= MAX_LENGTH && param.split('.').every(isSegment)) satisfies ParamMatcher;
