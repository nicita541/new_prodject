"""Remove confirmed production-title cards from actual selected source units."""
from __future__ import annotations

from app.source_ranges import subtract_ranges as _subtract

import copy
import hashlib
import json
import math
import os
from pathlib import Path
import urllib.error

from .config import ROOT, VLM_MODEL, VLM_PROJECTOR
from .story import _protected_speech, _spoken_words

TITLES_VERSION = 6


def title_units(start, end, transcript, shots):
    """Use real silent shot boundaries even for sub-two-second bumpers.

    Story units have a minimum size to keep replies coherent. A production
    check must not merge a short logo with the following character dialogue.
    These finer boundaries never split recognized speech or its handles.
    """
    from app.story_review import candidate_units
    original = candidate_units(start, end, transcript, shots)
    boundaries = {start, end} | {unit['start'] for unit in original}
    for shot in shots:
        value = shot['start']
        if start < value < end and not any(
                span['start']-.25 < value < span['end']+.3
                for span in transcript.get('segments', []) + transcript.get('words', [])):
            boundaries.add(value)
    ordered = sorted(boundaries)
    return [{'id':f't{i:03d}', 'start':left, 'end':right,
             'text':' '.join(span['text'] for span in transcript.get('segments', [])
                            if span['start'] < right and span['end'] > left)}
            for i,(left,right) in enumerate(zip(ordered,ordered[1:]))]


def _candidates(event, units, transcript):
    selected = []
    for unit in units:
        for selection in event.get('selected_ranges', [event]):
            left, right = max(unit['start'], selection['start']), min(unit['end'], selection['end'])
            if left < right:
                selected.append({**unit, 'start':left, 'end':right})
    runs, current = [], []
    for unit in selected:
        silent = not _spoken_words(unit, transcript)
        if current and (not silent or unit['start'] > current[-1]['end']+.002):
            runs.append(current)
            current = []
        if silent:
            current.append(unit)
    if current:
        runs.append(current)
    candidates = [unit for run in runs for unit in run]
    # A brief narrated title may border a silent card. Do not scan arbitrary
    # dialogue; current-source imagery must independently prove the title.
    for unit in selected:
        words = _spoken_words(unit, transcript)
        if not 0 < len(words) < 8 or _protected_speech(unit, transcript):
            continue
        if any(abs(unit['end']-run[0]['start']) <= .002 or abs(unit['start']-run[-1]['end']) <= .002 for run in runs):
            candidates.append(unit)
    return sorted(candidates, key=lambda unit:(unit['start'],unit['end']))


def _decision(raw, spoken):
    keys = ('visible_production_title','wholly_nonnarrative','continuous_narrative',
            'narrated_title','meaningful_character_dialogue')
    if not isinstance(raw, dict) or any(not isinstance(raw.get(key), bool) for key in keys):
        raise ValueError('Некорректная оценка изображения титра')
    confidence = raw.get('confidence')
    if isinstance(confidence, bool) or not isinstance(confidence, (int,float)) or not math.isfinite(confidence) or not 0 <= confidence <= 1:
        raise ValueError('Некорректная уверенность титра')
    return (confidence >= .85 and raw['visible_production_title'] and raw['wholly_nonnarrative']
            and not raw['continuous_narrative'] and not raw['meaningful_character_dialogue']
            and (not spoken or raw['narrated_title']))


def _groups(candidates):
    groups=[]
    for unit in candidates:
        if groups and abs(groups[-1][-1]['end']-unit['start']) <= .002:
            groups[-1].append(unit)
        else:
            groups.append([unit])
    return groups


def _extend_bumpers(event, candidates, excluded, checked, transcript, shots,
                    source, directory, identity, models, vision, report, cancelled):
    """Confirm abstract animation adjoining a proven logo, never a time pad."""
    from app.vision import storyboard
    attempted = set()
    while True:
        target = None
        for unit in candidates:
            key = (unit['id'],unit['start'],unit['end'])
            raw = checked.get(key, {})
            if (unit in excluded or key in attempted or _spoken_words(unit, transcript)
                    or raw.get('wholly_nonnarrative') is not True
                    or raw.get('continuous_narrative') is not False
                    or raw.get('meaningful_character_dialogue') is not False
                    or raw.get('confidence', 0) < .85):
                continue
            anchor = next((item for item in excluded if
                           abs(item['end']-unit['start']) <= .002 or
                           abs(unit['end']-item['start']) <= .002), None)
            if anchor is not None:
                target = (unit, anchor)
                break
        if target is None:
            return
        unit, anchor = target
        key = (unit['id'],unit['start'],unit['end'])
        attempted.add(key)
        if cancelled():
            raise InterruptedError('Обработка отменена')
        label = 'bumper_'+hashlib.sha256(json.dumps([event['id'],unit,anchor]).encode()).hexdigest()[:24]
        image, checkpoint = directory/(label+'.jpg'), directory/(label+'.json')
        try:
            storyboard(source,min(unit['start'],anchor['start']),max(unit['end'],anchor['end']),
                       shots,transcript,image,cancelled)
            signature=hashlib.sha256(json.dumps({'version':TITLES_VERSION,'source':identity,'models':models,
                'thinking':bool(getattr(vision,'thinking',False)),
                'unit':unit,'anchor':anchor,'unit_decision':checked[key],
                'image':hashlib.sha256(image.read_bytes()).hexdigest()},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
            raw=None
            if checkpoint.is_file():
                saved=json.loads(checkpoint.read_text('utf-8'))
                if saved.get('signature')==signature:
                    raw=saved.get('decision')
            if raw is None:
                report('condense',.4893,'Проверка анимации рядом с подтверждённой заставкой')
                schema={'type':'object','properties':{key:{'type':'boolean'} for key in
                    ('same_production_bumper','wholly_nonnarrative','continuous_narrative')}}
                schema['properties']['confidence']={'type':'number','enum':[round(i/20,2) for i in range(21)]}
                schema.update(required=list(schema['properties']),additionalProperties=False)
                raw=vision.query(f'Target source unit {unit["start"]:.3f}..{unit["end"]:.3f}s has no speech. '
                    f'Adjacent verified production-logo/bumper unit is {anchor["start"]:.3f}..{anchor["end"]:.3f}s. '
                    'Look at the CURRENT chronological frames of both. Does the WHOLE target belong to the SAME '
                    'abstract logo animation/fade/production bumper? Adjacency, silence, music or similar colors alone '
                    'are not proof. Preserve narrative establishing shots, actions and reactions, including scenes '
                    'before/after a bumper. Return same_production_bumper, wholly_nonnarrative, continuous_narrative, confidence.',
                    image,max_tokens=150,schema=schema)
            if (not isinstance(raw,dict) or any(type(raw.get(key)) is not bool for key in
                    ('same_production_bumper','wholly_nonnarrative','continuous_narrative'))
                    or isinstance(raw.get('confidence'),bool) or not isinstance(raw.get('confidence'),(int,float))
                    or not math.isfinite(raw['confidence']) or not 0 <= raw['confidence'] <= 1):
                raise ValueError('Некорректная проверка анимации заставки')
            if cancelled():
                raise InterruptedError('Обработка отменена')
            temporary=checkpoint.with_suffix('.tmp')
            temporary.write_text(json.dumps({'signature':signature,'version':TITLES_VERSION,'decision':raw},ensure_ascii=False),'utf-8')
            os.replace(temporary,checkpoint)
            if (raw['confidence'] >= .85 and raw['same_production_bumper']
                    and raw['wholly_nonnarrative'] and not raw['continuous_narrative']):
                excluded.append(unit)
        except InterruptedError:
            raise
        except (ValueError,KeyError,TypeError,RuntimeError,TimeoutError,OSError,urllib.error.URLError) as error:
            event.setdefault('story_warnings',[]).append('Анимация заставки не подтверждена: '+str(error)[:180]+'; фрагмент сохранён')


def refine_titles(events, transcript, shots, job_dir:Path, vision, report, cancelled):
    from app.vision import storyboard
    result = copy.deepcopy(events)
    source = None
    try:
        source = Path(json.loads((job_dir/'source.json').read_text('utf-8'))['path']).resolve()
        if not source.is_relative_to(ROOT.resolve()) or not source.is_file():
            source = None
    except (ValueError,KeyError,TypeError,OSError):
        pass
    directory = job_dir/'title_units'
    directory.mkdir(exist_ok=True)
    models = []
    for model in (getattr(vision,'model',VLM_MODEL),getattr(vision,'projector',VLM_PROJECTOR)):
        path = Path(model)
        models.append({'path':str(path),'size':path.stat().st_size,'mtime_ns':path.stat().st_mtime_ns}
                      if path.is_file() else {'path':str(path)})
    if getattr(vision, 'cache_profile', None) is not None:
        models.append({'provider_profile': vision.cache_profile})
    identity = {'path':str(source),'size':source.stat().st_size,'mtime_ns':source.stat().st_mtime_ns} if source else None
    for event_index, event in enumerate(result):
        if cancelled():
            raise InterruptedError('Обработка отменена')
        if event.get('credit_montage'):
            continue
        units = title_units(event['start'],event['end'],transcript,shots)
        candidates = _candidates(event,units,transcript)
        if not candidates:
            continue
        if source is None:
            event.setdefault('story_warnings',[]).append('Промежуточный титр не проверен: источник недоступен; сцена сохранена')
            continue
        screened=[]
        for group in [candidates]:
            if cancelled():
                raise InterruptedError('Обработка отменена')
            label='screen_'+hashlib.sha256(json.dumps([event['id'],group]).encode()).hexdigest()[:24]
            image,checkpoint=directory/(label+'.jpg'),directory/(label+'.json')
            try:
                storyboard(source,group[0]['start'],group[-1]['end'],shots,transcript,image,cancelled)
                signature=hashlib.sha256(json.dumps({'version':TITLES_VERSION,'profile':'production-screen-v3-one-event',
                    'source':identity,'models':models,'thinking':bool(getattr(vision,'thinking',False)),
                    'units':group,'shots':shots,'image':hashlib.sha256(image.read_bytes()).hexdigest()},
                    sort_keys=True,ensure_ascii=False).encode()).hexdigest()
                raw=None
                if checkpoint.is_file():
                    try:
                        cached=json.loads(checkpoint.read_text('utf-8'))
                        if cached.get('version')==TITLES_VERSION and cached.get('signature')==signature:
                            raw=cached.get('decision')
                    except (ValueError,TypeError,AttributeError):
                        pass
                if raw is None:
                    report('condense',.4893,f'Поиск титров: событие {event_index+1} из {len(result)}')
                    schema={'type':'object','properties':{'visible_production_title':{'type':'boolean'},
                        'confidence':{'type':'number','enum':[round(i/20,2) for i in range(21)]}},
                        'required':['visible_production_title','confidence'],'additionalProperties':False}
                    raw=vision.query('Look ONLY at these CURRENT frames. Is any studio/distributor logo, production bumper, production-credit or episode-title text '
                        'visibly present? Street/shop/train signs, scene documents and dialogue subtitles are not production titles. '
                        'Music and characters alone are not evidence. Return visible_production_title and confidence.',
                        image,max_tokens=80,schema=schema)
                confidence=raw.get('confidence') if isinstance(raw,dict) else None
                if (not isinstance(raw,dict) or not isinstance(raw.get('visible_production_title'),bool)
                    or isinstance(confidence,bool) or not isinstance(confidence,(float,int))
                    or not math.isfinite(confidence) or not 0<=confidence<=1):
                    raise ValueError('Некорректная проверка наличия заголовка')
                if confidence < .85:
                    event.setdefault('story_warnings',[]).append('Видимый заголовок не подтверждён уверенно; фрагмент сохранён')
                elif raw['visible_production_title']:
                    screened.extend(group)
                if cancelled():
                    raise InterruptedError('Обработка отменена')
                temporary=checkpoint.with_suffix('.tmp')
                temporary.write_text(json.dumps({'version':TITLES_VERSION,'signature':signature,'decision':raw},ensure_ascii=False),encoding='utf-8')
                os.replace(temporary,checkpoint)
            except InterruptedError:
                raise
            except (ValueError,KeyError,TypeError,RuntimeError,TimeoutError,OSError,urllib.error.URLError) as error:
                event.setdefault('story_warnings',[]).append('Видимый заголовок не проверен: '+str(error)[:180]+'; фрагмент сохранён')
        excluded, checked = [], {}
        for unit in screened:
            if cancelled():
                raise InterruptedError('Обработка отменена')
            label = hashlib.sha256(json.dumps([event['id'],unit['id'],unit['start'],unit['end']]).encode()).hexdigest()[:24]
            image, checkpoint = directory/(label+'.jpg'), directory/(label+'.json')
            report('condense',.4893,f'Подтверждение титра: событие {event_index+1} из {len(result)}')
            try:
                storyboard(source,unit['start'],unit['end'],shots,transcript,image,cancelled)
                signature = hashlib.sha256(json.dumps({'version':TITLES_VERSION,'source':identity,'models':models,
                    'thinking':bool(getattr(vision,'thinking',False)),'unit':unit,'transcript':transcript,
                    'shots':shots,'image':hashlib.sha256(image.read_bytes()).hexdigest()},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
                raw = None
                if checkpoint.is_file():
                    try:
                        cached = json.loads(checkpoint.read_text('utf-8'))
                        if cached.get('version') == TITLES_VERSION and cached.get('signature') == signature:
                            raw = cached.get('decision')
                    except (ValueError,TypeError,AttributeError):
                        pass
                if raw is None:
                    schema = {'type':'object','properties':{
                        key:{'type':'boolean'} for key in ('visible_production_title','wholly_nonnarrative',
                            'continuous_narrative','narrated_title','meaningful_character_dialogue')}}
                    schema['properties']['confidence'] = {'type':'number','enum':[round(i/20,2) for i in range(21)]}
                    schema.update(required=list(schema['properties']),additionalProperties=False)
                    raw = vision.query('These frames are ONLY current source unit '+unit['id']+
                        f', {unit["start"]:.2f}..{unit["end"]:.2f}s. Does the whole unit show a visible studio/distributor bumper, logo or production/episode title '
                        'with no continuous plot action? Street/shop/train signs, in-scene documents and subtitles are not production titles. '
                        'Music/silence alone is not evidence. Preserve new silent action and character dialogue even over credits. '
                        'Actual words: '+json.dumps(unit['text'],ensure_ascii=False)+'. A narrated visible title differs from character speech. '
                        'Return visible_production_title, wholly_nonnarrative, continuous_narrative, narrated_title, '
                        'meaningful_character_dialogue, confidence.',image,max_tokens=170,schema=schema)
                if _decision(raw,bool(_spoken_words(unit,transcript))):
                    excluded.append(unit)
                elif raw['confidence'] < .85:
                    event.setdefault('story_warnings',[]).append(f"{unit['id']}: промежуточный титр не подтверждён; сцена сохранена")
                checked[(unit['id'],unit['start'],unit['end'])] = raw
                if cancelled():
                    raise InterruptedError('Обработка отменена')
                temporary = checkpoint.with_suffix('.tmp')
                temporary.write_text(json.dumps({'version':TITLES_VERSION,'signature':signature,'decision':raw},ensure_ascii=False),encoding='utf-8')
                os.replace(temporary,checkpoint)
            except InterruptedError:
                raise
            except (ValueError,KeyError,TypeError,RuntimeError,TimeoutError,OSError,urllib.error.URLError) as error:
                event.setdefault('story_warnings',[]).append('Промежуточный титр не подтверждён: '+str(error)[:180]+'; сцена сохранена')
        if excluded:
            _extend_bumpers(event,screened,excluded,checked,transcript,shots,source,
                            directory,identity,models,vision,report,cancelled)
            excluded.sort(key=lambda unit:(unit['start'],unit['end']))
            ranges = _subtract(event.get('selected_ranges', [event]),excluded)
            event['excluded_title_units'] = [{'id':u['id'],'start':u['start'],'end':u['end']} for u in excluded]
            event['titles_refinement_version'] = TITLES_VERSION
            if ranges:
                event['selected_ranges'] = ranges
            else:
                event.update(credit_montage=True,contains_credits=True,credits_kind='title',kind='filler',importance=1,requires=[])
    return result
