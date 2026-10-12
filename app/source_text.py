"""Source-bound transcript text and normalized quote matching.

A whole segment without word timestamps belongs only to a containing interval.
"""
from __future__ import annotations

import re


def source_text(transcript, start, end):
    return ' '.join(str(w.get('text', '')) for w in (transcript.get('words') or transcript.get('segments', []))
                    if start <= w['start'] and w['end'] <= end)


def tokens(text):
    return re.findall(r'\w+', text.casefold().replace('ё', 'е'))


def quote_in(quote, text):
    q, t = tokens(quote), tokens(text)
    return bool(q) and any(t[i:i+len(q)] == q for i in range(len(t)-len(q)+1))
