"""Read-only evaluator for completed raw-video production renders.

CLI: portable Python scripts/verify_production_raw_exports.py --job-dir JOB
     --scenario A..J [--review-manifest MANIFEST]

Print JSON; exit 0=passed, 1=failed, 2=unresolved/not exercised. Review records
use scenario/case, source, source_sha256, input, input_manifest_sha256, and
optional groundtruth or facts. Expected answers are evaluator-only: this
script never calls a provider, analysis, planning or rendering. Existing A/C/D/
E/F fixture criteria are reused only after the finished source hashes match.
Media tools write to pipes; completed jobs and their artifacts stay unchanged.
Artifact consistency cannot independently authenticate a model execution or
prove subjective semantic/framing quality. Confidence remains self-reported.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.config import FFMPEG, FFPROBE

VERSION = 1
STAGE1 = {'A':'kidnapping_vehicle', 'C':'binding_same_background', 'D':'similar_rooms',
          'E':'reverse_shots_same_room', 'F':'long_tracking_action'}
POSITIVE = {'physical_action','state_transition','causal_dialogue','response',
            'character_reaction','emotional_pause','comedic_payoff','establishing_context'}
UNRESOLVED_FLAGS = ('uncertain','selection_uncertain','analysis_unresolved',
                    'global_verification_unresolved','source_role_unresolved',
                    'whole_scene_last_resort','selection_needs_adjudication')


class AuditError(ValueError):
    def __init__(self, code, detail, status='failed'):
        super().__init__(detail)
        self.code, self.status = code, status


def _workspace(path):
    path = Path(path).resolve()
    if not path.is_relative_to(ROOT.resolve()):
        raise AuditError('outside_workspace', 'Artifact is outside the workspace')
    return path


def _read(path):
    path = _workspace(path)
    if not path.is_file():
        raise AuditError('missing_artifact', str(path), 'unresolved')
    try:
        return json.loads(path.read_text('utf-8-sig'),
                          parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    except (ValueError, UnicodeError) as error:
        raise AuditError('invalid_json', str(path)) from error


def _sha(path):
    path = _workspace(path)
    if not path.is_file():
        raise AuditError('missing_artifact', str(path), 'unresolved')
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _ranges(rows):
    if not isinstance(rows, list) or any(not isinstance(row, dict)
            or not _number(row.get('start')) or not _number(row.get('end'))
            or not 0 <= row['start'] < row['end'] for row in rows):
        raise AuditError('invalid_source_ranges', 'Source ranges must be finite positive intervals')
    result = []
    for row in sorted(rows, key=lambda r:(r['start'],r['end'])):
        if result and row['start'] <= result[-1]['end']+.002:
            result[-1]['end'] = max(result[-1]['end'], row['end'])
        else:
            result.append({'start':row['start'],'end':row['end']})
    return result


def _covers(rows, targets):
    merged = _ranges(rows)
    return all(any(row['start'] <= target['start']+.002 and row['end'] >= target['end']-.002
                   for row in merged) for target in _ranges(targets))


def _overlap(rows, span):
    return any(row['start'] < span['end'] and span['start'] < row['end'] for row in rows)


def _span(value):
    if not isinstance(value, list) or len(value) != 2:
        raise AuditError('missing_review_fact', 'Review interval is missing', 'unresolved')
    return _ranges([{'start':value[0],'end':value[1]}])[0]


def _tokens(text):
    return re.findall(r'\w+|[^\w\s]', str(text).casefold().replace('ё','е'))


def _contains(text, quote):
    words, phrase = _tokens(text), _tokens(quote)
    return bool(phrase) and any(words[i:i+len(phrase)] == phrase for i in range(len(words)-len(phrase)+1))


def _tool(argv, timeout=180):
    process = subprocess.run([str(a) for a in argv], cwd=ROOT, capture_output=True,
                             timeout=timeout, creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    if process.returncode:
        raise AuditError('media_decode_failed', process.stderr.decode('utf-8', errors='replace')[-1200:])
    return process.stdout


def _probe(path, *, count_frames=False):
    if not FFPROBE.is_file():
        raise AuditError('missing_ffprobe', 'Portable FFprobe is unavailable', 'unresolved')
    args = [FFPROBE, '-v','error']
    if count_frames:
        args.append('-count_frames')
    return json.loads(_tool([*args,'-show_streams','-show_format','-of','json',_workspace(path)]))


def _decode(path):
    if not FFMPEG.is_file():
        raise AuditError('missing_ffmpeg', 'Portable FFmpeg is unavailable', 'unresolved')
    _tool([FFMPEG,'-nostdin','-v','error','-xerror','-i',_workspace(path),
           '-map','0:v:0','-map','0:a:0','-f','null','-'])


def _export_media(path, expected):
    """Mirror validate_export's format constraints without its workdir writes."""
    if path.stat().st_size < 1000:
        raise AuditError('invalid_export', 'Empty/incomplete export')
    info = _probe(path, count_frames=True)
    videos = [s for s in info.get('streams',[]) if s.get('codec_type')=='video']
    audios = [s for s in info.get('streams',[]) if s.get('codec_type')=='audio']
    if len(videos)!=1 or not audios:
        raise AuditError('invalid_export', 'Export requires one video stream and decoded audio')
    video, audio = videos[0], audios[0]
    duration = float(info['format']['duration'])
    video_duration,audio_duration = float(video.get('duration',duration)),float(audio.get('duration',duration))
    num, den = map(int, video['avg_frame_rate'].split('/'))
    if (any(not math.isfinite(t) or t<=0 for t in (duration,video_duration,audio_duration))
            or video.get('codec_name')!='h264' or audio.get('codec_name')!='aac'
            or video.get('width')!=1080 or video.get('height')!=1920 or not den
            or abs(num/den-30)>.01 or abs(duration-expected)>.15
            or duration > (150 if expected>120 else 120)+.001
            or abs(video_duration-audio_duration)>.15):
        raise AuditError('invalid_export', 'Export format/duration/audio sync differs from production contract')
    try:
        video_frames, audio_frames = int(video['nb_read_frames']), int(audio['nb_read_frames'])
    except (KeyError, ValueError, TypeError) as error:
        raise AuditError('invalid_export', 'Actual decoded frame counts are missing') from error
    if video_frames <= 0 or audio_frames <= 0 or abs(video_frames/30-expected)>.15:
        raise AuditError('invalid_export', 'Decoded video/audio frames disagree with expected duration')
    _decode(path)
    return {'duration':duration,'video_frames':video_frames,'audio_frames':audio_frames,
            'width':video['width'],'height':video['height'],'codec':'h264','audio_codec':'aac'}


def _srt(path):
    text = path.read_text('utf-8-sig').replace('\r\n','\n').strip()
    if not text:
        return []
    def clock(value):
        match = re.fullmatch(r'(\d+):([0-5]\d):([0-5]\d),(\d{3})',value)
        if not match:
            raise AuditError('invalid_srt','Invalid subtitle clock')
        h,m,s,ms = map(int,match.groups())
        return h*3600+m*60+s+ms/1000
    result = []
    for number,block in enumerate(re.split(r'\n\s*\n',text),1):
        lines = block.splitlines()
        if len(lines)<3 or lines[0] != str(number) or len(lines[1].split(' --> '))!=2:
            raise AuditError('invalid_srt','Invalid subtitle sequence/format')
        start,end = map(clock,lines[1].split(' --> '))
        if start>=end or result and start < result[-1]['start']:
            raise AuditError('invalid_srt','Invalid subtitle timing/order')
        result.append({'start':start,'end':end,'text':' '.join(lines[2:])})
    return result


def verify_subtitles(part, words, path):
    """Reconstruct the montage word clock independently of saved subtitle text."""
    remapped, offset = [], 0.0
    for cut in part['cuts']:
        for word in words:
            if word['end']<=cut['start'] or word['start']>=cut['end']:
                continue
            if word['start'] < cut['start']-.002 or word['end'] > cut['end']+.002:
                raise AuditError('cut_asr_word','Source cut intersects an original ASR word')
            remapped.append({'start':offset+max(word['start'],cut['start'])-cut['start'],
                'end':offset+min(word['end'],cut['end'])-cut['start'],'text':word['text']})
        offset += cut['end']-cut['start']
    actual = _srt(path)
    saved = part.get('subtitles')
    if not isinstance(saved,list) or len(saved)!=len(actual):
        raise AuditError('subtitle_plan_mismatch','SRT and registered plan cues disagree')
    cursor = 0
    for cue,original in zip(actual,saved):
        if (abs(cue['start']-original['start'])>.002 or abs(cue['end']-original['end'])>.002
                or _tokens(cue['text'])!=_tokens(original['text']) or cue['end']>part['duration']+.002):
            raise AuditError('subtitle_plan_mismatch','SRT cue differs from the registered plan')
        text, count = [], 0
        while cursor+count < len(remapped) and len(text)<len(_tokens(cue['text'])):
            text.extend(_tokens(remapped[cursor+count]['text'])); count+=1
        group = remapped[cursor:cursor+count]
        if (not group or text!=_tokens(cue['text']) or abs(cue['start']-group[0]['start'])>.002
                or abs(cue['end']-group[-1]['end'])>.002):
            raise AuditError('subtitle_asr_mismatch','SRT does not follow retained original ASR words/times')
        cursor += count
    if cursor!=len(remapped):
        raise AuditError('subtitle_asr_mismatch','Retained original ASR words are absent from SRT')
    return {'cues':len(actual),'retained_words':len(remapped)}


def _proof(record, unit, words):
    if (not isinstance(record,dict) or record.get('unit')!=unit['id'] or record.get('decision')!='keep'
            or record.get('kind') not in POSITIVE or not _number(record.get('confidence'))
            or not .9<=record['confidence']<=1 or not isinstance(record.get('evidence'),str)
            or len(record['evidence'].strip())<12 or not isinstance(record.get('checkpoint'),str)
            or not record['checkpoint']):
        raise AuditError('invalid_source_proof','Retained source unit lacks a concrete accepted proof')
    a,b = record.get('view_start',unit['start']),record.get('view_end',unit['end'])
    if not _number(a) or not _number(b):
        raise AuditError('invalid_source_proof','Proof view must have finite original bounds')
    start, end = max(unit['start'],a), min(unit['end'],b)
    bounds = _ranges([{'start':start,'end':end}])
    indices,times,count = record.get('frame_indices',[]),record.get('frame_times',[]),record.get('frame_count')
    if (not isinstance(indices,list) or len(indices)!=len(set(indices))
            or any(type(i) is not int or i<1 or type(count) is not int or i>count for i in indices)
            or not isinstance(times,list) or len(times)!=len(indices)
            or any(not _number(t) or not start<=t<end for t in times)):
        raise AuditError('invalid_source_proof','Proof indices/times do not belong to the CURRENT source unit/view')
    quote = record.get('speech_quote','')
    actual = ' '.join(w['text'] for w in words if start<=w['start'] and w['end']<=end)
    if not isinstance(quote,str) or quote and not _contains(actual,quote) or not (indices or quote.strip()):
        raise AuditError('invalid_source_proof','Proof has no bounded original frame/ASR anchor')
    if record['kind'] not in {'causal_dialogue','response'} and not indices:
        raise AuditError('invalid_source_proof','A visual selection reason needs original CURRENT frame proof')
    return bounds


def _ref(value, known):
    if not isinstance(value,dict) or set(value)!={'event','unit'} or any(not isinstance(v,str) for v in value.values()):
        raise AuditError('invalid_source_reference','Malformed event/unit reference')
    key = value['event'],value['unit']
    if key not in known:
        raise AuditError('foreign_source_reference','Unknown source event/unit pair')
    return key


def _stable(value):
    if isinstance(value,dict):
        return {k:_stable(v) for k,v in value.items() if k not in ('cache_hit','visual_cache_hit')}
    if isinstance(value,list):
        return [_stable(v) for v in value]
    return value


def _proof_id(ref, record):
    data = json.dumps({'ref':ref,'record':_stable(record)},ensure_ascii=False,sort_keys=True,
                      separators=(',',':'),allow_nan=False).encode()
    return 'proof_'+hashlib.sha256(data).hexdigest()[:24]


def _inherited_support(items, known, words):
    if not isinstance(items,list) or not items:
        raise AuditError('missing_inherited_support','No original source proofs support this semantic relation','unresolved')
    supported = set()
    for item in items:
        event,unit = known[_ref(item.get('ref'),known)]
        record = next((p for p in event.get('unit_evidence',[]) if
                       _proof_id(item['ref'],p)==item.get('proof')),None)
        if record is None:
            raise AuditError('foreign_inherited_proof','Semantic relation cites an unknown original source proof')
        bounds = _proof(record,unit,words)
        quote = item.get('quote','')
        actual = ' '.join(w['text'] for w in words if bounds[0]['start']<=w['start'] and w['end']<=bounds[0]['end'])
        if not isinstance(quote,str) or quote and not _contains(actual,quote) or not quote and not record.get('frame_indices'):
            raise AuditError('foreign_inherited_quote','Semantic quote lies outside its specific cited original proof')
        supported.add((event['id'],unit['id']))
    return supported


def _structure_pass(structure, requests, responses):
    if (structure.get('status')!='accepted' or any(not _number(structure.get(k))
            or not .9<=structure[k]<=1 for k in ('understanding_confidence','structure_confidence'))):
        raise AuditError('unverified_structure_pass','Original structure confidence/status is insufficient')
    history = structure.get('history',[])
    actual = [response for request,response in zip(requests,responses)
              if 'arcs' in (request.get('schema') or {}).get('properties',{})]
    if (not actual or not history or any(row.get('status')!='accepted' or row.get('decision') not in actual
                                        for row in history)):
        raise AuditError('missing_structure_query','Accepted structure history has no matching actual recorded model pass','unresolved')


def _endings(analysis, plan, known, words, responses, requests):
    """A generic part-boundary label or reaching EOF is not semantic closure."""
    structure = analysis.get('story_structure') or {}
    arcs = structure.get('arcs',[]) if structure.get('status')=='accepted' else []
    endings = [ending for event in analysis.get('events',[]) for ending in event.get('part_endings',[])]
    endings.extend(analysis.get('part_endings',[]))
    retained = [cut for part in plan['parts'] for cut in part['cuts']]
    speech = [{**s,'id':f'r{i:04}'} for i,s in enumerate(analysis.get('transcript',{}).get('segments',[]))
              if _covers(retained,[s])]
    decisions = [decision for response in responses for decision in response.get('decisions',[])
                 if isinstance(decision,dict)]
    verified = []
    for part in plan['parts']:
        end = part['cuts'][-1]['end']
        candidates = [arc for arc in arcs if _number(arc.get('end')) and abs(arc['end']-end)<=.002]
        accepted = None
        for arc in candidates:
            _structure_pass(structure,requests,responses)
            proof = arc.get('verification') or {}
            refs = arc.get('source_unit_refs',[])
            if (arc.get('complete_ending') is not True or arc.get('ending_verified') is not True
                    or arc.get('uncertain') is not False or proof.get('supported') is not True
                    or not _number(proof.get('confidence')) or not .9<=proof['confidence']<=1 or not refs):
                continue
            scoped = {_ref(ref,known) for ref in refs}
            closing = _ref(arc.get('closing_unit'),known)
            if closing not in scoped or closing not in _inherited_support(proof.get('proofs'),known,words):
                raise AuditError('unsupported_arc_closure','Arc closing unit is not supported by its original source proofs')
            if not _covers([known[key][1] for key in scoped],arc.get('source_ranges',[])):
                raise AuditError('foreign_arc_ranges','Arc source geometry leaves its original units')
            closing_pieces = [r for r in arc['source_ranges'] if _overlap([known[closing][1]],r)]
            if not closing_pieces or not _covers(part['cuts'],closing_pieces):
                continue
            accepted={'part':part['index'],'source_end':end,'source':'inferred_arc','arc':arc['id']}
            break
        if accepted is None:
            for ending in endings:
                proof = ending.get('verification') or {}
                if (not _number(ending.get('time')) or abs(ending['time']-end)>.002
                        or proof.get('supported') is not True or not _number(proof.get('confidence'))
                        or not .9<=proof['confidence']<=1 or not _number(ending.get('confidence'))
                        or not .9<=ending['confidence']<=1 or not proof.get('evidence')):
                    continue
                before = [s for s in speech if s['end']<=end+.002]
                after = [s for s in speech if s['start']>=end-.002]
                if (proof.get('boundary')!=ending.get('id') or not ending.get('id')
                        or proof.get('last_reply')!=(before[-1]['id'] if before else 'none')
                        or proof.get('next_reply')!=(after[0]['id'] if after else 'none')):
                    raise AuditError('foreign_ending_context','Original ending proof cites a foreign boundary/BEFORE/AFTER ASR reply')
                if proof not in decisions:
                    raise AuditError('missing_actual_ending_verification','Original part ending lacks an actual recorded verifier response','unresolved')
                accepted={'part':part['index'],'source_end':end,'source':'verified_part_ending'}
                break
        if accepted is None:
            raise AuditError('missing_original_semantic_ending',
                f'Part {part["index"]}: original accepted arc closing or verified part_endings is required; EOF/default label is insufficient',
                'unresolved')
        verified.append(accepted)
    return verified


def _review(manifest, scenario, source, original):
    if manifest is None:
        adjacent = source.parent/'review/groundtruth.json'
        if adjacent.is_file():
            return {'facts':_read(adjacent),'source':str(source),'source_sha256':original['source_sha256']}
        raise AuditError('missing_review_facts','No associated evaluator review manifest supplied','unresolved')
    data = _read(manifest)
    rows = data.get('records',data.get('cases',[])) if isinstance(data,dict) else data
    if not isinstance(rows,list):
        raise AuditError('invalid_review_manifest','Review records/cases must be a list')
    rows = [row for row in rows if isinstance(row,dict) and row.get('scenario',row.get('case'))==scenario]
    if len(rows)!=1:
        raise AuditError('missing_review_facts','Review must contain exactly one requested scenario','unresolved')
    row = dict(rows[0])
    if (_workspace(row.get('source',''))!=source or row.get('source_sha256')!=original['source_sha256']
            or row.get('input_manifest_sha256',original['input_manifest_sha256'])!=original['input_manifest_sha256']):
        raise AuditError('review_source_mismatch','Review facts do not identify these original input bytes')
    row['facts'] = row.get('facts') or (_read(row['groundtruth']) if row.get('groundtruth') else {})
    return row


def _pair_checks(analysis, parts, facts, known):
    left = _span(facts.get('question_words',facts.get('explanation_words')))
    right = _span(facts.get('answer_words',facts.get('dependent_question_words')))
    dialogue = analysis.get('dialogue_relations') or {}
    if dialogue.get('status')!='accepted':
        raise AuditError('missing_dialogue_pass','Accepted actual dialogue-relation pass is missing','unresolved')
    if any(not _number(dialogue.get(k)) or not .9<=dialogue[k]<=1
           for k in ('understanding_confidence','relation_confidence')):
        raise AuditError('unverified_dialogue_pair','Actual dialogue pass confidence is insufficient')
    pairs = [p for p in dialogue.get('pairs',[]) if p.get('status')=='confirmed' and p.get('requires_answer') is True
             and _number(p.get('confidence')) and .9<=p['confidence']<=1
             and _overlap(p.get('question_ranges',[]),left) and _overlap(p.get('answer_ranges',[]),right)]
    if not pairs:
        raise AuditError('missing_confirmed_pair','Reviewed cause/question-response relation was not actually inferred','unresolved')
    for pair in pairs:
        for side in ('question','answer'):
            refs = pair.get(side+'_refs',[])
            if not refs:
                raise AuditError('invalid_source_reference','Confirmed dialogue endpoints need source refs')
            bounds = [known[_ref(ref,known)][1] for ref in refs]
            if not _covers(bounds,pair[side+'_ranges']):
                raise AuditError('foreign_dialogue_ranges','Dialogue interval escapes its actual source refs')
            word_refs = pair.get(side+'_asr_refs',[])
            original = analysis['transcript']
            rows,seen = [],set()
            for word_ref in word_refs:
                container,index = word_ref.get('container'),word_ref.get('index')
                if (container not in ('words','segments') or type(index) is not int or index<0
                        or index>=len(original.get(container,[])) or (container,index) in seen):
                    raise AuditError('foreign_dialogue_asr_reference','Confirmed dialogue cites an unknown/duplicate original ASR row')
                rows.append(original[container][index]); seen.add((container,index))
            if (not rows or len(pair[side+'_ranges'])!=1
                    or abs(pair[side+'_ranges'][0]['start']-min(r['start'] for r in rows))>.002
                    or abs(pair[side+'_ranges'][0]['end']-max(r['end'] for r in rows))>.002):
                raise AuditError('foreign_dialogue_asr_reference','Confirmed endpoint times differ from exact original ASR rows')
        together = [part for part in parts if _covers(part['cuts'],[*pair['question_ranges'],*pair['answer_ranges']])]
        if not together:
            raise AuditError('split_required_dialogue','Original required question/answer is omitted or split across parts')
    return {'confirmed_pairs':len(pairs),'question':left,'answer':right}


def _g_asr(review, manifest, transcript, original):
    if not transcript.get('words') or any('?' in str(row.get('text',''))
            for key in ('words','segments') for row in transcript.get(key,[])):
        raise AuditError('g_not_unpunctuated','G requires ordinary source ASR without question marks','unresolved')
    origin_path = review.get('asr_origin')
    if not origin_path:
        return {'mode':'provided_ordinary_ASR' if 'transcript' in manifest else 'production_ASR',
                'origin_transformation_verified':False}
    provenance = _read(origin_path)
    origin = _workspace(provenance['origin'])
    if provenance.get('transformation')!='remove_question_mark_only' or _sha(origin)!=provenance.get('origin_sha256'):
        raise AuditError('asr_origin_mismatch','Reviewed original automatic-ASR bytes/transformation do not match')
    original_asr = _read(origin)
    def transformed(value):
        if isinstance(value,dict):
            return {k:v.replace('?','') if k=='text' and isinstance(v,str) else transformed(v) for k,v in value.items()}
        if isinstance(value,list):
            return [transformed(v) for v in value]
        return value
    # The ordinary provided ASR deliberately omits automatic repair/device logs.
    # Their removal is not a change to source speech; every original speech row
    # including its clocks, probability and speaker must remain exact.
    if any(transformed(original_asr.get(key))!=transcript.get(key) for key in ('words','segments')):
        raise AuditError('asr_transformation_changed_words','G changed original ASR words/times/probabilities beyond removing question marks')
    origin_input = _read(origin.parent/'original-inputs.json')
    if origin_input.get('source_sha256')!=original['source_sha256'] or origin_input.get('transcript_sha256') is not None:
        raise AuditError('asr_origin_mismatch','Original ASR was not automatically decoded from this source-only input')
    return {'mode':'provided_ordinary_ASR','origin_transformation_verified':True}


def _scenario(scenario, review, analysis, plan, gate, responses, requests, duration, job, known):
    facts, parts = review['facts'],plan['parts']
    retained = [cut for part in parts for cut in part['cuts']]
    if scenario in STAGE1:
        if review.get('fixture',STAGE1[scenario])!=STAGE1[scenario]:
            raise AuditError('review_scenario_mismatch','Wrong reviewed source fixture for the requested scenario')
        from scripts.run_raw_video_quality import evaluate_stage1
        scenes = analysis.get('scenes') or _read(job/'scenes.json')
        perception = _read(job/'media-evidence.json')
        source = _read(job/'original-inputs.json')
        if perception.get('source',{}).get('sha256')!=source['source_sha256']:
            raise AuditError('perception_source_mismatch','Measured motion belongs to a different original video')
        for scene in scenes:
            for row in scene.get('evidence',{}).get('boundary_decisions',[]):
                proof = row.get('boundary_verification') or {}
                if proof.get('accepted') is not True:
                    continue
                if (not _number(row.get('time')) or not 0<=row['time']<=duration
                        or not _number(proof.get('confidence')) or not .88<=proof['confidence']<=1
                        or proof.get('uncertain') is not False
                        or proof.get('source')!='semantic_boundary_verification'
                        or any(type(proof[k]) is not bool for k in ('same_location','location_changed',
                            'physical_transition','character_state_changed','object_state_changed') if k in proof)):
                    raise AuditError('invalid_boundary_proof','Accepted boundary has malformed source/confidence/state evidence')
        result = evaluate_stage1(STAGE1[scenario], {'scenes':scenes,
            'shots':_read(job/'shots.json'),'perception':perception,
            'probe':{'duration':duration},'actual_model_requests':len(requests)})
        if not result['passed']:
            raise AuditError('scenario_criteria_failed',json.dumps(result['checks'],ensure_ascii=False))
        if scenario=='C':
            proofs = [r.get('boundary_verification') or {} for s in scenes
                      for r in s.get('evidence',{}).get('boundary_decisions',[]) if 4<=r.get('time',-1)<=8]
            if not any(p.get('accepted') is True and p.get('same_location') is True
                       and p.get('location_changed') is False and (p.get('character_state_changed') or p.get('object_state_changed'))
                       for p in proofs):
                raise AuditError('same_room_state_not_verified','Binding/state change lacks accepted unchanged-room evidence')
        if scenario in ('E','F'):
            motion = perception.get('motion',{})
            if (motion.get('evidence')!='source_optical_flow' or motion.get('available') is not True
                    or not _number(motion.get('measurement_coverage')) or motion['measurement_coverage']<.35):
                raise AuditError('missing_measured_motion','Camera cuts cannot substitute for actual source optical-flow evidence','unresolved')
        if scenario in ('A','C'):
            # Evaluation-only geometry from tests/raw_video_fixtures._render:
            # A wrists close/rope appears at 5–6.5, then transport at 8–11;
            # C hands close and rope appears at 4–7 in the same room.
            required=([('binding',{'start':5.,'end':6.5}),('enter_vehicle',{'start':8.,'end':11.})]
                      if scenario=='A' else [('binding',{'start':4.,'end':7.})])
            proofs=[]
            for event,unit in known.values():
                for record in event.get('unit_evidence',[]):
                    if (record.get('unit')!=unit['id'] or record.get('decision')!='keep'
                            or record.get('kind') not in ('physical_action','state_transition')):
                        continue
                    bounds=_proof(record,unit,analysis['transcript']['words'])
                    proofs.append((bounds,record.get('frame_times',[])))
            for kind,interval in required:
                if not _covers(retained,[interval]):
                    raise AuditError('physical_transition_not_retained',
                        f'{scenario}: exported source cuts omit the reviewed {kind} action {interval}')
                eligible=[r for bounds,times in proofs for r in bounds
                          if any(interval['start']<=t<interval['end'] for t in times)]
                if not _covers(eligible,[interval]):
                    raise AuditError('missing_retained_physical_proof',
                        f'{scenario}: {kind} lacks specific original CURRENT physical frame proof')
                result['checks'].append({'name':'Export retains reviewed '+kind+' action with original frame proof',
                                         'passed':True,'source_range':interval})
        return result
    if scenario=='G':
        return _pair_checks(analysis,parts,facts,known)
    if scenario=='B':
        explanation, dependent = _span(facts.get('explanation_words')),_span(facts.get('dependent_question_words'))
        words = analysis['transcript']['words']
        question = [w for w in words if _overlap([w],dependent)]
        cause = [w for w in words if _overlap([w],explanation)]
        exercised = [part for part in parts if question and _covers(part['cuts'],question)]
        if not exercised:
            raise AuditError('not_exercised','Reviewed dependent arrival/question was not retained','unresolved')
        missing = [part for part in exercised if not cause or not _covers(part['cuts'],cause)]
        if missing:
            structure = analysis.get('story_structure') or {}
            _structure_pass(structure,requests,responses)
            relations = [r for r in structure.get('relations',[]) if r.get('type',r.get('kind')) in ('cause','state_transition')]
            justified = set()
            for relation in relations:
                if not _number(relation.get('confidence')) or not .9<=relation['confidence']<=1:
                    continue
                left,right = _ref(relation.get('from'),known),_ref(relation.get('to'),known)
                if not _overlap([known[right][1]],dependent):
                    continue
                if not {left,right}<=_inherited_support(relation.get('support'),known,words):
                    continue
                justified.update(part['index'] for part in missing
                    if _covers(part['cuts'],[known[left][1],known[right][1]]))
            if any(part['index'] not in justified for part in missing):
                raise AuditError('missing_prior_explanation','Dependent question lacks retained explanation or supported original causal bridge')
        return {'exercised_parts':[p['index'] for p in exercised],'explanation':explanation,'dependent':dependent}
    if scenario=='H':
        initial = [(request,response) for request,response in zip(requests,responses)
                   if 'CURRENT SCENE' in request.get('prompt','') and 'initial_analysis' not in request['prompt']
                   and 'keep_units' in (request.get('schema') or {}).get('properties',{})]
        doubtful = [r for _,r in initial if r.get('uncertain') is True or any(
                    _number(r.get(k)) and r[k]<.6 for k in ('semantic_confidence','visual_confidence','context_confidence'))]
        if not doubtful:
            raise AuditError('not_exercised','No genuine recorded initial-model uncertainty/low confidence','unresolved')
        fresh = [request for request in requests if 'initial_analysis' in request.get('prompt','')
                 or 'unit_evidence' in (request.get('schema') or {}).get('properties',{})]
        if not fresh:
            raise AuditError('missing_recovery_query','No actual fresh recovery/adjudication request','unresolved')
        if sum(c['end']-c['start'] for c in retained)>=duration-.002:
            raise AuditError('uncertainty_keep_all','Difficult source retained whole instead of bounded evidenced selection')
        return {'initial_doubtful_responses':len(doubtful),'fresh_requests':len(fresh)}
    if scenario=='I':
        neutral = _span(facts.get('neutral_scenery'))
        reaction = _span(facts.get('expression_change',facts.get('silent_reaction')))
        if _overlap(retained,neutral):
            raise AuditError('neutral_scenery_retained','Reviewed neutral prefix remains in the exported cuts')
        reaction_proofs = [row for row in gate['evidence_chain'] if _overlap(row['ranges'],reaction)
            and any(p['kind'] in {'character_reaction','emotional_pause','comedic_payoff'} for p in row['source_proofs'])]
        if not reaction_proofs:
            raise AuditError('reaction_missing','Reviewed silent reaction lacks retained concrete CURRENT proof')
        return {'reaction_refs':[row['ref'] for row in reaction_proofs],'neutral':neutral}
    if scenario=='J':
        stories = facts.get('observed_stories')
        structure = analysis.get('story_structure') or {}
        arcs = structure.get('arcs',[])
        if not isinstance(stories,list) or len(stories)!=5:
            raise AuditError('missing_review_facts','Five reviewed source stories are required','unresolved')
        if structure.get('status')!='accepted' or len(arcs)!=5:
            raise AuditError('five_arcs_not_inferred','Actual accepted structure pass did not infer five arcs')
        _structure_pass(structure,requests,responses)
        if analysis.get('preferred_part_count')!=6 or len(parts)!=5:
            raise AuditError('natural_part_count','Preferred six must produce five actual complete parts for this source')
        if not any('arcs' in (r.get('schema') or {}).get('properties',{}) for r in requests):
            raise AuditError('missing_structure_query','No actual recorded structure model pass','unresolved')
        for arc,story in zip(sorted(arcs,key=lambda a:a['start']),stories):
            verification = arc.get('verification') or {}
            refs = arc.get('source_unit_refs',[])
            if (not refs or arc.get('complete_ending') is not True or arc.get('ending_verified') is not True
                    or arc.get('uncertain') is not False or verification.get('supported') is not True
                    or not _number(verification.get('confidence')) or not .9<=verification['confidence']<=1):
                raise AuditError('unverified_arc','Inferred source arc has no accepted complete ending')
            bounds = _span(story.get('bounds'))
            units = [known[_ref(ref,known)][1] for ref in refs]
            if (not _covers(units,arc.get('source_ranges',[])) or arc['start']<bounds['start']-.002
                    or arc['end']>bounds['end']+.002):
                raise AuditError('foreign_arc_ranges','Inferred arc escapes original reviewed story/source units')
            closing = _ref(arc.get('closing_unit'),known)
            if closing not in {_ref(ref,known) for ref in refs} or closing not in _inherited_support(
                    verification.get('proofs'),known,analysis['transcript']['words']):
                raise AuditError('unsupported_arc_closure','Arc closing lacks its specific original inherited proof')
            if (not arc.get('source_ranges') or not _number(arc.get('start')) or not _number(arc.get('end'))
                    or abs(arc['source_ranges'][0]['start']-arc['start'])>.002
                    or abs(arc['source_ranges'][-1]['end']-arc['end'])>.002):
                raise AuditError('foreign_arc_ranges','Arc endpoints differ from its exact source-unit pieces')
            if not any(_covers(part['cuts'],arc['source_ranges']) for part in parts):
                raise AuditError('split_closed_arc','A reviewed closed arc is not retained in one complete part')
        return {'actual_arcs':5,'preferred_parts':6,'final_parts':5}
    raise AuditError('unknown_scenario','Unsupported scenario')


def verify_job(job_dir, scenario, review_manifest=None):
    """Evaluate registered completed artifacts; never mutate the job or call a model."""
    report = {'version':VERSION,'scenario':scenario,'status':'unresolved','checks':[],'exports':[],
              'limitations':['read_only_artifact_audit_not_independent_VLM_execution_authentication',
                  'semantic_criteria_depend_on_evaluator_review_and_recorded_source_proofs',
                  'model_confidence_is_self_reported','audio_decode_is_not_independent_speech_ASR_accuracy']}
    def checked(code, action):
        result = action()
        report['checks'].append({'code':code,'status':'passed'})
        return result
    try:
        if scenario not in 'ABCDEFGHIJ' or len(scenario)!=1:
            raise AuditError('unknown_scenario','Scenario must be A..J')
        job = _workspace(job_dir)
        report['job_dir'] = str(job)
        outcome = _read(job/'observed-outcome.json')
        outcome_sha = _sha(job/'observed-outcome.json')
        if outcome.get('mode')!='production_render' or outcome.get('complete') is not True:
            raise AuditError('incomplete_production_render','Evaluate only a completed production_render','unresolved')
        report['checks'].append({'code':'completed_production_render','status':'passed'})
        if outcome.get('pipeline_code_stable') is not True:
            raise AuditError('unstable_pipeline_code','A frozen final-proof run with pipeline_code_stable=true is required','unresolved')
        starting_identity,final_identity = _read(job/'observer-code-identity.json'),_read(job/'observer-code-identity-final.json')
        if not isinstance(starting_identity,dict) or not starting_identity or not isinstance(final_identity,dict):
            raise AuditError('missing_pipeline_code_identity','Nonempty original/final observer code identities are required','unresolved')
        if starting_identity!=final_identity:
            raise AuditError('pipeline_code_changed','Original/final observer code identities differ')
        report['checks'].append({'code':'frozen_pipeline_code','status':'passed'})
        original = _read(job/'original-inputs.json')
        source = _workspace(original['source'])
        manifest_path = source.parent/'input.json'
        locations_path = job/'observer-input-locations.json'
        locations = _read(locations_path) if locations_path.is_file() else None
        if locations is not None:
            manifest_path = _workspace(locations['input'])
        elif review_manifest:
            # A source may be registered by a separate input manifest.
            data = _read(review_manifest)
            rows = data.get('records',data.get('cases',[])) if isinstance(data,dict) else data
            match = [r for r in rows if r.get('scenario',r.get('case'))==scenario] if isinstance(rows,list) else []
            if len(match)==1 and match[0].get('input'):
                manifest_path = _workspace(match[0]['input'])
        manifest = _read(manifest_path)
        if (not isinstance(manifest,dict) or set(manifest) not in ({'source'},{'source','transcript'})
                or _workspace(manifest['source'])!=source or _read(job/'source.json').get('path')!=str(source)
                or _sha(source)!=original.get('source_sha256')
                or _sha(manifest_path)!=original.get('input_manifest_sha256')):
            raise AuditError('source_input_mismatch','Source-only input bytes/SHA do not match the observed production run')
        if locations is not None and locations.get('transcript')!=manifest.get('transcript'):
            raise AuditError('transcript_input_mismatch','Observed original ASR location differs from the source-only input')
        if 'transcript' in manifest:
            if _sha(manifest['transcript'])!=original.get('transcript_sha256'):
                raise AuditError('transcript_input_mismatch','Supplied ordinary ASR bytes changed')
        elif original.get('transcript_sha256') is not None:
            raise AuditError('transcript_input_mismatch','Source-only run carries unexpected supplied ASR')
        report['checks'].append({'code':'original_input_sha','status':'passed'})
        analysis = _read(job/'actual-analysis.json')
        final = _read(job/'analysis-final.json')
        if analysis!=final:
            raise AuditError('final_analysis_mismatch','Observer analysis differs from actual final render analysis')
        job_transcript = _read(job/'transcript.json')
        words = job_transcript.get('words',[])
        if analysis.get('transcript',{}).get('words')!=words or not isinstance(words,list):
            raise AuditError('source_asr_mismatch','Final analysis does not use the original job ASR word clock')
        source_info = _probe(source)
        duration = float(source_info['format']['duration'])
        if 'transcript' in manifest:
            from app.provided_asr import validate_provided_transcript
            supplied = _read(manifest['transcript'])
            try:
                validate_provided_transcript(supplied,{'transcript_source_sha256':original['source_sha256']},
                                             original['source_sha256'],duration)
            except ValueError as error:
                raise AuditError('invalid_provided_asr','Provided input contains nonordinary fields or invalid source speech') from error
            if any(supplied.get(key)!=job_transcript.get(key) for key in ('words','segments')):
                raise AuditError('transcript_input_mismatch','Job ASR speech rows differ from the original hashed provided ASR')
        if any(not isinstance(w,dict) or not _number(w.get('start')) or not _number(w.get('end'))
               or not 0<=w['start']<w['end']<=duration+.002 or not isinstance(w.get('text'),str) for w in words):
            raise AuditError('invalid_source_asr','ASR words have invalid original source geometry')
        request_paths = sorted((job/'actual-model').glob('request-*.json'))
        if not request_paths or type(outcome.get('actual_model_requests')) is not int or outcome['actual_model_requests']!=len(request_paths):
            raise AuditError('missing_actual_requests','Completed production observer lacks actual request records','unresolved')
        sessions = _read(job/'observed-sessions.json')
        if not isinstance(sessions,list) or not sessions or any(not s.get('model') or not s.get('projector') for s in sessions):
            raise AuditError('missing_model_sessions','Actual provider session provenance is missing','unresolved')
        requests,responses = [],[]
        for path in request_paths:
            request = _read(path)
            number = int(path.stem.split('-')[-1])
            if (type(request.get('request')) is not int or request['request']!=number
                    or not isinstance(request.get('prompt'),str) or not request['prompt'].strip()
                    or type(request.get('max_tokens')) is not int or request['max_tokens']<=0
                    or type(request.get('thinking')) is not bool or not isinstance(request.get('images'),list)):
                raise AuditError('invalid_actual_request','Recorded request ID/body does not match the actual model artifact')
            if not any((request.get('model'),request.get('projector'))==(s['model'],s['projector']) for s in sessions):
                raise AuditError('model_session_mismatch','Request does not match an observed genuine provider session')
            for image in request.get('images',[]):
                location = _workspace(image['path'])
                if not location.is_relative_to(job) or _sha(location)!=image['sha256']:
                    raise AuditError('request_image_mismatch','Recorded original-source image was changed/borrowed')
            response = _read(path.with_name(path.name.replace('request-','response-',1)))
            if isinstance(response.get('response'),dict):
                requests.append(request); responses.append(response['response'])
        if not requests:
            raise AuditError('missing_successful_model_pass','No successful genuine recorded model response','unresolved')
        report['checks'].append({'code':'actual_model_artifacts','status':'passed','successful_requests':len(requests)})
        gate = _read(job/'final_quality_gate.json')
        if (gate.get('status')!='passed' or gate.get('problems')!=[] or gate.get('phase')!='before_render'
                or outcome.get('quality_gate')!=gate):
            raise AuditError('quality_gate_not_passed','Final source-proof gate is missing, unresolved, or differs from observer outcome')
        plan = _read(job/'output/plan.json')
        if _read(job/'plan.json')!=plan or not isinstance(plan.get('parts'),list) or not plan['parts']:
            raise AuditError('registered_plan_mismatch','Registered output plan differs from actual final plan')
        known,events = {},{}
        for event in analysis.get('events',[]):
            if event['id'] in events:
                raise AuditError('duplicate_source_event','Repeated original event ID')
            if (not _number(event.get('start')) or not _number(event.get('end'))
                    or not 0<=event['start']<event['end']<=duration+.002):
                raise AuditError('invalid_source_event','Original event geometry escapes the decoded source')
            events[event['id']]=event
            for unit in event.get('units',[]):
                key = event['id'],unit['id']
                if (key in known or not _number(unit.get('start')) or not _number(unit.get('end'))
                        or not event['start']<=unit['start']<unit['end']<=event['end']):
                    raise AuditError('invalid_source_unit','Repeated or out-of-parent source unit')
                known[key]=(event,unit)
        expected_names, retained = [],[]
        for index,part in enumerate(plan['parts'],1):
            if part.get('index')!=index or not _number(part.get('duration')) or not part.get('cuts'):
                raise AuditError('invalid_registered_part','Invalid final part index/duration/cuts')
            cuts = part['cuts']; _ranges(cuts)
            if (any(c['end']>duration+.002 for c in cuts)
                    or any(a['end']>b['start']+.002 for a,b in zip(cuts,cuts[1:]))
                    or abs(sum(c['end']-c['start'] for c in cuts)-part['duration'])>.002):
                raise AuditError('invalid_registered_part','Part source geometry/duration is inconsistent')
            if any(w['start']+.002<c[side]<w['end']-.002 for c in cuts for side in ('start','end') for w in words):
                raise AuditError('cut_asr_word','Actual final cuts truncate original source ASR words')
            retained.extend(cuts)
            expected_names.extend([f'part_{index:03d}.mp4',f'part_{index:03d}.srt'])
        if (not isinstance(outcome.get('outputs'),list) or len(outcome['outputs'])!=len(expected_names)
                or set(outcome['outputs'])!=set(expected_names)
                or set(outcome.get('export_sha256',{}))!=set(expected_names)):
            raise AuditError('unregistered_exports','Observer exports must match every registered MP4/SRT pair exactly')
        actual_names = {p.name for p in (job/'output').iterdir() if p.suffix.lower() in ('.mp4','.srt')}
        if actual_names!=set(expected_names):
            raise AuditError('unregistered_exports','Output directory contains missing/stale unregistered MP4/SRT artifacts')
        from app.source_roles import confirmed_exclusions
        exclusions = [r for event in events.values() for r in confirmed_exclusions(event)]
        if any(_overlap(retained,span) for span in exclusions):
            raise AuditError('retained_confirmed_exclusion','Exported source cuts retain an independently confirmed exclusion')
        chain = gate.get('evidence_chain')
        if not isinstance(chain,list) or not chain:
            raise AuditError('missing_evidence_chain','Final source evidence chain is missing','unresolved')
        proven = []
        for row in chain:
            key = _ref(row.get('ref'),known)
            event,unit = known[key]
            if any(event.get(flag) for flag in UNRESOLVED_FLAGS) or event.get('fallback'):
                raise AuditError('unresolved_retained_event','Retained original event remains uncertain or uses generic fallback')
            if (event.get('selection_status')!='accepted' or event.get('understanding_status')=='unresolved'
                    or any(not _number(event.get(k)) or not .9<=event[k]<=1
                           for k in ('understanding_confidence','selection_confidence'))
                    or event.get('protected_atmosphere_units') or event.get('protected_atmosphere_ranges')):
                raise AuditError('unresolved_retained_event','Original source selection lacks accepted specific confidence/provenance')
            pieces = _ranges(row.get('ranges',[]))
            if not pieces or not _covers([unit],pieces) or not _covers(retained,pieces):
                raise AuditError('foreign_evidence_ranges','Evidence chain ranges leave their original unit/exported cuts')
            proofs = row.get('source_proofs',[])
            if not proofs or any(p not in event.get('unit_evidence',[]) for p in proofs):
                raise AuditError('foreign_source_proof','Evidence chain proof is absent from its actual original event')
            bounds = [span for record in proofs for span in _proof(record,unit,words)]
            if not _covers(bounds,pieces):
                raise AuditError('incomplete_source_proof','Accepted original source proofs do not cover retained unit pieces')
            if any(b.get('uncertain') or b.get('reason')=='endpoint_context'
                   or any(p.get('kind')=='endpoint_context' for p in b.get('evidence',[]) if isinstance(p,dict))
                   for b in row.get('continuity_reasons',[])):
                raise AuditError('endpoint_fallback','Unverified endpoint context cannot justify exported source retention')
            proven.extend(pieces)
        if not _covers(proven,retained):
            raise AuditError('unexplained_retained_ranges','Final exported cuts exceed specific original-source evidence')
        report['checks'].append({'code':'source_evidence_chain','status':'passed','refs':len(chain)})
        report['semantic_endings'] = checked('original_verified_semantic_endings',lambda:
            _endings(analysis,plan,known,words,responses,requests))
        for part in plan['parts']:
            basename = f'part_{part["index"]:03d}'
            mp4,srt = job/'output'/(basename+'.mp4'),job/'output'/(basename+'.srt')
            for path in (mp4,srt):
                if path.is_symlink() or _sha(path)!=outcome['export_sha256'][path.name]:
                    raise AuditError('export_hash_mismatch','Registered export bytes changed or are linked elsewhere')
            media = _export_media(mp4,part['duration'])
            captions = verify_subtitles(part,words,srt)
            report['exports'].append({'mp4':str(mp4),'srt':str(srt),**media,**captions})
        report['checks'].append({'code':'decoded_registered_exports_and_word_clock','status':'passed'})
        review = _review(review_manifest,scenario,source,original)
        if scenario=='G':
            report['asr_provenance'] = _g_asr(review,manifest,_read(job/'transcript.json'),original)
        report['scenario_result'] = checked('scenario_'+scenario,lambda:
            _scenario(scenario,review,analysis,plan,gate,responses,requests,duration,job,known))
        if _sha(job/'observed-outcome.json')!=outcome_sha or _sha(source)!=original['source_sha256']:
            raise AuditError('job_changed_during_verification','Completed job/source changed during audit','unresolved')
        report['status']='passed'
    except AuditError as error:
        report['status']=error.status
        report['checks'].append({'code':error.code,'status':error.status,'detail':str(error)})
    except (OSError,ValueError,TypeError,KeyError,AttributeError,subprocess.SubprocessError) as error:
        report['status']='failed'
        report['checks'].append({'code':'invalid_artifact_contract','status':'failed','error_type':type(error).__name__})
    return report


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job-dir',type=Path,required=True)
    parser.add_argument('--scenario',choices=list('ABCDEFGHIJ'),required=True)
    parser.add_argument('--review-manifest',type=Path)
    args=parser.parse_args(argv)
    result=verify_job(args.job_dir,args.scenario,args.review_manifest)
    print(json.dumps(result,ensure_ascii=False,allow_nan=False,indent=2))
    return {'passed':0,'failed':1,'unresolved':2}[result['status']]


if __name__=='__main__':
    raise SystemExit(main())
