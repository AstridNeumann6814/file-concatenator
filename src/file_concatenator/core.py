from __future__ import annotations

import io
import os
from typing import IO, Iterable, Iterator, List, Optional, Union

__all__ = ["Concatenator"]

# A "file-like object" here means anything with a read(size: int) -> str method.
# We deliberately accept str paths as well as already-open objects. Path objects
# are intentionally converted via str() so that os.fspath() users get a clear
# TypeError if they pass bytes — keeping the public surface narrow prevents the
# "bytes-or-str-or-path" guessing games that bite test suites.
_PathLike = Union[str, "os.PathLike[str]"]
_Source = Union[_PathLike, IO[str]]


class Concatenator:
    """Stream multiple text files into one destination without buffering them all.

    Reads each source in small chunks and writes those chunks to the destination,
    so the peak memory cost is bounded by ``chunk_size`` regardless of how many
    files are concatenated or how large each one is.

    Only text mode is supported. Mixing encodings across sources is out of scope;
    if you need that, open each file yourself and pass the handles in. Binary
    concatenation is deliberately not offered because the common failure mode
    (silently producing corrupt output when a "binary" read meets a text write)
    is worse than a clear NotImplementedError at the boundary.
    """

    def __init__(self, chunk_size: int = 65536) -> None:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be a positive integer")
        self.chunk_size = chunk_size

    def _iter_chunks(self, stream: IO[str]) -> Iterator[str]:
        while True:
            chunk = stream.read(self.chunk_size)
            if not chunk:
                # Both '' (text EOF) and None (some non-conforming streams) end
                # the loop. Relying on falsiness keeps us robust to the latter
                # without a special-case branch.
                return
            yield chunk

    def concatenate(
        self,
        sources: Iterable[_Source],
        destination: IO[str],
        encoding: Optional[str] = None,
        errors: Optional[str] = None,
        newline: Optional[str] = None,
    ) -> int:
        """Concatenate ``sources`` into ``destination``; return bytes written.

        ``sources`` may contain filesystem paths (``str`` or ``os.PathLike``)
        and/or already-open text streams. Paths are opened with universal
        newline translation disabled when ``newline`` is ``None`` — the text is
        copied verbatim — but you can pass ``newline=''`` or ``'\n'`` to control
        it. Files opened by this method are always closed, even on error.

        ``destination`` is written to but never closed; the caller owns it.
        """
        total = 0
        # We track opened streams separately so a failure in source N closes
        # only the files we opened (not caller-owned handles) before re-raising.
        opened: List[IO[str]] = []
        try:
            for src in sources:
                stream, owned = self._open(src, encoding, errors, newline)
                if owned:
                    opened.append(stream)
                for chunk in self._iter_chunks(stream):
                    destination.write(chunk)
                    total += len(chunk)
        finally:
            # Close in reverse so nested resources (rare, but possible if a
            # caller wrapped one handle inside another) unwind cleanly.
            for stream in reversed(opened):
                stream.close()
        return total

    def _open(
        self,
        source: _Source,
        encoding: Optional[str],
        errors: Optional[str],
        newline: Optional[str],
    ) -> "tuple[IO[str], bool]":
        if hasattr(source, "read"):
            # Already-open stream. We don't own it, so never close it here.
            return source, False
        # os.fspath would also accept bytes; we reject that explicitly to keep
        # the contract text-only, which is the whole point of this class.
        path = os.fspath(source)
        if isinstance(path, (bytes, bytearray)):
            raise TypeError("path must be str or os.PathLike, not bytes")
        stream = open(path, "r", encoding=encoding, errors=errors, newline=newline)
        return stream, True

    def concatenate_to_string(
        self,
        sources: Iterable[_Source],
        encoding: Optional[str] = None,
        errors: Optional[str] = None,
        newline: Optional[str] = None,
    ) -> str:
        """Concatenate ``sources`` and return the result as a single string.

        This is a convenience wrapper around :meth:`concatenate` that writes to
        an in-memory buffer. It exists mainly for tests and small-file callers
        who do not want to manage their own ``StringIO``. Because it materializes
        the whole result, it defeats the streaming memory guarantee — use
        :meth:`concatenate` with a real destination for large inputs.
        """
        buf = io.StringIO()
        self.concatenate(sources, buf, encoding=encoding, errors=errors, newline=newline)
        return buf.getvalue()
