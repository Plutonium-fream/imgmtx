"""The bounded, lossless ImgMtx key format and file operations.

An ImgMtx key contains a hidden PNG XORed with a stream derived from the
original PNG and a random salt. It is a transformation file, not a password:
anyone who has both the original and the key can recover the hidden image.
Checksums detect accidental corruption; they are not signatures.
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import secrets
import struct
from typing import Iterable
import warnings

from PIL import Image, UnidentifiedImageError


MAX_IMAGE_BYTES = 64 * 1024 * 1024
MAX_PIXELS = 25_000_000
MAX_HEADER_BYTES = 4096
MAGIC = b"IMGMTX\r\n"
TEXT_PREFIX = b"IMGMTX-TEXT-1\n"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PNG_KEY_MAGIC = b"IMGMTX-PIXELS\x00"
PNG_KEY_VERSION = 1
PNG_KEY_PREFIX_BYTES = len(PNG_KEY_MAGIC) + 1 + 8
PNG_KEY_HEADER_BYTES = PNG_KEY_PREFIX_BYTES + 32
DOMAIN = b"ImgMtx image transformation v1\x00"
MAX_BINARY_KEY_BYTES = len(MAGIC) + 4 + MAX_HEADER_BYTES + MAX_IMAGE_BYTES
MAX_KEY_BYTES = len(TEXT_PREFIX) + ((MAX_BINARY_KEY_BYTES + 2) // 3) * 4 + 1
_HEX_256 = re.compile(r"[0-9a-f]{64}\Z")
_HEADER_FIELDS = {
    "version", "algorithm", "source_sha256", "hidden_sha256", "salt",
    "width", "height", "payload_length",
}


class ImgMtxError(ValueError):
    """A file cannot be used safely by ImgMtx."""


@dataclass(frozen=True)
class ImageInfo:
    data: bytes
    width: int
    height: int


def _read_bounded(path: str | os.PathLike[str], limit: int, label: str) -> bytes:
    size_error = f"{label} is too large."
    if label == "PNG":
        size_error += " The image limit is 64 MiB."
    try:
        with open(path, "rb") as stream:
            if os.fstat(stream.fileno()).st_size > limit:
                raise ImgMtxError(size_error)
            data = stream.read(limit + 1)
    except OSError as exc:
        raise ImgMtxError(f"Could not read {label.lower()}: {exc.strerror or exc}") from exc
    if len(data) > limit:
        raise ImgMtxError(size_error)
    return data


def _parse_png(data: bytes) -> ImageInfo:
    if not isinstance(data, bytes) or not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ImgMtxError("Choose a valid PNG image.")
    if len(data) > MAX_IMAGE_BYTES:
        raise ImgMtxError("PNG is too large. The image limit is 64 MiB.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                width, height = image.size
                if image.format != "PNG":
                    raise ImgMtxError("Choose a valid PNG image.")
                if width <= 0 or height <= 0 or width * height > MAX_PIXELS:
                    raise ImgMtxError("PNG exceeds the 25 million pixel limit.")
                image.verify()
            # verify() checks the container; load() also checks the pixel stream.
            with Image.open(io.BytesIO(data)) as image:
                image.load()
    except ImgMtxError:
        raise
    except (OSError, SyntaxError, ValueError, UnidentifiedImageError,
            Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ImgMtxError("PNG is damaged or unsupported. Choose a valid PNG image.") from exc
    return ImageInfo(data, width, height)


def read_png(path: str | os.PathLike[str]) -> ImageInfo:
    """Read and validate a PNG without modifying or re-encoding its bytes."""
    return _parse_png(_read_bounded(path, MAX_IMAGE_BYTES, "PNG"))


def read_key(path: str | os.PathLike[str]) -> bytes:
    """Read a binary, encoded text, or PNG key, with a bound before allocation."""
    return _read_bounded(path, MAX_KEY_BYTES, "Key file")


def _validated_info(image: ImageInfo) -> ImageInfo:
    if not isinstance(image, ImageInfo):
        raise ImgMtxError("Select a PNG image first.")
    actual = _parse_png(image.data)
    if (type(image.width) is not int or type(image.height) is not int
            or (actual.width, actual.height) != (image.width, image.height)):
        raise ImgMtxError("Image dimensions do not match its PNG data.")
    return actual


def _xor_bytes(left: bytes, right: bytes) -> bytes:
    # Large integer chunks avoid a slow Python loop for every pixel byte.
    result = bytearray(len(left))
    for start in range(0, len(left), 65536):
        stop = min(start + 65536, len(left))
        chunk = int.from_bytes(left[start:stop], "little") ^ int.from_bytes(right[start:stop], "little")
        result[start:stop] = chunk.to_bytes(stop - start, "little")
    return bytes(result)


def _stream(original_data: bytes, salt: bytes, length: int) -> bytes:
    return hashlib.shake_256(DOMAIN + original_data + salt).digest(length)


def create_key(original: ImageInfo, hidden: ImageInfo) -> bytes:
    """Create a binary key that recovers the hidden PNG's exact file bytes."""
    _validated_info(original)
    _validated_info(hidden)
    salt = secrets.token_bytes(32)
    header = {
        "version": 1,
        "algorithm": "shake256-xor",
        "source_sha256": hashlib.sha256(original.data).hexdigest(),
        "hidden_sha256": hashlib.sha256(hidden.data).hexdigest(),
        "salt": salt.hex(),
        "width": hidden.width,
        "height": hidden.height,
        "payload_length": len(hidden.data),
    }
    encoded_header = json.dumps(header, separators=(",", ":"), sort_keys=True).encode("ascii")
    payload = _xor_bytes(hidden.data, _stream(original.data, salt, len(hidden.data)))
    return MAGIC + struct.pack(">I", len(encoded_header)) + encoded_header + payload


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ImgMtxError("Key header contains duplicate fields.")
        result[key] = value
    return result


def _decode_key(data: bytes) -> bytes:
    if not isinstance(data, bytes) or len(data) > MAX_KEY_BYTES:
        raise ImgMtxError("Key file is invalid or too large.")
    if data.startswith(PNG_SIGNATURE):
        data = _decode_png_key(data)
    elif data.startswith(TEXT_PREFIX):
        encoded = data[len(TEXT_PREFIX):]
        if encoded.endswith(b"\n"):
            encoded = encoded[:-1]
        try:
            data = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ImgMtxError("Text key is damaged: invalid Base64 data.") from exc
    if data.startswith((PNG_SIGNATURE, TEXT_PREFIX)):
        raise ImgMtxError("Nested key formats are not supported.")
    if len(data) > MAX_BINARY_KEY_BYTES:
        raise ImgMtxError("Key file is too large.")
    return data


def _key_image_size(binary_length: int) -> tuple[int, int]:
    """Return a near-square RGB carrier with space for its envelope and key."""
    pixels = (PNG_KEY_HEADER_BYTES + binary_length + 2) // 3
    width = math.isqrt(pixels)
    if width * width < pixels:
        width += 1
    return width, (pixels + width - 1) // width


def _decode_png_key(data: bytes) -> bytes:
    """Extract an RGB pixel envelope, independent of PNG metadata/compression."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                width, height = image.size
                maximum_width, maximum_height = _key_image_size(MAX_BINARY_KEY_BYTES)
                if (image.format != "PNG" or image.mode not in ("RGB", "RGBA")
                        or getattr(image, "is_animated", False)):
                    raise ImgMtxError("Choose an ImgMtx PNG key with RGB or opaque RGBA pixels.")
                if (width <= 0 or height <= 0 or width * height > MAX_PIXELS
                        or width * height > maximum_width * maximum_height
                        or width not in (height, height + 1)):
                    raise ImgMtxError("PNG key is damaged: invalid image dimensions.")
                if width * height * 3 < PNG_KEY_HEADER_BYTES:
                    raise ImgMtxError("This PNG does not contain an ImgMtx key.")
                image.verify()
            # Key carriers have their own byte limit: a full-size key PNG can
            # exceed the ordinary image-file limit due to its container bytes.
            with Image.open(io.BytesIO(data)) as image:
                image.load()
                if image.mode == "RGBA":
                    if image.getextrema()[3] != (255, 255):
                        raise ImgMtxError("PNG key is damaged: its pixels must remain opaque.")
                    pixels = image.convert("RGB")
                else:
                    pixels = image
                # Read only enough rows for the envelope before allocating a
                # second byte buffer for the entire decoded carrier.
                header_rows = (PNG_KEY_HEADER_BYTES + width * 3 - 1) // (width * 3)
                header = pixels.crop((0, 0, width, header_rows)).tobytes()[:PNG_KEY_HEADER_BYTES]
                if not header.startswith(PNG_KEY_MAGIC):
                    raise ImgMtxError("This PNG does not contain an ImgMtx key.")
                if header[len(PNG_KEY_MAGIC)] != PNG_KEY_VERSION:
                    raise ImgMtxError("This PNG key uses an unsupported ImgMtx version.")
                length = struct.unpack(">Q", header[len(PNG_KEY_MAGIC) + 1:PNG_KEY_PREFIX_BYTES])[0]
                if not 1 <= length <= MAX_BINARY_KEY_BYTES:
                    raise ImgMtxError("PNG key is damaged: invalid key length.")
                if (width, height) != _key_image_size(length):
                    raise ImgMtxError("PNG key is damaged: dimensions do not match its key length.")
                raw = pixels.tobytes()
    except ImgMtxError:
        raise
    except (OSError, SyntaxError, ValueError, UnidentifiedImageError,
            Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ImgMtxError("PNG key is damaged or unsupported. Choose the unchanged key PNG.") from exc
    end = PNG_KEY_HEADER_BYTES + length
    binary = raw[PNG_KEY_HEADER_BYTES:end]
    expected = header[PNG_KEY_PREFIX_BYTES:PNG_KEY_HEADER_BYTES]
    checksum = hashlib.sha256(header[:PNG_KEY_PREFIX_BYTES])
    checksum.update(binary)
    if not secrets.compare_digest(checksum.digest(), expected):
        raise ImgMtxError("PNG key is damaged: its pixel checksum does not match.")
    if any(raw[end:]):
        raise ImgMtxError("PNG key is damaged: its padding pixels were changed.")
    return binary


def _parse_key(data: bytes) -> tuple[dict, bytes]:
    data = _decode_key(data)
    prefix_size = len(MAGIC) + 4
    if len(data) < prefix_size or not data.startswith(MAGIC):
        raise ImgMtxError("This is not a supported ImgMtx key file.")
    header_size = struct.unpack(">I", data[len(MAGIC):prefix_size])[0]
    if not 1 <= header_size <= MAX_HEADER_BYTES or len(data) < prefix_size + header_size:
        raise ImgMtxError("Key file is damaged: invalid or truncated header.")
    try:
        header = json.loads(data[prefix_size:prefix_size + header_size].decode("ascii"),
                            object_pairs_hook=_unique_object)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise ImgMtxError("Key file is damaged: invalid header.") from exc
    if type(header) is not dict or set(header) != _HEADER_FIELDS:
        raise ImgMtxError("Key file is damaged: missing or unexpected header fields.")
    if type(header["version"]) is not int or header["version"] != 1:
        raise ImgMtxError("This key uses an unsupported ImgMtx version.")
    if header["algorithm"] != "shake256-xor":
        raise ImgMtxError("This key uses an unsupported transformation.")
    for field in ("source_sha256", "hidden_sha256", "salt"):
        if type(header[field]) is not str or not _HEX_256.fullmatch(header[field]):
            raise ImgMtxError("Key file is damaged: invalid fingerprint or salt.")
    width, height, length = (header[field] for field in ("width", "height", "payload_length"))
    if (type(width) is not int or type(height) is not int
            or width <= 0 or height <= 0 or width * height > MAX_PIXELS):
        raise ImgMtxError("Key file is damaged: invalid image dimensions.")
    if type(length) is not int or not 1 <= length <= MAX_IMAGE_BYTES:
        raise ImgMtxError("Key file is damaged: invalid image length.")
    payload = data[prefix_size + header_size:]
    if len(payload) != length:
        raise ImgMtxError("Key file is damaged: image data is truncated or has extra bytes.")
    return header, payload


def encode_text_key(binary: bytes) -> bytes:
    """Encode a validated binary key as an ASCII text file."""
    decoded = _decode_key(binary)
    _parse_key(decoded)
    return TEXT_PREFIX + base64.b64encode(decoded) + b"\n"


def encode_png_key(binary: bytes) -> bytes:
    """Store a validated key in the RGB pixels of a normal, opaque PNG."""
    decoded = _decode_key(binary)
    _parse_key(decoded)
    width, height = _key_image_size(len(decoded))
    if width * height > MAX_PIXELS:
        raise ImgMtxError("PNG key exceeds the 25 million pixel limit.")
    prefix = PNG_KEY_MAGIC + bytes([PNG_KEY_VERSION]) + struct.pack(">Q", len(decoded))
    checksum = hashlib.sha256(prefix)
    checksum.update(decoded)
    raw = prefix + checksum.digest() + decoded
    raw += b"\x00" * (width * height * 3 - len(raw))
    output = io.BytesIO()
    with Image.frombytes("RGB", (width, height), raw) as image:
        image.save(output, format="PNG", compress_level=1)
    encoded = output.getvalue()
    if len(encoded) > MAX_KEY_BYTES:
        raise ImgMtxError("PNG key file is too large.")
    return encoded


def reveal_image(original: ImageInfo, key_data: bytes) -> ImageInfo:
    """Recover the exact hidden PNG, rejecting mismatches and corruption."""
    _validated_info(original)
    header, payload = _parse_key(key_data)
    if not secrets.compare_digest(hashlib.sha256(original.data).hexdigest(), header["source_sha256"]):
        raise ImgMtxError("Original image does not match this key. Select the exact original PNG file.")
    recovered = _xor_bytes(payload, _stream(original.data, bytes.fromhex(header["salt"]), len(payload)))
    if not secrets.compare_digest(hashlib.sha256(recovered).hexdigest(), header["hidden_sha256"]):
        raise ImgMtxError("Key file is damaged: the hidden image checksum does not match.")
    image = _parse_png(recovered)
    if (image.width, image.height) != (header["width"], header["height"]):
        raise ImgMtxError("Key file is damaged: hidden image dimensions do not match.")
    return image


def write_new_file(path: str | os.PathLike[str], data: bytes,
                   protected_paths: Iterable[str | os.PathLike[str]] = ()) -> None:
    """Write a new file exclusively; existing files and input images are safe."""
    destination = Path(path)
    for protected in protected_paths:
        source = Path(protected)
        if destination.resolve() == source.resolve():
            raise ImgMtxError("Choose a new filename. Input files cannot be overwritten.")
        try:
            if destination.exists() and source.exists() and os.path.samefile(destination, source):
                raise ImgMtxError("Choose a new filename. Input files cannot be overwritten.")
        except OSError as exc:
            raise ImgMtxError(f"Could not verify the output path: {exc}") from exc
    try:
        with open(destination, "xb") as stream:
            stream.write(data)
    except FileExistsError as exc:
        raise ImgMtxError("A file already exists there. Choose a new filename.") from exc
    except OSError as exc:
        raise ImgMtxError(f"Could not save the file: {exc.strerror or exc}") from exc
