// Raw uploads transfer one bounded 64 MiB part per request.
process.env.BODY_SIZE_LIMIT ??= '67108864';

await import('../build/index.js');
