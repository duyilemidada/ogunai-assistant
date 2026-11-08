import datetime as dt
from types import SimpleNamespace as NS

import numpy as np
import pytest

from app.services.agents import fitness_logic as fl, ml_training as mt, rec_logic as rl


def synthetic_logs(days=100, seed=0):
    """Heavy weeks (hard, frequent training, poor sleep) are followed by pain."""
    rng = np.random.default_rng(seed)
    start = dt.date(2026, 1, 1)
    workouts, statuses = [], []
    for i in range(days):
        d = start + dt.timedelta(days=i)
        heavy = (i // 7) % 3 == 2
        if rng.random() < (0.95 if heavy else 0.45):
            workouts.append(NS(date=d, sets=4, reps=5, load_kg=100 if heavy else 60, rpe=9 if heavy else 6))
        after_heavy = (i // 7) % 3 == 0 and i >= 7 and (i % 7) < 3
        pain = int(rng.integers(0, 3)) + (5 if after_heavy else 0)
        statuses.append(NS(date=d, pain_level=min(pain, 10), sleep_hours=float(rng.normal(5.5 if heavy else 7.5, 0.3))))
    return workouts, statuses


def test_training_rows_use_exactly_the_serving_features():
    w, s = synthetic_logs()
    X, y, _ = fl.build_training_windows(w, s, 5)
    first_anchor = min(x.date for x in s)
    expected, _ = fl.injury_features(w, s, first_anchor)
    assert X[0] == expected


def test_injury_trainer_refuses_thin_or_one_sided_data():
    pipe, meta, problems = mt.fit_injury_model([[0] * 8] * 10, [0, 1] * 5)
    assert pipe is None and "30" in problems[0]
    pipe, meta, problems = mt.fit_injury_model([[0] * 8] * 40, [0] * 40)
    assert pipe is None and "each outcome" in problems[0]


def test_injury_trainer_learns_a_real_pattern_and_marks_it_trusted():
    pytest.importorskip("xgboost"); pytest.importorskip("sklearn")
    w, s = synthetic_logs()
    X, y, _ = fl.build_training_windows(w, s, 5)
    assert 0 < sum(y) < len(y)
    pipe, meta, problems = mt.fit_injury_model(X, y)
    assert not problems and meta["cv_auc"] is not None and meta["cv_auc"] > 0.6 and meta["trusted"]
    assert pipe.predict_proba(np.array(X[:3], dtype=np.float32)).shape == (3, 2)


def test_injury_trainer_on_pure_noise_is_not_trusted():
    pytest.importorskip("xgboost"); pytest.importorskip("sklearn")
    rng = np.random.default_rng(1)
    X = rng.normal(size=(80, 8)); y = rng.integers(0, 2, size=80)
    _, meta, _ = mt.fit_injury_model(X, y)
    assert not meta["trusted"]


def test_negatives_come_from_meta_data_for_this_user_only():
    eps = [
        NS(meta_data={"user_id": 1, "liked": False, "item_type": "book", "title": "Bad Book", "description": "dull"}),
        NS(meta_data={"user_id": 2, "liked": False, "item_type": "book", "title": "Other Users Dislike"}),
        NS(meta_data={"user_id": 1, "liked": True, "item_type": "book", "title": "A Like"}),
        NS(meta_data={"user_id": 1, "liked": "false", "item_type": "Movies", "title": "Bad Film"}),
        NS(meta_data={"user_id": 1, "liked": False, "item_type": "book", "title": ""}),
        NS(meta_data=None),
    ]
    assert mt.negatives_from_episodes(eps, 1) == ["Bad Book dull", "Bad Film"]
    assert mt.negatives_from_episodes(eps, 1, "book") == ["Bad Book dull"]


def test_affinity_features_are_embedding_only_with_no_scalar_columns():
    X, y = mt.build_affinity_xy([np.ones(384)] * 3, [np.zeros(384)] * 2)
    assert X.shape == (5, 384) and list(y) == [1, 1, 1, 0, 0]


def test_affinity_trainer_refuses_without_real_rejections():
    X, y = mt.build_affinity_xy([np.ones(8)] * 20, [np.zeros(8)] * 3)
    pipe, _, problems = mt.fit_affinity_model(X, y)
    assert pipe is None and "rejected" in problems[0]


def test_affinity_trainer_separates_two_tastes():
    pytest.importorskip("xgboost"); pytest.importorskip("sklearn")
    rng = np.random.default_rng(0)
    pos = [np.r_[1.0, 0.0, rng.normal(0, 0.3, 6)] for _ in range(25)]
    neg = [np.r_[0.0, 1.0, rng.normal(0, 0.3, 6)] for _ in range(15)]
    X, y = mt.build_affinity_xy(pos, neg)
    pipe, meta, problems = mt.fit_affinity_model(X, y, "book")
    assert not problems and meta["cv_auc"] > 0.9 and meta["trusted"]


def test_save_and_reload_roundtrip(tmp_path):
    pytest.importorskip("xgboost"); pytest.importorskip("sklearn"); pytest.importorskip("joblib")
    import json, joblib
    w, s = synthetic_logs()
    X, y, _ = fl.build_training_windows(w, s, 5)
    pipe, meta, _ = mt.fit_injury_model(X, y)
    pkl, mp = fl.injury_model_paths(str(tmp_path), 7)
    mt.save_model(pipe, meta, pkl, mp)
    assert fl.model_is_trusted(json.load(open(mp))) and joblib.load(pkl) is not None
