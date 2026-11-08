import numpy as np
from app.services.agents import rec_logic as rl

A = np.array([1, 0, 0], dtype=np.float32)
B = np.array([0.9, 0.1, 0], dtype=np.float32)
C = np.array([0, 1, 0], dtype=np.float32)


def test_item_type_variants_collapse():
    for v in ("Movies", "movie ", "film", "FILMS"):
        assert rl.normalize_item_type(v) == "movie"
    assert rl.normalize_item_type("books") == "book" and rl.normalize_item_type("glass") == "glass"


def test_cold_start_is_neutral_and_says_so():
    r = rl.score_against_history(A, [], [])
    assert r["affinity_score"] == 0.5 and r["model"] == "no_data" and r["confidence"] == "low"


def test_close_to_a_like_scores_high():
    r = rl.score_against_history(B, [("A", A)], [])
    assert r["affinity_score"] > 0.9 and r["confidence"] == "high" and "A" in r["reason"]


def test_closer_to_a_rejection_than_a_like_is_halved():
    r = rl.score_against_history(C, [("A", A)], [("C", C)])
    assert "rejected" in r["reason"] and r["affinity_score"] <= 0.5


def test_only_rejections_pushes_similar_items_down():
    assert rl.score_against_history(C, [], [("C", C)])["affinity_score"] < 0.5


def test_model_trust_checks_type_and_quality():
    ok = {"n_pos": 20, "n_neg": 12, "cv_auc": 0.8, "item_type": None}
    assert rl.affinity_model_is_trusted(ok, "book")
    assert not rl.affinity_model_is_trusted({**ok, "item_type": "movie"}, "book")
    assert not rl.affinity_model_is_trusted({**ok, "cv_auc": 0.5}, "book")
    assert not rl.affinity_model_is_trusted({**ok, "n_neg": 3}, "book")


def test_is_false_handles_sloppy_booleans():
    assert rl.is_false(False) and rl.is_false("false") and rl.is_false("No")
    assert not rl.is_false(True) and not rl.is_false(None) and not rl.is_false("true")
