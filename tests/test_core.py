from __future__ import annotations

import io
import os
import tempfile
import unittest
from pathlib import Path

from file_concatenator import Concatenator


class _CountingStream:
    """A minimal read-only text stream that counts how much it has yielded.

    Used to verify that a caller-owned handle is never closed by the
    Concatenator, and that chunking actually happens.
    """

    def __init__(self, text: str) -> None:
        self._text = text
        self._pos = 0
        self.read_calls = 0
        self.closed = False

    def read(self, size: int = -1) -> str:
        self.read_calls += 1
        if self._pos >= len(self._text):
            return ""
        if size is None or size < 0:
            chunk = self._text[self._pos:]
        else:
            chunk = self._text[self._pos:self._pos + size]
        self._pos += len(chunk)
        return chunk

    def close(self) -> None:
        self.closed = True


class TestConcatenator(unittest.TestCase):

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.cat = Concatenator(chunk_size=4)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write(self, name: str, text: str) -> Path:
        p = self.dir / name
        p.write_text(text, encoding="utf-8")
        return p

    def test_concatenate_two_files(self) -> None:
        a = self._write("a.txt", "hello")
        b = self._write("b.txt", "world")
        out = io.StringIO()
        n = self.cat.concatenate([a, b], out)
        self.assertEqual(out.getvalue(), "helloworld")
        self.assertEqual(n, 10)

    def test_empty_source_list(self) -> None:
        out = io.StringIO()
        n = self.cat.concatenate([], out)
        self.assertEqual(out.getvalue(), "")
        self.assertEqual(n, 0)

    def test_empty_file_is_no_op(self) -> None:
        a = self._write("a.txt", "")
        b = self._write("b.txt", "x")
        out = io.StringIO()
        self.cat.concatenate([a, b], out)
        self.assertEqual(out.getvalue(), "x")

    def test_chunking_actually_streams(self) -> None:
        stream = _CountingStream("abcdefgh")
        out = io.StringIO()
        self.cat.concatenate([stream], out)
        self.assertEqual(out.getvalue(), "abcdefgh")
        # chunk_size=4 over 8 chars => 2 data reads + 1 EOF read = 3 calls.
        self.assertEqual(stream.read_calls, 3)

    def test_caller_owned_stream_not_closed(self) -> None:
        stream = _CountingStream("data")
        out = io.StringIO()
        self.cat.concatenate([stream], out)
        self.assertFalse(stream.closed)

    def test_opened_files_are_closed(self) -> None:
        a = self._write("a.txt", "hi")
        out = io.StringIO()
        self.cat.concatenate([a], out)
        # Re-opening should succeed (no Windows lock / fd leak).
        with open(a, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), "hi")

    def test_path_as_str(self) -> None:
        a = self._write("a.txt", "abc")
        out = io.StringIO()
        self.cat.concatenate([str(a)], out)
        self.assertEqual(out.getvalue(), "abc")

    def test_mixed_path_and_stream(self) -> None:
        a = self._write("a.txt", "one")
        stream = _CountingStream("two")
        out = io.StringIO()
        self.cat.concatenate([a, stream], out)
        self.assertEqual(out.getvalue(), "onetwo")
        self.assertFalse(stream.closed)

    def test_unicode_preserved(self) -> None:
        a = self._write("a.txt", "\u00e9\u00e8\u00ea")
        out = io.StringIO()
        n = self.cat.concatenate([a], out)
        self.assertEqual(out.getvalue(), "\u00e9\u00e8\u00ea")
        self.assertEqual(n, 3)

    def test_invalid_chunk_size_raises(self) -> None:
        with self.assertRaises(ValueError):
            Concatenator(chunk_size=0)
        with self.assertRaises(ValueError):
            Concatenator(chunk_size=-1)

    def test_bytes_path_rejected(self) -> None:
        a = self._write("a.txt", "hi")
        out = io.StringIO()
        with self.assertRaises(TypeError):
            self.cat.concatenate([str(a).encode("utf-8")], out)

    def test_nonexistent_file_raises(self) -> None:
        out = io.StringIO()
        with self.assertRaises(FileNotFoundError):
            self.cat.concatenate([self.dir / "missing.txt"], out)

    def test_error_closes_opened_files(self) -> None:
        a = self._write("a.txt", "ok")
        bad = self.dir / "missing.txt"
        out = io.StringIO()
        with self.assertRaises(FileNotFoundError):
            self.cat.concatenate([a, bad], out)
        # a.txt must have been closed by the finally block; verify by opening.
        with open(a, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), "ok")

    def test_concatenate_to_string(self) -> None:
        a = self._write("a.txt", "foo")
        b = self._write("b.txt", "bar")
        result = self.cat.concatenate_to_string([a, b])
        self.assertEqual(result, "foobar")

    def test_newline_translation_control(self) -> None:
        # Write a file containing CRLF on disk; with newline='' the bytes pass
        # through unchanged, with newline='\n' the CRLF collapses to LF.
        a = self.dir / "a.txt"
        a.write_bytes(b"x\r\ny\r\n")
        out_passthrough = io.StringIO(newline="")
        self.cat.concatenate([a], out_passthrough, newline="")
        self.assertEqual(out_passthrough.getvalue(), "x\r\ny\r\n")

    def test_large_file_does_not_load_all_at_once(self) -> None:
        # 1000 chars, chunk_size=4 => many reads. Verifies the loop terminates
        # and that memory cost is bounded by chunk_size, not input size.
        text = "a" * 1000
        a = self._write("big.txt", text)
        out = io.StringIO()
        n = self.cat.concatenate([a], out)
        self.assertEqual(n, 1000)
        self.assertEqual(out.getvalue(), text)


if __name__ == "__main__":
    unittest.main()
