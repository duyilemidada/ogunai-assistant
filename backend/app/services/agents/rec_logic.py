# backend/app/services/agents/rec_logic.py
"""
Recommendation scoring, kept free of database and model-loading code so it can
be tested directly.

How a candidate is scored (no trained model needed, works from the first like):
  - similarity to the closest thing the user LIKED  -> the score
  - similarity to the closest thing the user REJECTED -> if closer than the
    best like, the score is halved and the reason says so
Embeddings come from all-MiniLM-L6-v2. Its cosine scores run lower than people
expect (two clearly related titles often land at 0.4 to 0.6), so the
confidence cut-offs below are set for that model, not for a 0 to 1 intuition.
"""
import os
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

STRONG = 0.55
MEDIUM = 0.35
MIN_POS = 15
MIN_NEG = 10
MIN_CV_AUC = 0.65

_TYPE_ALIASES = {
    "film": "movie", "films": "movie", "movies": "movie", "tv": "show", "series": "show", "shows": "show",
    "music": "song", "songs": "song", "track": "song", "tracks": "song", "albums": "album",
    "books": "book", "novel": "book", "novels": "book", "products": "product",
}


def normalize_item_type(value: Any) -> str:
    """'Movies', 'movie ', 'film' all become 'movie' (the model rarely repeats a label exactly)."""
    t = re.sub(r"\s+", " ", str(value or "").strip().lower())
    if t in _TYPE_ALIASES:
        return _TYPE_ALIASES[t]
    return t[:-1] if len(t) > 3 and t.endswith("s") and not t.endswith("ss") else t


def item_text(meta: Dict[str, Any]) -> str:
    return f"{meta.get('title', '')} {meta.get('description', '')}".strip()


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
    return float(np.dot(a, b) / (na * nb)) if na > 0 and nb > 0 else 0.0


def _confidence(score: float) -> str:
    return "high" if score >= STRONG else "medium" if score >= MEDIUM else "low"


def score_against_history(
    candidate: np.ndarray,
    liked: Sequence[Tuple[str, np.ndarray]],
    disliked: Sequence[Tuple[str, np.ndarray]],
) -> Dict[str, Any]:
    best_like = max(((cosine(candidate, e), t) for t, e in liked), default=(None, None), key=lambda x: -1 if x[0] is None else x[0])
    best_dis = max(((cosine(candidate, e), t) for t, e in disliked), default=(None, None), key=lambda x: -1 if x[0] is None else x[0])
    like_sim, like_title = best_like
    dis_sim, dis_title = best_dis

    if like_sim is None and dis_sim is None:
        return {"affinity_score": 0.5, "confidence": "low", "model": "no_data",
                "reason": "No likes or rejections recorded yet, so this is a neutral guess."}

    if like_sim is None:                                   # only rejections so far
        if dis_sim >= MEDIUM:
            return {"affinity_score": round(max(0.1, 0.5 - dis_sim / 2), 2), "confidence": "low",
                    "model": "similarity", "reason": f"Similar to '{dis_title}' which you rejected."}
        return {"affinity_score": 0.5, "confidence": "low", "model": "similarity",
                "reason": "Nothing liked yet; not close to anything you rejected."}

    score = max(like_sim, 0.0)
    reason = f"Closest to '{like_title}' which you liked."
    if dis_sim is not None and dis_sim > like_sim:
        score *= 0.5
        reason = f"Closer to '{dis_title}' which you rejected than to anything you liked."
    score = min(score, 1.0)
    return {"affinity_score": round(score, 2), "confidence": _confidence(score),
            "model": "similarity", "reason": reason}


def affinity_model_paths(models_dir: str, user_id: int) -> Tuple[str, str]:
    base = os.path.join(models_dir, f"affinity_model_u{user_id}")
    return base + ".pkl", base + ".json"


def affinity_model_is_trusted(meta: Dict[str, Any], wanted_type: str) -> bool:
    trained_type = meta.get("item_type")
    if trained_type and normalize_item_type(trained_type) != wanted_type:
        return False
    auc = meta.get("cv_auc")
    return (int(meta.get("n_pos", 0) or 0) >= MIN_POS and int(meta.get("n_neg", 0) or 0) >= MIN_NEG
            and auc is not None and auc >= MIN_CV_AUC)


def is_false(v: Any) -> bool:
    """True for False / 'false' / 'no' / 'dislike' (the model is not consistent about booleans)."""
    return v is False or str(v).strip().lower() in ("false", "no", "0", "dislike", "disliked")
