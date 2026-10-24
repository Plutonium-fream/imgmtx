"""Generate the ImgMtx overlapping-image-frame icon with Pillow.

Run from any directory: python tools/make_icon.py
"""

from pathlib import Path

from PIL import Image, ImageDraw


PAPER = "#eeeee5"
INK = "#282b25"
BRICK = "#ad432c"
ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)


def make_icon() -> Image.Image:
    """Draw at four times the final resolution for clean, consistent edges."""
    factor = 4
    image = Image.new("RGB", (256 * factor, 256 * factor), INK)
    draw = ImageDraw.Draw(image)

    def rectangle(box, *, fill=None, outline=None, width=1):
        draw.rectangle(
            tuple(round(value * factor) for value in box),
            fill=fill,
            outline=outline,
            width=width * factor,
        )

    # The back frame stays visible at the top and left of the front frame.
    rectangle((38, 38, 166, 166), outline=PAPER, width=17)
    rectangle((90, 90, 218, 218), fill=INK, outline=BRICK, width=17)

    # A solid inset marks the area shared by the two image frames.
    rectangle((112, 112, 145, 145), fill=PAPER)

    return image.resize((256, 256), Image.Resampling.LANCZOS)


def main() -> None:
    destination = Path(__file__).resolve().parents[1] / "assets" / "ImgMtx.ico"
    destination.parent.mkdir(parents=True, exist_ok=True)
    make_icon().save(
        destination,
        format="ICO",
        sizes=[(size, size) for size in ICON_SIZES],
    )
    with Image.open(destination) as icon:
        actual_sizes = icon.ico.sizes()
    expected_sizes = {(size, size) for size in ICON_SIZES}
    if actual_sizes != expected_sizes:
        raise RuntimeError(f"Icon sizes do not match: {actual_sizes}")
    print(f"Created {destination} with {len(actual_sizes)} sizes (16–256 px).")


if __name__ == "__main__":
    main()
