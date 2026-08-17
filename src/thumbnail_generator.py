"""Generate an eye-catching vertical thumbnail for a generated video.

The thumbnail reuses the first scene image as the background, darkens it with a
bottom-up gradient for legibility and overlays the video title using one of the
bundled fonts. A strong, readable title card is the single biggest driver of
click-through rate on Shorts/Reels/TikTok, so this runs automatically at the
end of the pipeline.
"""

import os
import textwrap
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

script_dir = os.path.dirname(os.path.abspath(__file__))
FONT_DIR = os.path.join(os.path.dirname(script_dir), "font")


def _load_font(font_name: str, size: int) -> ImageFont.FreeTypeFont:
    """Load a bundled TrueType font, falling back to PIL's default."""
    font_path = os.path.join(FONT_DIR, font_name)
    try:
        return ImageFont.truetype(font_path, size)
    except Exception:
        try:
            return ImageFont.load_default(size)
        except TypeError:
            # Older Pillow: load_default() takes no size argument.
            return ImageFont.load_default()


def _text_width(draw: ImageDraw.ImageDraw, text: str, font) -> float:
    """Width of `text` for the given font, across Pillow versions."""
    try:
        return draw.textlength(text, font=font)
    except AttributeError:
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0]


def _wrap_text(draw, text, font, max_width) -> list:
    """Greedy word-wrap so each line fits within `max_width` pixels."""
    words = text.split()
    if not words:
        return []
    lines, current = [], words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if _text_width(draw, candidate, font) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def generate_thumbnail(
    image_path: str,
    title: str,
    output_path: str,
    font_name: str = "TitanOne.ttf",
) -> Optional[str]:
    """Create a titled thumbnail from `image_path` and save it to `output_path`.

    Returns the output path on success, or None if the source image could not
    be opened (the caller treats the thumbnail as a nice-to-have, never a hard
    failure of the pipeline).
    """
    try:
        base = Image.open(image_path).convert("RGB")
    except Exception as e:
        print(f"Could not open image for thumbnail: {e}")
        return None

    width, height = base.size

    # Bottom-up dark gradient so text stays readable over any image.
    gradient = Image.new("L", (1, height), color=0)
    fade_start = int(height * 0.45)
    for y in range(fade_start, height):
        alpha = int(200 * (y - fade_start) / max(1, height - fade_start))
        gradient.putpixel((0, y), alpha)
    gradient = gradient.resize((width, height))
    shadow = Image.new("RGB", (width, height), color=0)
    base = Image.composite(shadow, base, gradient)

    draw = ImageDraw.Draw(base)

    clean_title = (title or "").strip().strip('"')
    if clean_title:
        max_text_width = int(width * 0.9)
        # Scale the font to the image width and clamp to a sane range.
        font_size = max(48, min(int(width * 0.11), 130))
        font = _load_font(font_name, font_size)

        # Shrink until the longest word fits, then wrap to lines.
        while font_size > 40:
            longest = max(clean_title.split(), key=len, default="")
            if _text_width(draw, longest, font) <= max_text_width:
                break
            font_size -= 6
            font = _load_font(font_name, font_size)

        lines = _wrap_text(draw, clean_title, font, max_text_width)
        line_height = int(font_size * 1.15)
        block_height = line_height * len(lines)

        # Anchor the title block in the lower third of the frame.
        y = height - int(height * 0.12) - block_height
        stroke_width = max(2, font_size // 18)
        for line in lines:
            line_width = _text_width(draw, line, font)
            x = (width - line_width) / 2
            draw.text(
                (x, y),
                line,
                font=font,
                fill="white",
                stroke_width=stroke_width,
                stroke_fill="black",
            )
            y += line_height

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    base.save(output_path)
    print(f"Thumbnail created: {output_path}")
    return output_path
