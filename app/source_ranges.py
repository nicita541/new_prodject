"""Finite source-time range algebra, independent of models and classification."""
from __future__ import annotations

import math


def merge_ranges(ranges):
    merged=[]
    for value in sorted(ranges,key=lambda r:r['start']):
        a,b=float(value['start']),float(value['end'])
        if not math.isfinite(a) or not math.isfinite(b) or a>=b:
            raise ValueError('Некорректный подтверждённый интервал')
        if merged and a<=merged[-1]['end']:
            merged[-1]['end']=max(merged[-1]['end'],b)
        else:
            merged.append({'start':a,'end':b})
    return merged

def intersect_ranges(left, right):
    return merge_ranges([{'start':max(a['start'],b['start']), 'end':min(a['end'],b['end'])}
        for a in left for b in right if a['start'] < b['end'] and a['end'] > b['start']])


def subtract_ranges(selections, excluded):
    result = []
    for selection in selections:
        pieces = [(selection['start'],selection['end'])]
        for unit in excluded:
            following = []
            for left,right in pieces:
                if unit['end'] <= left or unit['start'] >= right:
                    following.append((left,right))
                else:
                    if left < unit['start']:
                        following.append((left,unit['start']))
                    if unit['end'] < right:
                        following.append((unit['end'],right))
            pieces = following
        for left,right in pieces:
            if result and left <= result[-1]['end']:
                result[-1]['end'] = max(result[-1]['end'],right)
            else:
                result.append({'start':left,'end':right})
    return result
