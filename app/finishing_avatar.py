"""Owned immutable channel avatars and local preset artwork."""
from __future__ import annotations

import io
import re
import uuid
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageChops
from app.subtitles import _speech_font

MAX_AVATAR_BYTES = 4 * 1024 * 1024
AVATAR_PATTERN = r'av_[0-9a-f]{32}_[0-9a-f]{32}'
PRESETS = ('initials', 'star', 'play', 'chat')


def avatar_path(root: Path, identifier: str, episode_id: str | None = None) -> Path:
    if not isinstance(identifier, str) or not re.fullmatch(AVATAR_PATTERN, identifier):
        raise ValueError('Некорректная иконка канала')
    if episode_id is not None and identifier.split('_')[1] != uuid.UUID(episode_id).hex:
        raise ValueError('Иконка принадлежит другой серии')
    folder = (root / 'finishing' / 'avatars').resolve()
    folder.relative_to(root.resolve())
    path = (folder / (identifier + '.png')).resolve()
    path.relative_to(folder)
    return path


def resolve_avatar(root: Path, video: dict, episode_id: str | None = None) -> Path | None:
    if not video.get('avatar_id'):
        return None
    path = avatar_path(root, video['avatar_id'], episode_id)
    if not path.is_file():
        raise ValueError('Иконка канала не найдена. Загрузите её снова.')
    return path if video.get('avatar_style') == 'image' else None


def store_avatar(root: Path, episode_id: str, data: bytes) -> str:
    if not data or len(data) > MAX_AVATAR_BYTES:
        raise ValueError('Выберите изображение PNG, JPEG или WebP до 4 МБ')
    with Image.open(io.BytesIO(data)) as source:
        if (source.format not in ('PNG', 'JPEG', 'WEBP') or source.width < 16 or source.height < 16
                or source.width > 8192 or source.height > 8192 or source.width * source.height > 16_000_000):
            raise ValueError('Изображение должно быть от 16 пикселей и не более 16 мегапикселей')
        image = ImageOps.fit(ImageOps.exif_transpose(source).convert('RGBA'), (512, 512),
                             method=Image.Resampling.LANCZOS)
        identifier = 'av_' + uuid.UUID(episode_id).hex + '_' + uuid.uuid4().hex
        path = avatar_path(root, identifier, episode_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        # New generated ID, canonical pixels only: no original path/name/metadata.
        image.save(path, format='PNG')
    return identifier


def draw_avatar(video: dict, size: int = 84, image_path: Path | None = None) -> Image.Image:
    scale = 4
    side = size * scale
    if image_path is not None and video.get('avatar_style') == 'image':
        with Image.open(image_path) as source:
            image = ImageOps.fit(source.convert('RGBA'), (side, side), method=Image.Resampling.LANCZOS)
    else:
        image = Image.new('RGBA', (side, side))
        draw = ImageDraw.Draw(image)
        for y in range(side):
            fraction = y / max(1, side - 1)
            draw.line((0, y, side, y), fill=(int(82 - 53 * fraction), int(169 - 80 * fraction),
                                           int(220 - 58 * fraction), 255))
        draw.ellipse((side * .08, side * .08, side * .92, side * .92), outline=(255, 255, 255, 70), width=scale)
        kind = video.get('avatar_style', 'initials')
        white = '#edf8ff'
        if kind == 'star':
            import math
            points = [(side / 2 + side * (.29 if i % 2 == 0 else .13) * math.cos(-math.pi / 2 + i * math.pi / 5),
                       side / 2 + side * (.29 if i % 2 == 0 else .13) * math.sin(-math.pi / 2 + i * math.pi / 5))
                      for i in range(10)]
            draw.polygon(points, fill=white)
        elif kind == 'play':
            draw.polygon([(side * .39, side * .28), (side * .72, side * .5), (side * .39, side * .72)], fill=white)
        elif kind == 'chat':
            draw.rounded_rectangle((side * .23, side * .27, side * .77, side * .65), radius=side * .1, fill=white)
            draw.polygon([(side * .32, side * .6), (side * .32, side * .76), (side * .5, side * .61)], fill=white)
        else:
            initial = str(video.get('channel_name', '')).strip()[:1].upper() or 'К'
            font = ImageFont.truetype(str(_speech_font().path), int(side * .48))
            draw.text((side / 2, side * .49), initial, font=font, fill=white, anchor='mm')
    mask = Image.new('L', (side, side))
    ImageDraw.Draw(mask).ellipse((0, 0, side - 1, side - 1), fill=255)
    image.putalpha(ImageChops.multiply(image.getchannel('A'), mask))
    return image.resize((size, size), Image.Resampling.LANCZOS)
