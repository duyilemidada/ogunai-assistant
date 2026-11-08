"""Tool-level checks. Uses an in-memory database: never touches your real ogun.db."""
import datetime as dt
import zlib
from types import SimpleNamespace as NS
from typing import Any, Dict, List, Optional

import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import PhysicalStatus, WorkoutLog, UserLike, Episode, DailyNutrition
from app.services.agents import tools


@pytest.fixture
def db(monkeypatch, tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    monkeypatch.setattr(tools, "SessionLocal", Session)
    monkeypatch.setattr(tools.settings, "ML_MODELS_DIR", str(tmp_path), raising=False)
    s = Session()
    yield s
    s.close()


class FakeEmbedder:
    """Deterministic bag-of-words embedder: shared words => similar vectors."""
    def _one(self, text):
        v = np.zeros(64, dtype=np.float32)
        for w in str(text).lower().split():
            v[zlib.crc32(w.encode()) % 64] += 1.0
        return v
    def encode(self, x):
        return self._one(x) if isinstance(x, str) else np.array([self._one(t) for t in x])


# ── tool schemas ──────────────────────────────────────────────────────────────

def test_schema_types_for_optional_dict_and_list():
    props = {t["function"]["name"]: t["function"]["parameters"]["properties"]
             for t in tools.get_tool_schemas(["predict_affinity", "score_candidates", "log_physical_status", "record_preference"])}
    assert props["predict_affinity"]["metadata"]["type"] == "object"
    assert props["score_candidates"]["candidates"] == {"type": "array", "items": {"type": "object"}}
    assert props["log_physical_status"]["energy_level"]["type"] == "number"
    assert props["record_preference"]["liked"]["type"] == "boolean"
    assert "user_id" not in props["record_preference"]


# ── adjust_program ────────────────────────────────────────────────────────────

def test_elbow_injury_never_gets_zercher_or_machines():
    alts = tools.adjust_program("right elbow", "curl")["alternatives"]
    assert alts and "Zercher squat" not in alts
    assert not any(w in " ".join(alts).lower() for w in ("machine", "cable", "leg press"))


def test_unknown_site_gives_no_invented_alternatives():
    r = tools.adjust_program("neck", "press")
    assert r["alternatives"] == [] and "do not recognise" in r["note"]


def test_two_sites_use_only_moves_safe_for_both():
    assert tools.adjust_program("knee and lower back", "x")["alternatives"] == [
        "bench press", "barbell curl", "single-arm behind-the-neck tricep extension"]


def test_site_words_match_on_word_start_only():
    assert tools.adjust_program("shipping container", "x")["alternatives"] == []


# ── nutrition ─────────────────────────────────────────────────────────────────

def nutrient(i, v): return {"nutrientId": i, "value": v}

def fake_usda(monkeypatch, foods):
    class R:
        def raise_for_status(self): pass
        def json(self): return {"foods": foods}
    monkeypatch.setattr(tools.httpx, "get", lambda *a, **k: R())
    monkeypatch.setattr(tools.settings, "USDA_API_KEY", "k", raising=False)
    monkeypatch.setattr(tools.settings, "USDA_BASE_URL", "http://usda", raising=False)


def test_branded_food_is_scaled_per_100g_not_per_serving(db, monkeypatch):
    # Per-100g values with a 28 g serving: the old code divided by 28 and overstated by 3.6x.
    fake_usda(monkeypatch, [{"description": "SNACK", "dataType": "Branded", "servingSize": 28, "servingSizeUnit": "g",
                             "foodNutrients": [nutrient(1008, 500), nutrient(1003, 10), nutrient(1005, 60), nutrient(1004, 25)]}])
    r = tools.log_nutrition("snack", 100, user_id=1)
    assert r["calories"] == 500.0 and r["protein_grams"] == 10.0
    assert db.query(DailyNutrition).one().calories == 500.0
    assert tools.log_nutrition("snack", 50, user_id=1)["calories"] == 250.0


def test_foundation_food_with_atwater_energy_is_logged(db, monkeypatch):
    fake_usda(monkeypatch, [{"description": "Chicken, cooked", "dataType": "Foundation",
                             "foodNutrients": [nutrient(2047, 165), nutrient(1003, 31), nutrient(1004, 3.6)]}])
    assert tools.log_nutrition("chicken", 200, user_id=1)["calories"] == 330.0


def test_absurd_database_rows_are_skipped_not_logged(db, monkeypatch):
    fake_usda(monkeypatch, [
        {"description": "BROKEN", "foodNutrients": [nutrient(1008, 28000), nutrient(1003, 1600)]},
        {"description": "GOOD", "foodNutrients": [nutrient(1008, 100), nutrient(1003, 5)]}])
    assert tools.log_nutrition("x", 100, user_id=1)["logged"] == "GOOD"


def test_bad_portions_are_rejected(db):
    for p in (0, -5, 99999, "two eggs"):
        assert "error" in tools.log_nutrition("egg", p, user_id=1)


# ── physical status / injury risk ─────────────────────────────────────────────

def test_logging_twice_in_a_day_updates_one_row_and_keeps_worst_pain(db):
    tools.log_physical_status(pain_level=2, sleep_hours=7, user_id=1)
    r = tools.log_physical_status(pain_level=6, sleep_hours=6.5, user_id=1, energy_level="7")
    r2 = tools.log_physical_status(pain_level=1, sleep_hours=6.5, user_id=1)
    rows = db.query(PhysicalStatus).all()
    assert len(rows) == 1 and rows[0].pain_level == 6 and rows[0].energy_level == 7
    assert r["updated_existing_entry"] and r2["pain_level"] == 6


def test_recent_high_pain_means_high_risk(db):
    today = dt.date.today()
    db.add(WorkoutLog(user_id=1, date=today - dt.timedelta(days=2), exercise_name="rdl", sets=3, reps=5, load_kg=80, rpe=6))
    db.add(PhysicalStatus(user_id=1, date=today - dt.timedelta(days=1), pain_level=8, sleep_hours=8))
    db.commit()
    r = tools.predict_injury_risk(user_id=1)
    assert r["risk"] == "high" and r["model"].endswith("safety_floor")


def test_no_data_is_unknown(db):
    assert tools.predict_injury_risk(user_id=1)["risk"] == "unknown"


def test_untrusted_model_file_is_ignored(db, tmp_path):
    from app.services.agents.fitness_logic import injury_model_paths
    import json
    pkl, meta = injury_model_paths(str(tmp_path), 1)
    open(pkl, "wb").write(b"not a real model"); json.dump({"n_samples": 10, "n_pos": 5, "cv_auc": 0.99}, open(meta, "w"))
    today = dt.date.today()
    db.add(PhysicalStatus(user_id=1, date=today, pain_level=1, sleep_hours=8)); db.commit()
    r = tools.predict_injury_risk(user_id=1)
    assert r["model"] == "heuristic" and "too weak" in r["note"]


# ── recommendations ───────────────────────────────────────────────────────────

def test_the_loop_closes_like_then_rank_then_reject(db, monkeypatch):
    monkeypatch.setattr(tools, "get_embedder", lambda: FakeEmbedder())
    assert tools.record_preference("Books", "Dune", True, user_id=1, description="sci-fi desert epic")["recorded"] == "like"
    like = db.query(UserLike).one()
    assert like.item_type == "book" and like.description == "sci-fi desert epic"

    cands = [{"title": "Foundation", "description": "sci-fi epic"}, {"title": "Pasta basics", "description": "cooking for beginners"}]
    r = tools.score_candidates("book", cands, user_id=1)
    assert [x["title"] for x in r["ranked"]] == ["Foundation", "Pasta basics"]
    assert r["based_on"] == {"liked": 1, "rejected": 0}

    # a rejection is stored by the audit log (Episode) when the tool call finishes
    tools.record_preference("book", "Pasta basics", False, user_id=1, description="cooking for beginners")
    db.add(Episode(conversation_id=1, agent_name="LifestyleAgent", action="record_preference",
                   meta_data={"item_type": "book", "title": "Pasta basics", "description": "cooking for beginners",
                              "liked": False, "user_id": 1}))
    db.commit()
    r2 = tools.score_candidates("book", [{"title": "Pasta for two", "description": "cooking for beginners"}], user_id=1)
    assert r2["based_on"]["rejected"] == 1 and "rejected" in r2["ranked"][0]["reason"]


def test_one_users_history_does_not_leak_to_another(db, monkeypatch):
    monkeypatch.setattr(tools, "get_embedder", lambda: FakeEmbedder())
    tools.record_preference("book", "Dune", True, user_id=1, description="sci-fi desert epic")
    r = tools.score_candidates("book", [{"title": "Foundation", "description": "sci-fi epic"}], user_id=2)
    assert r["ranked"][0]["model"] == "no_data"


def test_changing_your_mind_removes_the_like(db, monkeypatch):
    monkeypatch.setattr(tools, "get_embedder", lambda: FakeEmbedder())
    tools.record_preference("book", "Dune", True, user_id=1)
    tools.record_preference("book", "Dune", False, user_id=1)
    assert db.query(UserLike).count() == 0


def test_predict_affinity_tolerates_a_string_instead_of_an_object(db, monkeypatch):
    monkeypatch.setattr(tools, "get_embedder", lambda: FakeEmbedder())
    assert "affinity_score" in tools.predict_affinity("book", '{"title": "Dune"}', user_id=1)
    assert "affinity_score" in tools.predict_affinity("book", "Dune", user_id=1)
    assert "error" in tools.predict_affinity("book", {}, user_id=1)
