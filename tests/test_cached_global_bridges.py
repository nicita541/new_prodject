"""Reusing accepted global decisions must preserve their native bridge effects."""
import copy
from types import SimpleNamespace

from app.analysis_continuation import StageJournal
from app.story_review import apply_global_selection


def test_stage_cached_global_bridge_has_the_same_events_and_protects_omission(tmp_path):
    events=[{'id':'source','start':0.,'end':10.,'kind':'story','importance':4,
             'summary':'A visible departure connects two scenes.',
             'narrative_bridge':False,'selected_ranges':[{'start':0.,'end':10.}]}]
    decisions={'keep':[],'omit':[{'event':'source','reason':'nonstory',
        'evidence':'The claimed wholly nonstory content is contradicted by the accepted bridge.',
        'confidence':.95,'reaction_or_humor':False}],
        'dependencies':[],'narrative_bridges':['source']}
    journal=StageJournal(tmp_path,'a'*64,{},[],{},SimpleNamespace(event=lambda *a,**k:None),
                         lambda *a:None,lambda:False)
    fresh=copy.deepcopy(events)
    def review():
        fresh[0]['narrative_bridge']=True
        return copy.deepcopy(decisions)
    answer=journal.run('global_story',fresh,review,'deepseek_plan')
    apply_global_selection(fresh,answer)
    cached=copy.deepcopy(events)
    def forbidden():raise AssertionError('Accepted global decision must be reused')
    answer=journal.run('global_story',cached,forbidden,'antigravity_manual')
    apply_global_selection(cached,answer)
    assert cached==fresh
    assert cached[0]['narrative_bridge'] is True
    assert 'global_excluded' not in cached[0]
