"""Credit title checks must not burn 512 reasoning tokens on the 9B model."""
import io
import json

from app.config import STORY_MODEL
from app.story import _credit_decision, _profiled_query
from app.vision import LocalVision
from scripts.export_safe_ai_diagnostics import model_perf_summary


def test_credit_classifier_disables_reasoning_only_for_that_request(tmp_path):
    vision = LocalVision(tmp_path, lambda: False, model=STORY_MODEL, thinking=True)
    vision.port = 9876
    class StubOpener:
        def __init__(self):
            self.requests = []
        def open(self, request, timeout):
            body = json.loads(request.data.decode("utf-8"))
            self.requests.append(body)
            answer = {"credit_montage": False, "contains_credits": True,
                      "continuous_narrative": True, "confidence": .95}
            return io.BytesIO(json.dumps({
                "choices": [{"message": {"content": json.dumps(answer)},
                             "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 40, "completion_tokens": 25}
            }).encode("utf-8"))
    vision.opener = StubOpener()
    schema = {"type": "object"}
    first = _profiled_query(vision, "credit_classifier", "credit?", None,
                            max_tokens=130, schema=schema)
    assert first["continuous_narrative"] is True
    assert _credit_decision(first) is False
    second = _profiled_query(vision, "choose_units", "choose actual story units", None,
                             max_tokens=650, schema=schema)
    assert second["contains_credits"] is True
    credit_body, story_body = vision.opener.requests
    assert credit_body["chat_template_kwargs"]["enable_thinking"] is False
    assert credit_body["max_tokens"] == 130
    assert story_body["chat_template_kwargs"]["enable_thinking"] is True
    assert story_body["max_tokens"] == 650 + 512
    assert vision.thinking is True   # No session-wide mutation.
    groups = {row["stage"]: row for row in model_perf_summary(tmp_path)["by_model_and_stage"]}
    assert groups["credit_classifier"]["thinking_requests"] == 0
    assert groups["choose_units"]["thinking_requests"] == 1


def test_omission_proof_disables_reasoning_but_keeps_select_and_full_source_schema(tmp_path):
    import json
    from app.editorial import DEFAULT_PROFILE
    from app.story import verify_omissions
    vision = LocalVision(tmp_path, lambda: False, model=STORY_MODEL, thinking=True)
    vision.port = 9876
    class Opener:
        def __init__(self):
            self.calls = []
        def open(self, request, timeout):
            body = json.loads(request.data.decode('utf-8'))
            self.calls.append(body)
            answer = {'decisions': [{
                'unit':'u001', 'keep':True, 'story_change':True,
                'reaction_or_humor':False, 'current_episode_story':True,
                'confidence':.99, 'evidence':'A character is tied and moved into the car.',
                'retained_witness':'none', 'reaction_kind':'none',
                'frame_indices':[]} ]}
            return io.BytesIO(json.dumps({'choices':[{'message':{'content':json.dumps(answer)},
                                                      'finish_reason':'stop'}],
                                            'usage':{'prompt_tokens':60,'completion_tokens':80}}).encode())
    vision.opener = Opener()
    original = [{'id':'u000','start':0,'end':3},{'id':'u001','start':3,'end':5}]
    approved, proof = verify_omissions(original, {'u000'},
                  [{'unit':'u001','reason':'waiting'}], None,
                  [{'frame':1,'unit':'u001','source':4}], vision, DEFAULT_PROFILE)
    assert not approved
    assert proof['decisions'][0]['story_change']
    body = vision.opener.calls[0]
    assert body['chat_template_kwargs']['enable_thinking'] is False
    assert body['max_tokens'] == 360
    assert body['response_format']['schema']['properties']['decisions']['items']['properties']['unit']['enum'] == ['u001']
    assert vision.thinking is True


def test_omission_verification_keeps_external_adapter_contract():
    class Adapter:
        def query(self, prompt, image=None, max_tokens=100, schema=None):
            return {'requested': True}
    assert _profiled_query(Adapter(), 'verify_omissions', 'verify?') == {'requested': True}


def test_credit_safeguards_do_not_discard_mixed_story():
    assert not _credit_decision({"credit_montage": True,
        "continuous_narrative": True, "contains_credits": True,
        "confidence": 1.0})
    assert not _credit_decision({"credit_montage": True,
        "continuous_narrative": False, "contains_credits": True,
        "confidence": .80})
    assert _credit_decision({"credit_montage": True,
        "continuous_narrative": False, "contains_credits": True,
        "confidence": .95})


def test_cloud_or_mock_adapter_query_signature_unchanged():
    class Adapter:
        def query(self, prompt, image=None, max_tokens=100, schema=None):
            return {"prompt": prompt}
    assert _profiled_query(Adapter(), "credit_classifier", "credit?") == {"prompt": "credit?"}
