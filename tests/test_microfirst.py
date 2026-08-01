"""Day-10 micro-model-first: the micro-classifier and the two-tier route, offline.

FakeEmbedder is a hashed bag-of-words, so texts that share words land close in
cosine space — enough to build separable centroids and drive the OK/UNSURE gate
without a network. FakeEngine stands in for the big LLM fallback.
"""

from jarvis.indexing.embeddings import FakeEmbedder
from tests.fake_engine import FakeEngine

from microfirst.micro import MicroClassifier
from microfirst.pipeline import route

# Two classes with disjoint vocabularies → cleanly separated centroids.
_TRAIN = [
    ("invoice payment due now urgent wire transfer", "urgent_now"),
    ("urgent wire transfer payment due immediately", "urgent_now"),
    ("newsletter weekly digest unsubscribe promo sale", "ignore"),
    ("promo sale newsletter digest unsubscribe deal", "ignore"),
]


def _micro(sim_floor=0.3, margin_floor=0.02):
    return MicroClassifier(FakeEmbedder(), sim_floor=sim_floor, margin_floor=margin_floor).fit(_TRAIN)


def test_fit_builds_one_centroid_per_label():
    micro = _micro()
    assert set(micro._centroids) == {"urgent_now", "ignore"}


def test_confident_in_distribution_message_is_ok_and_labelled():
    micro = _micro()
    r = micro.classify("urgent wire transfer payment due now")
    assert r.label == "urgent_now"
    assert r.status == "OK"
    assert r.top_sim > 0.3


def test_off_distribution_message_is_unsure_via_low_similarity():
    # Vocabulary shared with neither class → far from both centroids.
    micro = _micro(sim_floor=0.5)
    r = micro.classify("quantum lizard trampoline volcano xylophone")
    assert r.status == "UNSURE"


def test_margin_floor_forces_unsure_when_the_lead_is_too_small():
    # top_sim passes (floor 0.0) but no realistic cosine lead clears 0.95, so the
    # margin gate — not the similarity gate — is what returns UNSURE.
    micro = _micro(sim_floor=0.0, margin_floor=0.95)
    r = micro.classify("urgent wire transfer payment due now")
    assert r.status == "UNSURE"


def test_scores_cover_every_label():
    r = _micro().classify("promo sale digest")
    assert set(r.scores) == {"urgent_now", "ignore"}


# ── two-tier route ───────────────────────────────────────────────────────────

def test_ok_micro_answer_serves_without_any_llm_call():
    micro = _micro()
    engine = FakeEngine(scripted=["today"])  # must NOT be consumed
    r = route(micro, engine, "big/model", "urgent wire transfer payment due now", 0.0)
    assert r.tier == "micro"
    assert r.escalated is False
    assert r.n_llm_calls == 0
    assert len(engine.calls) == 0
    assert r.cost_usd == 0.0


def test_unsure_micro_answer_falls_back_to_the_llm():
    micro = _micro(sim_floor=0.99)  # force UNSURE on everything
    engine = FakeEngine(scripted=["ignore"])
    r = route(micro, engine, "big/model", "promo sale newsletter", 0.0)
    assert r.tier == "llm"
    assert r.escalated is True
    assert r.n_llm_calls == 1
    assert r.label == "ignore"          # served by the big model
    assert len(engine.calls) == 1


def test_reference_is_carried_through_for_scoring():
    micro = _micro()
    engine = FakeEngine(scripted=["today"])
    r = route(micro, engine, "big/model", "urgent wire transfer due now", 0.0, reference="urgent_now")
    assert r.reference == "urgent_now"
