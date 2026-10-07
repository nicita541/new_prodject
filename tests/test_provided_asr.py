import copy
import unittest

from app.provided_asr import validate_provided_transcript


class ProvidedASRTests(unittest.TestCase):
    def setUp(self):
        self.transcript={'words':[{'start':1,'end':2,'text':'Да.'}],
                         'segments':[{'start':1,'end':2,'text':'Да.'}]}
        self.settings={'transcript_mode':'provided','transcript_source_sha256':'a'*64}

    def test_valid_source_bound_asr_has_truthful_provenance_without_fake_repair(self):
        result=validate_provided_transcript(self.transcript,self.settings,'a'*64,5)
        self.assertEqual(result['provenance']['kind'],'provided')
        self.assertNotIn('repair_version',result)
        self.assertNotIn('provenance',self.transcript)

    def test_foreign_source_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_provided_transcript(self.transcript,self.settings,'b'*64,5)

    def test_nested_or_unknown_semantic_payload_cannot_reach_model_as_words(self):
        for key in ('features','metadata','extra'):
            for container in ('words','segments',None):
                transcript=copy.deepcopy(self.transcript)
                row=transcript[container][0] if container else transcript
                row[key]={'state_after':{'character_state':'oracle-bound'},'location':'oracle-room'}
                with self.subTest(key=key,container=container),self.assertRaises(ValueError):
                    validate_provided_transcript(transcript,self.settings,'a'*64,5)

    def test_scalar_asr_metadata_is_allowed_but_nested_speaker_and_probability_are_not(self):
        transcript=copy.deepcopy(self.transcript)
        transcript.update(language='ru',device='cuda',elapsed_seconds=2.5,warning=None)
        transcript['words'][0].update(probability=.95,speaker='speaker_1')
        result=validate_provided_transcript(transcript,self.settings,'a'*64,5)
        self.assertEqual(result['words'][0]['speaker'],'speaker_1')
        for change in ({'speaker':{'location':'oracle'}},{'probability':2},{'probability':True}):
            invalid=copy.deepcopy(transcript);invalid['words'][0].update(change)
            with self.subTest(change=change),self.assertRaises(ValueError):
                validate_provided_transcript(invalid,self.settings,'a'*64,5)

    def test_validated_normalized_checkpoint_can_resume_without_leaking_metadata(self):
        from app.media_probe import normalize_transcript
        result=normalize_transcript(validate_provided_transcript(
            self.transcript,self.settings,'a'*64,5),5)
        resumed=validate_provided_transcript(result,self.settings,'a'*64,5)
        self.assertEqual(resumed['words'],self.transcript['words'])
        invalid=copy.deepcopy(result);invalid['raw_segments'][0]['metadata']={'location':'oracle'}
        with self.assertRaises(ValueError):
            validate_provided_transcript(invalid,self.settings,'a'*64,5)

    def test_semantic_answers_in_asr_are_rejected(self):
        for field in ('location','state_before','action_units','story_arc_id','summary'):
            for nested in (False,True):
                transcript=copy.deepcopy(self.transcript)
                (transcript['words'][0] if nested else transcript)[field]='oracle'
                with self.subTest(field=field,nested=nested),self.assertRaises(ValueError):
                    validate_provided_transcript(transcript,self.settings,'a'*64,5)

    def test_invalid_timestamps_and_text_cannot_skip_validation(self):
        for change in ({'start':-1},{'end':6},{'start':float('nan')},{'end':True},{'text':4},{'end':0}):
            transcript=copy.deepcopy(self.transcript);transcript['words'][0].update(change)
            with self.subTest(change=change),self.assertRaises(ValueError):
                validate_provided_transcript(transcript,self.settings,'a'*64,5)


if __name__=='__main__':
    unittest.main()
