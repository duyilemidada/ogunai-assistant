#!/usr/bin/env python3
"""
Trains the taste model for ONE user from their likes (UserLike) and rejections
(record_preference calls with liked=false, stored in the Episode audit log).

    python -m ml.train_affinity_model --user-id 1 [--item-type book]

You usually do NOT need this: similarity scoring works from the first like. The
model is only saved with at least 15 likes and 10 real rejections, and is only
used if its cross-validated AUC is at least 0.65. There are no synthetic
negatives and no price/rating/year features (both caused the model to learn
artifacts instead of taste).
"""
import argparse
import sys
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.config import settings
from backend.app.database import SessionLocal
from backend.app.models import UserLike, Episode
from backend.app.services.agents.tools import get_embedder
from backend.app.services.agents.rec_logic import affinity_model_paths, normalize_item_type
from backend.app.services.agents.ml_training import (
    negatives_from_episodes, build_affinity_xy, fit_affinity_model, save_model,
)


def main():
    p = argparse.ArgumentParser(description="Train the Ogun AI taste model for one user.")
    p.add_argument("--user-id", type=int, required=True, help="Required: models are per user.")
    p.add_argument("--item-type", default=None, help="Train for one kind of item only (book, movie, ...).")
    args = p.parse_args()
    wanted = normalize_item_type(args.item_type) if args.item_type else None

    db = SessionLocal()
    try:
        likes = [l for l in db.query(UserLike).filter(UserLike.user_id == args.user_id).all()
                 if not wanted or normalize_item_type(l.item_type) == wanted]
        episodes = db.query(Episode).filter(Episode.action == "record_preference").all()
    finally:
        db.close()

    pos = [np.frombuffer(l.embedding, dtype=np.float32) for l in likes]
    neg_texts = negatives_from_episodes(episodes, args.user_id, wanted)
    neg = list(get_embedder().encode(neg_texts)) if neg_texts else []
    print(f"[INFO] {len(pos)} liked, {len(neg)} rejected.")
    if not pos or not neg:
        print("[NOT TRAINED] Need both likes and rejections.")
        return

    X, y = build_affinity_xy(pos, neg)
    pipeline, meta, problems = fit_affinity_model(X, y, args.item_type)
    if pipeline is None:
        print("[NOT TRAINED]")
        for line in problems:
            print("  -", line)
        print("  Similarity scoring keeps working meanwhile.")
        return
    print(f"[INFO] Cross-validated AUC: {meta['cv_auc'] if meta['cv_auc'] is not None else 'unavailable'}")
    pkl, meta_path = affinity_model_paths(settings.ML_MODELS_DIR, args.user_id)
    save_model(pipeline, meta, pkl, meta_path)
    print(f"[SAVED] {pkl}")
    print("[IN USE]" if meta["trusted"] else "[NOT IN USE] Saved, but too weak to trust yet (needs CV AUC >= 0.65).")


if __name__ == "__main__":
    main()
