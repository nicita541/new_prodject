"""Raster publication card: user text never enters FFmpeg filter syntax."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageFilter

from app.subtitles import _speech_font
from app.finishing_avatar import draw_avatar


CARD_LAYOUTS = {"compact": {"video_top": 280, "padding": 340, "caption_size": 34},
                "post": {"video_top": 400, "padding": 460, "caption_size": 48}}


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


def write_card(path: Path, width: int, height: int, video: dict, *, avatar: Path | None = None,
               duration: float | None = None) -> dict:
    variant = video.get("card_variant", "compact")
    layout = CARD_LAYOUTS[variant]
    box = geometry(width, height, variant)
    image = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
    top, bottom = box["card_top"], box["card_bottom"]
    radius = 38
    shadow = Image.new('RGBA', image.size)
    ImageDraw.Draw(shadow).rounded_rectangle((60, top + 20, 1020, bottom + 20), radius=radius,
                                             fill=(0, 0, 0, 125))
    image.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(22)))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((60, top, 1020, bottom), radius=radius, fill='#1b3042', outline='#29465d', width=2)
    # A small messenger-bubble tail, kept away from the media and caption.
    draw.polygon([(64, bottom - 53), (40, bottom - 13), (87, bottom - 26)], fill='#1b3042')
    draw.line((99, top + 2, 981, top + 2), fill='#38556b', width=2)
    name = str(video.get("channel_name", ""))
    name_font = _font(44)
    for size in range(44, 11, -1):
        name_font = _font(size)
        if name_font.getlength(name) <= 705:
            break
    image.alpha_composite(draw_avatar(video, 84, avatar), (94, top + 30))
    draw = ImageDraw.Draw(image)
    if name:
        draw.text((202, top + 56), name, font=name_font, fill='#79bce8', anchor='lm')
    handle = str(video.get("channel_handle", "")).lstrip("@")
    if handle:
        handle_font = _font(26)
        while handle_font.size > 12 and handle_font.getlength("@" + handle) > 740:
            handle_font = _font(handle_font.size - 1)
        draw.text((202, top + 94), "@" + handle, font=handle_font, fill='#93acbf', anchor='lm')
    else:
        draw.text((202, top + 94), 'Канал', font=_font(26), fill='#93acbf', anchor='lm')
    for x in (954, 970, 986):
        draw.ellipse((x - 3, top + 62, x + 3, top + 68), fill="#999cac")
    x, y, w, h = box["x"], box["y"], box["width"], box["height"]
    draw.rounded_rectangle((x, y, x + w - 1, y + h - 1), radius=min(24, w // 8), fill=(0, 0, 0, 0))
    caption = str(video.get("post_caption", ""))
    caption_font = _font(layout["caption_size"])
    lines = _wrap(caption, caption_font, 870)
    for size in range(layout["caption_size"], 17, -1):
        caption_font = _font(size)
        lines = _wrap(caption, caption_font, 870)
        if len(lines) * (size + 9) <= layout["video_top"] - 145:
            break
    draw.multiline_text((94, top + 140), "\n".join(lines), font=caption_font,
                        fill='#edf5fc', spacing=9)
    footer = 'Видео'
    if duration is not None:
        seconds = max(0, round(duration))
        footer += f' · {seconds // 60}:{seconds % 60:02}'
    draw.text((98, bottom - 30), footer, font=_font(24), fill='#93acbf', anchor='lm')
    image.save(path)
    return box
