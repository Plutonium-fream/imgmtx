"""Round-trip and invalid-input proof for the ImgMtx file format."""

import hashlib
import io
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock

from PIL import Image, PngImagePlugin

from imgmtx import core


def png(size=(7, 11), color=(20, 100, 200, 83), mode="RGBA"):
    image = Image.new(mode, size, color)
    if mode == "P":
        image.putpalette([value for i in range(256) for value in (i, 255 - i, i // 2)])
        image.info["transparency"] = 3
    data = io.BytesIO()
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("test-metadata", "Preserve this exactly.")
    image.save(data, format="PNG", pnginfo=metadata)
    return core.ImageInfo(data.getvalue(), *size)


class KeyTests(unittest.TestCase):
    def setUp(self):
        self.original = png()
        self.hidden = png(size=(13, 5), color=(177, 4, 89, 0))
        self.key = core.create_key(self.original, self.hidden)

    def rewrite_header(self, **updates):
        size = struct.unpack(">I", self.key[len(core.MAGIC):len(core.MAGIC) + 4])[0]
        start = len(core.MAGIC) + 4
        header = json.loads(self.key[start:start + size])
        header.update(updates)
        encoded = json.dumps(header).encode("ascii")
        return core.MAGIC + struct.pack(">I", len(encoded)) + encoded + self.key[start + size:]

    def test_exact_byte_roundtrip_different_dimensions_and_transparency(self):
        recovered = core.reveal_image(self.original, self.key)
        self.assertEqual(recovered, self.hidden)
        self.assertEqual(hashlib.sha256(recovered.data).digest(), hashlib.sha256(self.hidden.data).digest())

    def test_palette_roundtrip_preserves_metadata(self):
        hidden = png((19, 3), 3, "P")
        self.assertEqual(core.reveal_image(self.original, core.create_key(self.original, hidden)), hidden)

    def test_text_roundtrip(self):
        text = core.encode_text_key(self.key)
        self.assertTrue(text.startswith(core.TEXT_PREFIX))
        self.assertTrue(text.isascii())
        self.assertEqual(core.reveal_image(self.original, text), self.hidden)

    def test_key_generation_uses_fresh_salt(self):
        self.assertNotEqual(self.key, core.create_key(self.original, self.hidden))

    def test_same_key_and_original_produce_same_image(self):
        self.assertEqual(core.reveal_image(self.original, self.key), core.reveal_image(self.original, self.key))

    def test_wrong_original(self):
        with self.assertRaisesRegex(core.ImgMtxError, "does not match"):
            core.reveal_image(png(color=(0, 0, 0, 255)), self.key)

    def test_corrupt_payload(self):
        damaged = self.key[:-1] + bytes([self.key[-1] ^ 1])
        with self.assertRaisesRegex(core.ImgMtxError, "checksum"):
            core.reveal_image(self.original, damaged)

    def test_truncated_and_trailing_data(self):
        for damaged in (b"", b"IMGMTX", self.key[:10], self.key[:20], self.key[:-1], self.key + b"x"):
            with self.subTest(length=len(damaged)), self.assertRaises(core.ImgMtxError):
                core.reveal_image(self.original, damaged)

    def test_header_validation(self):
        changes = [
            {"version": 2}, {"version": True}, {"algorithm": "unknown"},
            {"width": -1}, {"width": True}, {"height": 0}, {"height": "5"},
            {"width": 25_000_001}, {"payload_length": -1},
            {"payload_length": True}, {"payload_length": core.MAX_IMAGE_BYTES + 1},
            {"salt": "no"}, {"source_sha256": []}, {"hidden_sha256": "f"},
            {"unexpected": "field"},
        ]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(core.ImgMtxError):
                core.reveal_image(self.original, self.rewrite_header(**change))

    def test_header_dimension_mismatch(self):
        with self.assertRaisesRegex(core.ImgMtxError, "dimensions"):
            core.reveal_image(self.original, self.rewrite_header(width=14))

    def test_header_invalid_json_or_size(self):
        for header in (b"[]", b"{}", b"null", b"{bad}", b"\xff", b'{"version":1,"version":1}'):
            key = core.MAGIC + struct.pack(">I", len(header)) + header
            with self.subTest(header=header), self.assertRaises(core.ImgMtxError):
                core.reveal_image(self.original, key)
        with self.assertRaises(core.ImgMtxError):
            core.reveal_image(self.original, core.MAGIC + struct.pack(">I", core.MAX_HEADER_BYTES + 1))

    def test_text_invalid_base64(self):
        with self.assertRaisesRegex(core.ImgMtxError, "Base64"):
            core.reveal_image(self.original, core.TEXT_PREFIX + b"bad%%")

    def test_oversize_key_rejected_before_decoding(self):
        with mock.patch.object(core, "MAX_KEY_BYTES", 32):
            with self.assertRaisesRegex(core.ImgMtxError, "too large"):
                core.reveal_image(self.original, self.key)

    def test_forged_image_info_rejected(self):
        with self.assertRaisesRegex(core.ImgMtxError, "dimensions"):
            core.create_key(core.ImageInfo(self.original.data, 9, 9), self.hidden)


class FileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix=".imgmtx-test-", dir=Path(__file__).resolve().parent)
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.original = self.folder / "original.png"
        self.hidden = self.folder / "hidden.png"
        self.original.write_bytes(png().data)
        self.hidden.write_bytes(png((4, 6)).data)

    def test_full_file_workflow_preserves_input_bytes(self):
        before = [path.read_bytes() for path in (self.original, self.hidden)]
        original = core.read_png(self.original)
        hidden = core.read_png(self.hidden)
        key_path = self.folder / "secret.imgkey"
        core.write_new_file(key_path, core.create_key(original, hidden), [self.original, self.hidden])
        recovered = core.reveal_image(core.read_png(self.original), core.read_key(key_path))
        output = self.folder / "revealed.png"
        core.write_new_file(output, recovered.data, [self.original, self.hidden, key_path])
        self.assertEqual(output.read_bytes(), before[1])
        self.assertEqual([path.read_bytes() for path in (self.original, self.hidden)], before)

    def test_protected_input_cannot_be_overwritten(self):
        before = self.original.read_bytes()
        with self.assertRaisesRegex(core.ImgMtxError, "Input files"):
            core.write_new_file(self.original, b"changed", [self.original])
        self.assertEqual(self.original.read_bytes(), before)

    def test_hardlinked_input_cannot_be_overwritten(self):
        alias = self.folder / "alias.png"
        try:
            os.link(self.original, alias)
        except OSError:
            self.skipTest("Hardlinks unavailable on this filesystem")
        with self.assertRaisesRegex(core.ImgMtxError, "Input files"):
            core.write_new_file(alias, b"changed", [self.original])

    def test_existing_unprotected_file_cannot_be_overwritten(self):
        output = self.folder / "existing.imgkey"
        output.write_bytes(b"original contents")
        with self.assertRaisesRegex(core.ImgMtxError, "already exists"):
            core.write_new_file(output, b"changed")
        self.assertEqual(output.read_bytes(), b"original contents")

    def test_samefile_guard_rejects_alias_before_write(self):
        # Exercise the guard even on sandboxes that forbid creating hardlinks.
        alias = self.folder / "alias.png"
        alias.write_bytes(b"unchanged")
        with mock.patch.object(core.os.path, "samefile", return_value=True):
            with self.assertRaisesRegex(core.ImgMtxError, "Input files"):
                core.write_new_file(alias, b"changed", [self.original])
        self.assertEqual(alias.read_bytes(), b"unchanged")

    def test_non_png_and_corrupt_png_rejected(self):
        for data in (b"not an image", self.original.read_bytes()[:-20]):
            path = self.folder / "damaged.png"
            path.write_bytes(data)
            with self.assertRaises(core.ImgMtxError):
                core.read_png(path)

    def test_file_size_limit_checked_before_read(self):
        with mock.patch.object(core, "MAX_IMAGE_BYTES", 20):
            with self.assertRaisesRegex(core.ImgMtxError, "too large"):
                core.read_png(self.original)

    def test_key_size_limit_checked_before_read(self):
        key_path = self.folder / "oversized.imgkey"
        key_path.write_bytes(b"x" * 50)
        with mock.patch.object(core, "MAX_KEY_BYTES", 20):
            with self.assertRaisesRegex(core.ImgMtxError, "too large"):
                core.read_key(key_path)

    def test_pixel_limit_checked_before_load(self):
        with mock.patch.object(core, "MAX_PIXELS", 10):
            with self.assertRaisesRegex(core.ImgMtxError, "pixel limit"):
                core.read_png(self.original)

    def test_missing_and_unwritable_paths(self):
        with self.assertRaisesRegex(core.ImgMtxError, "Could not read"):
            core.read_png(self.folder / "missing.png")
        with self.assertRaisesRegex(core.ImgMtxError, "Could not save"):
            core.write_new_file(self.folder / "missing" / "output.png", b"data")


if __name__ == "__main__":
    unittest.main()
