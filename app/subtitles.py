"""Word-clock subtitle mapping; no generated dialogue is introduced."""
from __future__ import annotations

import re
import os
from functools import lru_cache
from pathlib import Path

from PIL import ImageFont

TEXT_WIDTH = 884  # 900px safe area minus outlines and rounding allowance.


def style_identity(style: str = 'classic') -> dict:
    font = Path(_speech_font().path)
    stat = font.stat()
    return {'version': 4, 'style': style, 'font': str(font), 'size': stat.st_size,
            'mtime_ns': stat.st_mtime_ns, 'font_size': 64 if style == 'accent' else 56,
            'text_width': 780 if style == 'accent' else TEXT_WIDTH}


@lru_cache(maxsize=1)
def _speech_font():
    # Read the same installed Windows font used by libass; no installation or
    # font cache is written outside the project.
    font = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / 'arialbd.ttf'
    return ImageFont.truetype(str(font), 56)


def _width(text: str) -> float:
    # ASS escaping changes these glyphs to fullwidth forms at export.
    visible = text.replace('\\', '＼').replace('{', '｛').replace('}', '｝')
    return _speech_font().getlength(visible)


def _wrap(text: str, width: float = TEXT_WIDTH) -> list[str]:
    lines, current = [], ''
    for word in text.split():
        candidate = current + ' ' + word if current else word
        if current and _width(candidate) > width:
            lines.append(current)
            current = ''
        if _width(word) > width:
            # Preserve every character of unusually long names without adding
            # a spoken hyphen. The normal path wraps at spaces.
            for character in word:
                if current and _width(current + character) > width:
                    lines.append(current)
                    current = ''
                current += character
        else:
            current = current + ' ' + word if current else word
    if current:
        lines.append(current)
    return lines


def remap_words(words: list[dict], cuts: list[dict]) -> list[dict]:
    result, offset = [], 0.0
    for cut in cuts:
        for word in words:
            start, end = float(word["start"]), float(word["end"])
            if end <= cut["start"] or start >= cut["end"]:
                continue
            if start < cut["start"] - 0.002 or end > cut["end"] + 0.002:
                raise ValueError("Граница монтажа обрывает слово: " + word["text"])
            result.append({"start": round(offset + max(start, cut["start"]) - cut["start"], 6),
                           "end": round(offset + min(end, cut["end"]) - cut["start"], 6),
                           "text": word["text"]})
        offset += cut["end"] - cut["start"]
    return result


def _lines(text: str, width: float = TEXT_WIDTH) -> str:
    lines = _wrap(text, width)
    if len(lines) > 2:
        raise ValueError("Слишком длинный блок субтитров")
    return "\n".join(lines)


def make_cues(words: list[dict], style: str = 'classic') -> list[dict]:
    cues, group = [], []
    accent = style == 'accent'
    # Measure uppercase at the available font-size-adjusted width; final
    # libass uses 64px while the measurement font is 56px.
    width = 780 * 56 / 64 if accent else TEXT_WIDTH
    def display(text):
        return text.upper() if accent else text
    def flush():
        if group:
            cues.append({"start": group[0]["start"], "end": group[-1]["end"],
                         "text": _lines(display(" ".join(w["text"].strip() for w in group)), width)})
            group.clear()
    for word in words:
        if not word["text"].strip():
            continue
        candidate = " ".join(w["text"].strip() for w in [*group, word])
        if group and (len(_wrap(display(candidate), width)) > 2
                      or (accent and len(group) >= 5)
                      or word["end"] - group[0]["start"] > (2.4 if accent else 5.5)
                      or word["start"] - group[-1]["end"] > 0.65):
            flush()
        group.append(word)
        if re.search(r"[.!?…]$", word["text"].strip()):
            flush()
    flush()
    return cues


def _clock(seconds: float, ass: bool = False) -> str:
    unit = 100 if ass else 1000
    ticks = max(0, round(seconds * unit))
    total, fraction = divmod(ticks, unit)
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    return (f"{hours}:{minutes:02}:{seconds:02}.{fraction:02}" if ass else
            f"{hours:02}:{minutes:02}:{seconds:02},{fraction:03}")


def write_srt(path: Path, cues: list[dict]) -> None:
    path.write_text("\n\n".join(f"{i}\n{_clock(c['start'])} --> {_clock(c['end'])}\n{c['text']}"
                               for i, c in enumerate(cues, 1)) + "\n", encoding="utf-8")


def write_ass(path: Path, cues: list[dict], index: int, duration: float,
              style: str = 'classic', layout: str = 'portrait') -> None:
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Speech,Arial,56,&H00FFFFFF,&H00FFFFFF,&H00141414,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,2,90,90,285,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    if style == 'accent':
        header = header.replace('Style: Speech,Arial,56,&H00FFFFFF,&H00FFFFFF',
                                'Style: Speech,Arial,64,&H0058DFFF,&H0058DFFF')
        header = header.replace('100,100,0,0,1,3,1,2,90,90,285,1',
                                '100,100,0,0,1,5,2,2,150,150,285,1')
    if layout == 'cinema':
        header = header.replace(',285,1', ',430,1')
    # Never allow dialogue to insert ASS control/override sequences.
    def escape(text):
        return text.replace("\\", "＼").replace("{", "｛").replace("}", "｝").replace("\r", "").replace("\n", r"\N")
    lines = [header]
    for cue in cues:
        effect = r'{\fad(50,60)}' if style == 'accent' else ''
        lines.append(f"Dialogue: 0,{_clock(cue['start'], True)},{_clock(cue['end'], True)},Speech,,0,0,0,,{effect}{escape(cue['text'])}\n")
    path.write_text("".join(lines), encoding="utf-8")
