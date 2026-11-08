# backend/app/services/agents/ml_training.py
"""
Training code for the injury and affinity models, kept out of the CLI scripts
so it can be tested without a database. The scripts in ml/ only load rows and
call these functions.
"""
import datetime as dt
import json
import os
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

from .fitness_logic import (
    FEATURE_NAMES, LABEL_DAYS, MIN_SAMPLES, MIN_PER_CLASS, model_is_trusted,
)
from .rec_logic import MIN_POS, MIN_NEG, normalize_item_type, item_text, is_false, affinity_model_is_trusted


def save_model(pipeline, meta: Dict[str, Any], pkl_path: str, meta_path: str) -> None:
    import joblib
    os.makedirs(os.path.dirname(pkl_path) or ".", exist_ok=True)
    joblib.dump(pipeline, pkl_path)
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)


def _mean_auc(scores) -> Optional[float]:
    valid = np.asarray(scores, dtype=float)
    valid = valid[~np.isnan(valid)]
    return float(valid.mean()) if len(valid) else None


# ── Injury ────────────────────────────────────────────────────────────────────

def fit_injury_model(X, y):
    """
    Returns (pipeline, meta, problems). pipeline/meta are None when the data is
    too thin, and `problems` says why. Cross-validation is chronological
    (TimeSeriesSplit with a gap): consecutive days share most of their
    7-day window and 3-day label window, so shuffled folds would let a model
    "predict" a day it had effectively already seen and inflate the score.
    """
    X = np.asarray(X, dtype=np.float32)
    y = np.asarray(y, dtype=np.int32)
    n, pos = len(y), int(y.sum())
    neg = n - pos
    problems = []
    if n < MIN_SAMPLES:
        problems.append(f"Only {n} labelled days; need at least {MIN_SAMPLES}.")
    if min(pos, neg) < MIN_PER_CLASS:
        problems.append(f"Need at least {MIN_PER_CLASS} days of each outcome (got {pos} high-pain, {neg} safe).")
    if problems:
        return None, None, problems

    from xgboost import XGBClassifier
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.model_selection import TimeSeriesSplit, cross_val_score

    pipeline = Pipeline([
        ("scaler", StandardScaler()),
        ("clf", XGBClassifier(
            n_estimators=200, max_depth=3, learning_rate=0.05, subsample=0.8,
            colsample_bytree=0.8, min_child_weight=3, scale_pos_weight=neg / pos,
            eval_metric="aucpr", random_state=42, n_jobs=1,
        )),
    ])
    cv = TimeSeriesSplit(n_splits=max(2, min(4, n // 10)), gap=LABEL_DAYS)
    cv_auc = _mean_auc(cross_val_score(pipeline, X, y, cv=cv, scoring="roc_auc", error_score=np.nan))
    pipeline.fit(X, y)
    meta = {
        "n_samples": n, "n_pos": pos, "cv_auc": cv_auc, "feature_names": FEATURE_NAMES,
        "trained_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    meta["trusted"] = model_is_trusted(meta)
    return pipeline, meta, []


# ── Affinity ──────────────────────────────────────────────────────────────────

def negatives_from_episodes(episodes: Iterable[Any], user_id: int, wanted_type: Optional[str] = None) -> List[str]:
    """
    Texts of items this user rejected, read from record_preference audit rows.
    Uses Episode.meta_data (NOT .metadata, which on a SQLAlchemy model is the
    table registry) and only this user's rows.
    """
    out = []
    for ep in episodes:
        m = getattr(ep, "meta_data", None) or {}
        if m.get("user_id") != user_id or not is_false(m.get("liked")):
            continue
        if wanted_type and normalize_item_type(m.get("item_type")) != wanted_type:
            continue
        text = item_text(m)
        if text:
            out.append(text)
    return out


def build_affinity_xy(pos_embs: Sequence[np.ndarray], neg_embs: Sequence[np.ndarray]):
    """Embedding-only features. (Price/rating/year were dropped: positives had no values for
    them, so the model learned 'has a price' = 'rejected' instead of learning taste.)"""
    X = np.vstack([np.asarray(e, dtype=np.float32) for e in list(pos_embs) + list(neg_embs)])
    y = np.array([1] * len(pos_embs) + [0] * len(neg_embs), dtype=np.int32)
    return X, y


def fit_affinity_model(X, y, item_type: Optional[str] = None):
    X = np.asarray(X, dtype=np.float32)
    y = np.asarray(y, dtype=np.int32)
    n_pos, n_neg = int(y.sum()), int((y == 0).sum())
    problems = []
    if n_pos < MIN_POS:
        problems.append(f"Only {n_pos} liked items; need at least {MIN_POS}.")
    if n_neg < MIN_NEG:
        problems.append(f"Only {n_neg} rejected items; need at least {MIN_NEG}. Rejections come from record_preference(liked=false).")
    if problems:
        return None, None, problems

    from xgboost import XGBClassifier
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.model_selection import StratifiedKFold, cross_val_score

    pipeline = Pipeline([
        ("scaler", StandardScaler()),
        ("clf", XGBClassifier(
            n_estimators=150, max_depth=3, learning_rate=0.08, subsample=0.8,
            colsample_bytree=0.5, min_child_weight=2, eval_metric="logloss",
            random_state=42, n_jobs=1,
        )),
    ])
    cv = StratifiedKFold(n_splits=min(5, n_pos, n_neg), shuffle=True, random_state=42)
    cv_auc = _mean_auc(cross_val_score(pipeline, X, y, cv=cv, scoring="roc_auc", error_score=np.nan))
    pipeline.fit(X, y)
    meta = {"n_pos": n_pos, "n_neg": n_neg, "cv_auc": cv_auc, "item_type": item_type, "features": "embedding"}
    meta["trusted"] = affinity_model_is_trusted(meta, normalize_item_type(item_type) if item_type else "")
    return pipeline, meta, []
