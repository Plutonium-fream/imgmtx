# Key formats and file handling

ImgMtx pairs an original PNG with a chosen hidden PNG. It stores the transformation in a separate key file. Revealing requires the exact original file and the key; the hidden source file is no longer needed.

## Binary key: `.imgkey`

A version-1 binary key contains:

1. Magic bytes `IMGMTX\r\n`.
2. A four-byte, big-endian JSON-header length.
3. A bounded ASCII JSON header with the format version, transformation name, original and hidden SHA-256 checksums, random salt, hidden dimensions, and payload length.
4. The transformation payload.

The payload XORs the hidden PNG's file bytes with a SHAKE256 stream derived from the original PNG contents, a domain separator, and a random salt. Recovery reconstructs the hidden PNG's exact file bytes, including metadata, colour mode, and transparency.

Two keys created from the same pair can differ because each creation uses a fresh salt. A given original and key always recover the same hidden image.

## Text key: `.txt`

A text key begins with `IMGMTX-TEXT-1` and a newline, followed by the Base64-encoded binary key and a final newline. Text adds approximately one third to the binary size.

## Image key: `.png`

An image key is an ordinary, opaque RGB PNG with a near-square canvas. Its RGB pixel bytes contain:

1. Magic bytes `IMGMTX-PIXELS\0`.
2. A one-byte carrier version.
3. An eight-byte, big-endian binary-key length.
4. A SHA-256 checksum of the prefix and binary key.
5. The complete binary key.
6. Zero padding to fill the remaining pixels.

The key lives in pixel data, rather than PNG metadata. Lossless PNG re-saving, metadata changes, and conversion to fully opaque RGBA preserve recovery if every RGB pixel remains identical. Resizing, changing colours, introducing transparency, JPEG conversion, and palette conversion are unsupported. Animated key PNGs are rejected.

ImgMtx recognises all three formats from their contents. Nested carrier envelopes are rejected.

## Limits and checks

- Original and hidden PNG files: at most 64 MiB and 25 million pixels each.
- Binary header: at most 4 KiB.
- Key files have a separate byte limit that accommodates text encoding and PNG-container overhead.
- A maximum-size PNG key fits within 4730 × 4730 pixels, below the 25-million-pixel limit.
- Original fingerprints, carrier checksums, hidden-image checksums, dimensions, lengths, and format versions are checked before a reveal is accepted.
- Writes create new files exclusively. Existing files, including original inputs and aliases, cannot be overwritten.

## Original versus image key

The **original PNG must remain byte-for-byte identical**. Re-saving identical pixels, changing metadata, or optimising its encoding changes the original's fingerprint. Moving or renaming the original is fine.

An **image key must retain identical RGB pixels and dimensions**. Its metadata and lossless PNG compression can change.

## Security model

ImgMtx is an image-mapping utility, not password-protected encryption or a secure messaging protocol. Anyone with both the original and the key can reveal the hidden image. If the original is public, possession of the key is enough. Checksums detect accidental corruption; they do not authenticate a sender or protect against deliberate modification.

Processing stays local and in memory until the user explicitly saves a file. Clearing the workspace removes loaded references and previews; it is not a secure memory eraser. PNG inputs may contain metadata, and hidden metadata is preserved on export.
