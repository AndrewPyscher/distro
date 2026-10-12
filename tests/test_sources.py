import hashlib
import io
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from distro_build.model import BuildError, Source
from distro_build.sources import extract, fetch


class SourceTests(unittest.TestCase):
    def example_source(self):
        return Source.parse({
            "name": "example", "url": "https://primary.example/source.tar.xz",
            "fallback_urls": ["https://fallback.example/source.tar.xz"],
            "sha256": hashlib.sha256(b"original source").hexdigest(),
        }, "test")

    def response(self, url, content=b"original source"):
        response = io.BytesIO(content)
        response.geturl = lambda: url
        return response

    def test_primary_success_does_not_contact_fallback(self):
        source = self.example_source()
        with tempfile.TemporaryDirectory() as temporary, patch(
            "distro_build.sources.urllib.request.urlopen",
            return_value=self.response(source.url),
        ) as download:
            result = fetch(source, Path(temporary))
            self.assertEqual(result.read_bytes(), b"original source")
            self.assertEqual(download.call_count, 1)
            self.assertEqual(download.call_args.args[0].full_url, source.url)

    def test_failed_download_tries_fallback_and_caches_verified_bytes(self):
        source = self.example_source()
        for error in (TimeoutError("read timed out"), URLError("server unavailable")):
            with self.subTest(error=error), tempfile.TemporaryDirectory() as temporary, patch(
                "distro_build.sources.urllib.request.urlopen",
                side_effect=[error, self.response(source.fallback_urls[0])],
            ) as download:
                cache = Path(temporary)
                result = fetch(source, cache)
                self.assertEqual(result.read_bytes(), b"original source")
                self.assertEqual([call.args[0].full_url for call in download.call_args_list],
                                 [source.url, *source.fallback_urls])
                self.assertEqual(list(cache.iterdir()), [result])
                self.assertEqual(fetch(source, cache, offline=True), result)
                self.assertEqual(download.call_count, 2)

    def test_partial_download_is_discarded_before_fallback(self):
        source = self.example_source()
        partial = self.response(source.url)
        with tempfile.TemporaryDirectory() as temporary, patch(
            "distro_build.sources.urllib.request.urlopen",
            side_effect=[partial, self.response(source.fallback_urls[0])],
        ), patch.object(partial, "read", side_effect=[b"partial", TimeoutError("read timed out")]):
            cache = Path(temporary)
            result = fetch(source, cache)
            self.assertEqual(result.read_bytes(), b"original source")
            self.assertEqual(list(cache.iterdir()), [result])

    def test_exhausted_urls_report_failures_and_leave_no_cache(self):
        source = self.example_source()
        with tempfile.TemporaryDirectory() as temporary, patch(
            "distro_build.sources.urllib.request.urlopen",
            side_effect=[TimeoutError("read timed out"), URLError("server unavailable")],
        ):
            cache = Path(temporary)
            with self.assertRaises(BuildError) as failure:
                fetch(source, cache)
            for detail in (source.url, source.fallback_urls[0], "read timed out", "server unavailable"):
                self.assertIn(detail, str(failure.exception))
            self.assertEqual(list(cache.iterdir()), [])

    def test_checksum_mismatch_and_insecure_redirect_stop_without_fallback(self):
        source = self.example_source()
        for url, content, message in (
            (source.url, b"tampered", "SHA256 mismatch"),
            ("http://example.org/source.tar.xz", b"original source", "non-HTTPS redirect"),
        ):
            with self.subTest(message=message), tempfile.TemporaryDirectory() as temporary, patch(
                "distro_build.sources.urllib.request.urlopen", return_value=self.response(url, content),
            ) as download:
                cache = Path(temporary)
                with self.assertRaisesRegex(BuildError, message):
                    fetch(source, cache)
                self.assertEqual(download.call_count, 1)
                self.assertEqual(list(cache.iterdir()), [])

    def test_missing_offline_source_does_not_contact_any_url(self):
        with tempfile.TemporaryDirectory() as temporary, patch(
            "distro_build.sources.urllib.request.urlopen",
        ) as download:
            with self.assertRaisesRegex(BuildError, "absent from offline cache"):
                fetch(self.example_source(), Path(temporary), offline=True)
            download.assert_not_called()

    def test_tampered_fallback_is_rejected(self):
        source = self.example_source()
        with tempfile.TemporaryDirectory() as temporary, patch(
            "distro_build.sources.urllib.request.urlopen",
            side_effect=[TimeoutError("read timed out"),
                         self.response(source.fallback_urls[0], b"tampered")],
        ):
            cache = Path(temporary)
            with self.assertRaisesRegex(BuildError, "SHA256 mismatch"):
                fetch(source, cache)
            self.assertEqual(list(cache.iterdir()), [])

    def test_fallback_urls_require_an_array_of_https_urls(self):
        for urls in ("https://example.org", ["http://example.org"], [123], None):
            with self.subTest(urls=urls), self.assertRaisesRegex(BuildError, "fallback_urls"):
                Source.parse({"name": "example", "url": "https://example.org/source",
                              "sha256": "a" * 64, "fallback_urls": urls}, "test")

    def test_tampered_offline_cache_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary)
            (cache / "source.tar.xz").write_bytes(b"modified upstream source")
            source = Source("example", "https://example.org/source.tar.xz", hashlib.sha256(b"original source").hexdigest(), "source.tar.xz")
            with self.assertRaisesRegex(BuildError, "checksum mismatch"):
                fetch(source, cache, offline=True)

    def test_traversal_and_escaping_symlinks_are_rejected(self):
        for kind in ("traversal", "symlink"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                archive = root / "source.tar"
                with tarfile.open(archive, "w") as stream:
                    entry = tarfile.TarInfo("../escaped" if kind == "traversal" else "source/escape")
                    if kind == "symlink":
                        entry.type = tarfile.SYMTYPE
                        entry.linkname = "../../escaped"
                        stream.addfile(entry)
                    else:
                        entry.size = 6
                        stream.addfile(entry, io.BytesIO(b"unsafe"))
                with self.assertRaises(BuildError):
                    extract(archive, root / "extract")
                self.assertFalse((root / "escaped").exists())

    def test_safe_source_tree_is_extracted(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "source.tar"
            with tarfile.open(archive, "w") as stream:
                entry = tarfile.TarInfo("source/hello.c")
                entry.size = 5
                stream.addfile(entry, io.BytesIO(b"hello"))
            source = extract(archive, root / "extract")
            self.assertEqual((source / "hello.c").read_bytes(), b"hello")


if __name__ == "__main__":
    unittest.main()
