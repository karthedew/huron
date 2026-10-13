"""Bounded streaming adapters between HTTP and synchronous storage consumers."""

from collections.abc import Iterator

from asyncer import syncify
from fastapi import Request


def body_chunks(request: Request) -> Iterator[bytes]:
    """Pull the request body one chunk at a time, safe to iterate from a worker thread.

    Bridges FastAPI's async body stream to the synchronous ``Iterable[bytes]``
    the raw store's ``write_part`` consumes on its own worker thread: each
    call blocks on ``syncify``, hopping back to the event loop to pull the
    next chunk, so a part is never buffered beyond the one chunk in flight.
    Empty chunks are skipped; the stream ends when the body is exhausted,
    and a client disconnect propagates as ``ClientDisconnect``.

    Args:
        request: The request whose body is streamed.

    Yields:
        Each non-empty chunk of the request body, in order.
    """
    body = request.stream().__aiter__()

    async def _next_chunk() -> bytes:
        """Await the body's next chunk, so ``syncify`` sees a plain coroutine function.

        Returns:
            The next chunk from the request body.
        """
        return await body.__anext__()

    pull = syncify(_next_chunk)
    while True:
        try:
            chunk = pull()
        except StopAsyncIteration:
            return
        if chunk:
            yield chunk
