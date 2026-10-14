"""Derived geometry never overwrites raw perception or crosses source changes."""
import copy,json
from app.scoped_recovery_state import persist_repaired_scenes,repaired_scenes
from tests.test_final_quality import fixture


def test_exact_derived_owners_resume_without_overwriting_native_scenes(tmp_path):
    analysis,_=fixture()
    (tmp_path/'analysis.meta.json').write_text(json.dumps({'source':'a'*64}),'utf-8')
    original=copy.deepcopy(analysis['scenes'])
    (tmp_path/'scenes.json').write_text(json.dumps(original),'utf-8')
    events=copy.deepcopy(analysis['events']);events[0]['scene_id']='repaired'
    scenes=[{**original[0],'id':'repaired'}]
    persist_repaired_scenes(tmp_path,events,scenes,analysis['transcript'],analysis['shots'])
    assert repaired_scenes(tmp_path,events,analysis['transcript'],analysis['shots'],original)==scenes
    assert json.loads((tmp_path/'scenes.json').read_text('utf-8'))==original
    for field in ('events','transcript','shots'):
        changed=copy.deepcopy({'events':events,'transcript':analysis['transcript'],'shots':analysis['shots']})
        if field=='events':changed[field][0]['unit_evidence'][0]['evidence']='Different source judgment'
        elif field=='transcript':changed[field]['words'][0]['text']='Different word'
        else:changed[field][0]['end']=3
        assert repaired_scenes(tmp_path,changed['events'],changed['transcript'],changed['shots'],original)==original
    (tmp_path/'analysis.meta.json').write_text(json.dumps({'source':'b'*64}),'utf-8')
    assert repaired_scenes(tmp_path,events,analysis['transcript'],analysis['shots'],original)==original


def test_corrupt_or_unowned_geometry_is_never_adopted(tmp_path):
    analysis,_=fixture();original=copy.deepcopy(analysis['scenes'])
    (tmp_path/'analysis.meta.json').write_text(json.dumps({'source':'a'*64}),'utf-8')
    # Even an integrity-consistent record cannot bind an event to another owner.
    persist_repaired_scenes(tmp_path,analysis['events'],[{**original[0],'id':'wrong-owner'}],analysis['transcript'],analysis['shots'])
    assert repaired_scenes(tmp_path,analysis['events'],analysis['transcript'],analysis['shots'],original)==original
    path=tmp_path/'boundary-recovery'/'derived-ownership.json'
    path.write_text('{broken','utf-8')
    assert repaired_scenes(tmp_path,analysis['events'],analysis['transcript'],analysis['shots'],original)==original
