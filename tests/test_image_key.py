"""Prove that ordinary PNG pixels can carry a complete ImgMtx key."""

import hashlib
import io
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock

from PIL import Image, PngImagePlugin

from imgmtx import core


def png(size=(11, 7), color=(40, 50, 100, 120)):
    output = io.BytesIO()
    image = Image.new("RGBA", size, color)
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("description", "Keep hidden bytes and metadata exactly.")
    image.save(output, format="PNG", pnginfo=metadata)
    return core.ImageInfo(output.getvalue(), *size)


class ImageKeyTests(unittest.TestCase):
    def setUp(self):
        self.original = png()
        self.hidden = png((17, 13), (200, 100, 30, 0))
        self.binary = core.create_key(self.original, self.hidden)
        self.key_png = core.encode_png_key(self.binary)

    def mutate_pixels(self, mutation):
        with Image.open(io.BytesIO(self.key_png)) as image:
            size = image.size
            raw = bytearray(image.tobytes())
        mutation(raw)
        output = io.BytesIO()
        Image.frombytes("RGB", size, bytes(raw)).save(output, format="PNG")
        return output.getvalue()

    def test_normal_rgb_png_recovers_exact_hidden_file(self):
        self.assertTrue(self.key_png.startswith(core.PNG_SIGNATURE))
        with Image.open(io.BytesIO(self.key_png)) as key:
            self.assertEqual(key.format, "PNG")
            self.assertEqual(key.mode, "RGB")
            self.assertFalse(key.is_animated)
            self.assertLessEqual(abs(key.width - key.height), 1)
            self.assertLessEqual(key.width * key.height, core.MAX_PIXELS)
            key.load()
        self.assertEqual(core.reveal_image(self.original, self.key_png), self.hidden)
        self.assertEqual(core.reveal_image(self.original, self.key_png).data, self.hidden.data)

    def test_lossless_resave_with_changed_metadata_and_compression(self):
        output = io.BytesIO()
        metadata = PngImagePlugin.PngInfo()
        metadata.add_text("note", "Metadata and PNG compression are not part of the key pixels.")
        with Image.open(io.BytesIO(self.key_png)) as image:
            image.save(output, format="PNG", compress_level=9, pnginfo=metadata)
        self.assertNotEqual(output.getvalue(), self.key_png)
        self.assertEqual(core.reveal_image(self.original, output.getvalue()), self.hidden)

    def test_lossless_opaque_rgba_conversion(self):
        output = io.BytesIO()
        with Image.open(io.BytesIO(self.key_png)) as image:
            image.convert("RGBA").save(output, format="PNG")
        self.assertEqual(core.reveal_image(self.original, output.getvalue()), self.hidden)

    def test_changed_alpha_rejected(self):
        output = io.BytesIO()
        with Image.open(io.BytesIO(self.key_png)) as image:
            rgba = image.convert("RGBA")
            rgba.putpixel((0, 0), (*rgba.getpixel((0, 0))[:3], 254))
            rgba.save(output, format="PNG")
        with self.assertRaisesRegex(core.ImgMtxError, "opaque"):
            core.reveal_image(self.original, output.getvalue())

    def test_png_can_encode_an_existing_text_or_image_key(self):
        for source in (core.encode_text_key(self.binary), self.key_png):
            with self.subTest(format=source[:16]):
                self.assertEqual(core.reveal_image(self.original, core.encode_png_key(source)), self.hidden)

    def test_existing_binary_and_text_formats_remain_compatible(self):
        for key in (self.binary, core.encode_text_key(self.binary), core.encode_text_key(self.key_png)):
            with self.subTest(format=key[:16]):
                self.assertEqual(core.reveal_image(self.original, key), self.hidden)

    def test_wrong_original_rejected(self):
        with self.assertRaisesRegex(core.ImgMtxError, "does not match"):
            core.reveal_image(png(color=(2, 3, 4, 255)), self.key_png)

    def test_changed_binary_header_payload_and_envelope_checksum_rejected(self):
        positions = [core.PNG_KEY_HEADER_BYTES, core.PNG_KEY_HEADER_BYTES + len(self.binary) - 1,
                     core.PNG_KEY_PREFIX_BYTES]
        for position in positions:
            with self.subTest(byte=position):
                altered = self.mutate_pixels(lambda raw: raw.__setitem__(position, raw[position] ^ 1))
                with self.assertRaisesRegex(core.ImgMtxError, "checksum"):
                    core.reveal_image(self.original, altered)

    def test_changed_length_and_version_rejected(self):
        for position in (len(core.PNG_KEY_MAGIC), core.PNG_KEY_PREFIX_BYTES - 1):
            with self.subTest(byte=position):
                altered = self.mutate_pixels(lambda raw: raw.__setitem__(position, raw[position] ^ 1))
                with self.assertRaises(core.ImgMtxError):
                    core.reveal_image(self.original, altered)

    def test_changed_padding_rejected(self):
        with Image.open(io.BytesIO(self.key_png)) as image:
            self.assertGreater(len(image.tobytes()), core.PNG_KEY_HEADER_BYTES + len(self.binary))
        altered = self.mutate_pixels(lambda raw: raw.__setitem__(-1, 1))
        with self.assertRaisesRegex(core.ImgMtxError, "padding"):
            core.reveal_image(self.original, altered)

    def test_resizing_and_jpeg_conversion_rejected(self):
        with Image.open(io.BytesIO(self.key_png)) as image:
            resized = io.BytesIO()
            image.resize((image.width + 1, image.height + 1)).save(resized, format="PNG")
            jpeg = io.BytesIO()
            image.save(jpeg, format="JPEG", quality=100, subsampling=0)
        for data in (resized.getvalue(), jpeg.getvalue()):
            with self.subTest(signature=data[:8]), self.assertRaises(core.ImgMtxError):
                core.reveal_image(self.original, data)

    def test_unrelated_tiny_palette_and_truncated_png_rejected(self):
        with Image.open(io.BytesIO(self.key_png)) as image:
            unrelated = io.BytesIO()
            Image.new("RGB", image.size, "white").save(unrelated, format="PNG")
            palette = io.BytesIO()
            image.convert("P").save(palette, format="PNG")
        tiny = io.BytesIO()
        Image.new("RGB", (1, 1)).save(tiny, format="PNG")
        for data in (unrelated.getvalue(), tiny.getvalue(), palette.getvalue(), self.key_png[:-20]):
            with self.subTest(length=len(data)), self.assertRaises(core.ImgMtxError):
                core.reveal_image(self.original, data)

    def test_animated_png_key_rejected(self):
        output = io.BytesIO()
        with Image.open(io.BytesIO(self.key_png)) as image:
            second = image.copy()
            second.putpixel((0, 0), (0, 0, 0))
            image.save(output, format="PNG", save_all=True, append_images=[second], duration=100)
        with self.assertRaisesRegex(core.ImgMtxError, "RGB or opaque RGBA"):
            core.reveal_image(self.original, output.getvalue())

    def test_dimension_limit_checked_before_decoding_pixel_stream(self):
        with Image.open(io.BytesIO(self.key_png)) as image:
            too_small = image.width * image.height - 1
        with mock.patch.object(core, "MAX_PIXELS", too_small):
            # Directly exercise carrier decoding so original-image validation
            # cannot load pixels before this guard is reached.
            with mock.patch("PIL.PngImagePlugin.PngImageFile.load", side_effect=AssertionError("Loaded pixels before limit")):
                with self.assertRaisesRegex(core.ImgMtxError, "dimensions"):
                    core._decode_key(self.key_png)

    def test_binary_length_boundary_and_oversized_envelope(self):
        with mock.patch.object(core, "MAX_BINARY_KEY_BYTES", len(self.binary)):
            self.assertEqual(core.reveal_image(self.original, core.encode_png_key(self.binary)), self.hidden)
        bad_length = len(self.binary) + 1
        altered = self.mutate_pixels(lambda raw: raw.__setitem__(
            slice(len(core.PNG_KEY_MAGIC) + 1, core.PNG_KEY_PREFIX_BYTES), struct.pack(">Q", bad_length)))
        with mock.patch.object(core, "MAX_BINARY_KEY_BYTES", len(self.binary)):
            with self.assertRaisesRegex(core.ImgMtxError, "length"):
                core.reveal_image(self.original, altered)

    def test_maximum_binary_key_fits_within_pixel_limit(self):
        # Check the actual 64 MiB boundary arithmetically, without allocating
        # that large carrier in every test run. The reduced boundary above
        # exercises the same encoding and decoding paths with real files.
        width, height = core._key_image_size(core.MAX_BINARY_KEY_BYTES)
        required_bytes = core.PNG_KEY_HEADER_BYTES + core.MAX_BINARY_KEY_BYTES
        self.assertLessEqual(width * height, core.MAX_PIXELS)
        self.assertGreaterEqual(width * height * 3, required_bytes)
        self.assertLess(width * height * 3 - required_bytes, width * 3)
        self.assertLessEqual(abs(width - height), 1)

    def test_image_key_uses_key_file_limit_not_ordinary_png_byte_limit(self):
        self.assertGreater(len(self.key_png), max(len(self.original.data), len(self.hidden.data)))
        with mock.patch.object(core, "MAX_IMAGE_BYTES", len(self.key_png) - 1):
            self.assertEqual(core.reveal_image(self.original, self.key_png), self.hidden)

    def test_nested_carriers_rejected(self):
        def put_nested(raw):
            start = core.PNG_KEY_HEADER_BYTES
            inner = core.TEXT_PREFIX + b"A" * (len(self.binary) - len(core.TEXT_PREFIX))
            raw[start:start + len(inner)] = inner
            checksum = hashlib.sha256(raw[:core.PNG_KEY_PREFIX_BYTES])
            checksum.update(inner)
            raw[core.PNG_KEY_PREFIX_BYTES:core.PNG_KEY_HEADER_BYTES] = checksum.digest()
        with self.assertRaisesRegex(core.ImgMtxError, "Nested"):
            core.reveal_image(self.original, self.mutate_pixels(put_nested))

    def test_file_workflow_preserves_original_and_hidden(self):
        with tempfile.TemporaryDirectory(prefix=".imgmtx-image-key-", dir=Path(__file__).resolve().parent) as directory:
            folder = Path(directory)
            original = folder / "original.png"
            hidden = folder / "hidden.png"
            carrier = folder / "key.png"
            original.write_bytes(self.original.data)
            hidden.write_bytes(self.hidden.data)
            core.write_new_file(carrier, self.key_png, [original, hidden])
            recovered = core.reveal_image(core.read_png(original), core.read_key(carrier))
            self.assertEqual(recovered.data, self.hidden.data)
            self.assertEqual(original.read_bytes(), self.original.data)
            self.assertEqual(hidden.read_bytes(), self.hidden.data)
            with self.assertRaisesRegex(core.ImgMtxError, "cannot be overwritten"):
                core.write_new_file(original, self.key_png, [original, hidden])


if __name__ == "__main__":
    unittest.main()
