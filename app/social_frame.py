"""Raster publication card: user text never enters FFmpeg filter syntax."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from app.subtitles import _speech_font


CARD_LAYOUTS = {"compact": {"video_top": 280, "padding": 300, "caption_size": 34},
                "post": {"video_top": 400, "padding": 420, "caption_size": 48}}


def geometry(width: int, height: int, variant: str = "compact") -> dict:
    scale = min(900 / width, 800 / height)
    video_width = max(2, int(width * scale) // 2 * 2)
    video_height = max(2, int(height * scale) // 2 * 2)
    layout = CARD_LAYOUTS[variant]
    card_height = video_height + layout["padding"]
    top = (1920 - card_height) // 2
    return {"width": video_width, "height": video_height,
            "x": (1080 - video_width) // 2, "y": top + layout["video_top"],
            "card_top": top, "card_bottom": top + card_height}


def _font(size: int):
    return ImageFont.truetype(str(_speech_font().path), size)


def _wrap(text: str, font, width: int) -> list[str]:
    lines, line = [], ""
    for word in text.split():
        if line and font.getlength(line + " " + word) > width:
            lines.append(line)
            line = ""
        for character in (" " if line else "") + word:
            if font.getlength(line + character) > width:
                lines.append(line)
                line = ""
            line += character
    if line:
        lines.append(line)
    return lines


def write_card(path: Path, width: int, height: int, video: dict) -> dict:
    variant = video.get("card_variant", "compact")
    layout = CARD_LAYOUTS[variant]
    box = geometry(width, height, variant)
    image = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    top, bottom = box["card_top"], box["card_bottom"]
    radius = 28 if variant == "post" else 4
    draw.rounded_rectangle((68, top + 10, 1020, bottom + 12), radius=radius,
                           fill=(0, 0, 0, 75))
    draw.rounded_rectangle((60, top, 1020, bottom), radius=radius,
                           fill="#14212a" if variant == "post" else "#080b0f")
    if variant == "post":
        draw.rounded_rectangle((60, top, 1020, bottom), radius=28, outline="#535662", width=2)
    name = str(video.get("channel_name", ""))
    name_font = _font(44)
    for size in range(44, 11, -1):
        name_font = _font(size)
        if name_font.getlength(name) <= 740:
            break
    draw.ellipse((94, top + 30, 160, top + 96), fill="#35343f")
    if name:
        draw.text((127, top + 63), name[0].upper(), font=_font(34),
                  fill="#dbd3f4", anchor="mm")
        draw.text((186, top + (50 if variant == "post" else 64)), name, font=name_font, fill="#f3f3fa", anchor="lm")
    handle = str(video.get("channel_handle", "")).lstrip("@")
    if variant == "post" and handle:
        handle_font = _font(26)
        while handle_font.size > 12 and handle_font.getlength("@" + handle) > 740:
            handle_font = _font(handle_font.size - 1)
        draw.text((186, top + 85), "@" + handle, font=handle_font, fill="#9b9fad", anchor="lm")
    for x in (954, 970, 986):
        draw.ellipse((x - 3, top + 62, x + 3, top + 68), fill="#999cac")
    x, y, w, h = box["x"], box["y"], box["width"], box["height"]
    draw.rectangle((x, y, x + w - 1, y + h - 1), fill=(0, 0, 0, 0))
    caption = str(video.get("post_caption", ""))
    caption_font = _font(layout["caption_size"])
    lines = _wrap(caption, caption_font, 870)
    for size in range(layout["caption_size"], 17, -1):
        caption_font = _font(size)
        lines = _wrap(caption, caption_font, 870)
        if len(lines) * (size + 9) <= layout["video_top"] - 145:
            break
    draw.multiline_text((94, top + 140), "\n".join(lines), font=caption_font,
                        fill="#d6d9e4", spacing=9)
    image.save(path)
    return box
