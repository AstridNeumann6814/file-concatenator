# file_concatenator

Concatenates multiple text files into one output stream without reading any
single file fully into memory.

```python
import io
from file_concatenator import Concatenator

# Create example inputs first.
open("a.txt", "w").write("hello ")
open("b.txt", "w").write("world")
open("c.txt", "w").write("!")

cat = Concatenator(chunk_size=65536)
out = io.StringIO()
n = cat.concatenate(["a.txt", "b.txt", "c.txt"], out)
print(out.getvalue())  # -> "hello world!"
```

`Concatenator.concatenate(sources, destination, encoding=None, errors=None, newline=None)`
returns the number of characters written. Sources may be `str` / `os.PathLike`
paths or already-open text streams (anything with a `read(size)` method). The
destination is written to but never closed; files opened internally are always
closed, including on error.

`Concatenator.concatenate_to_string(sources, ...)` is a convenience wrapper
that materializes the whole result in a `StringIO` — handy for tests and small
inputs, but it does not preserve the streaming memory guarantee.

## Why

The obvious way to join files — `"".join(open(p).read() for p in paths)` —
loads every file into memory at once and blows up on large inputs or many
sources. This library reads each source in fixed-size chunks and writes them
straight through, so peak memory is bounded by `chunk_size` regardless of
input size.

Only text mode is supported. Binary concatenation is deliberately omitted: the
silent corruption you get when a binary read is forced through a text write is
worse than a clear `NotImplementedError` at the boundary. If you need binary
concatenation, `shutil.copyfileobj` already does it well.

## Edge you will hit

Path arguments must be `str` or `os.PathLike`; `bytes` paths raise `TypeError`.
If you pass an already-open stream, it is used as-is and never closed — the
caller owns it. Universal-newline translation is disabled by default
(`newline=None` means verbatim copy); pass `newline=''` or `newline='\n'` if you
need translation.
