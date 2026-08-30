#!/usr/bin/env python3
"""
Trains an XGBoost affinity model from your liked items and episode feedback.

Positives  → UserLike table (items you explicitly liked)
Negatives  → Episode rows where action='predict_affinity' and feedback=0
             (items the agent recommended that you rejected)
             + synthetic low-similarity embeddings to balance the classes

Output: ml_models/affinity_model.pkl  (sklearn Pipeline: StandardScaler + XGBClassifier)

Once saved, predict_affinity() in tools.py picks it up automatically on the next call.

Usage:
    python -m ml.train_affinity_model             # all users
    python -m ml.train_affinity_model --user-id 1 # single user
"""

import sys
import argparse
import os
import numpy as np
from pathlib import Path

# Make backend importable when running from project root
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.config import settings
from backend.app.database import SessionLocal
from backend.app.models import UserLike, Episode
from backend.app.services.agents.tools import get_embedder


def build_dataset(user_id=None):
    """
    Returns (X, y) where X is (n_samples, 387) and y is binary.
    Feature layout: [embedding (384 dims), price, rating, year]
    """
    db = SessionLocal()
    embedder = get_embedder()
    X, y = [], []

    try:
        # ── Positive examples: items the user liked ──
        query = db.query(UserLike)
        if user_id:
            query = query.filter(UserLike.user_id == user_id)
        liked = query.all()

        if len(liked) < 5:
            print(f"[ERROR] Only {len(liked)} liked items found. Need at least 5 to train.")
            print("        Use the agent to like more items, then re-run this script.")
            return None, None

        print(f"[INFO] Positive examples: {len(liked)} liked items.")
        pos_embeddings = []

        for item in liked:
            emb = np.frombuffer(item.embedding, dtype=np.float32)
            pos_embeddings.append(emb)
            # Scalars default to 0 since UserLike doesn't store price/rating —
            # the XGBoost model will learn to weight them appropriately once
            # the LifestyleAgent starts passing metadata with scalar fields.
            features = np.hstack([emb, [0.0, 0.0, 0.0]])
            X.append(features)
            y.append(1)

        pos_embeddings = np.array(pos_embeddings)

        # ── Negative examples: rejected recommendations from episode feedback ──
        neg_episodes = db.query(Episode).filter(
            Episode.action == "predict_affinity",
            Episode.feedback == 0
        ).all()

        print(f"[INFO] Negative examples from feedback: {len(neg_episodes)} rejected recommendations.")

        for ep in neg_episodes:
            meta = ep.metadata or {}
            title = meta.get("title", "")
            desc = meta.get("description", "")
            text = f"{title} {desc}".strip()
            if not text:
                continue
            emb = embedder.encode(text).astype(np.float32)
            features = np.hstack([
                emb,
                [
                    float(meta.get("price", 0)),
                    float(meta.get("rating", 0)),
                    float(meta.get("year", 0))
                ]
            ])
            X.append(features)
            y.append(0)

        # ── Synthetic negatives if we don't have enough real ones ──
        # Strategy: generate random embeddings and keep only those with low
        # cosine similarity to ALL liked items — these safely represent "not your taste".
        n_pos = sum(1 for label in y if label == 1)
        n_neg = sum(1 for label in y if label == 0)
        n_needed = n_pos - n_neg

        if n_needed > 0:
            print(f"[INFO] Generating up to {n_needed} synthetic negatives (low-similarity embeddings)...")
            # Sample random sentences that are deliberately generic/off-topic
            # The embedding distance from liked items makes them good negatives.
            generic_texts = [
                f"random unrelated item category{i % 20} type{i % 8} object{i}"
                for i in range(n_needed * 3)  # Over-sample, then filter
            ]
            added = 0
            for text in generic_texts:
                if added >= n_needed:
                    break
                emb = embedder.encode(text).astype(np.float32)
                # Cosine similarity to all positive embeddings
                norms = np.linalg.norm(pos_embeddings, axis=1) * np.linalg.norm(emb)
                sims = np.dot(pos_embeddings, emb) / (norms + 1e-8)
                # Only accept if max similarity < 0.3 — far enough from liked items
                if np.max(sims) < 0.3:
                    features = np.hstack([emb, [0.0, 0.0, 0.0]])
                    X.append(features)
                    y.append(0)
                    added += 1
            print(f"[INFO] Added {added} synthetic negatives.")

    finally:
        db.close()

    X = np.array(X, dtype=np.float32)
    y = np.array(y, dtype=np.int32)
    print(f"[INFO] Final dataset: {sum(y==1)} positives, {sum(y==0)} negatives — {len(y)} total samples.")
    return X, y


def train(user_id=None):
    from xgboost import XGBClassifier
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.model_selection import cross_val_score

    X, y = build_dataset(user_id)
    if X is None:
        return

    # StandardScaler normalises the scalar features (price, rating, year) relative to
    # the embedding dimensions — without this, the scalars would be drowned out.
    # XGBoost with these settings is robust against the high-dimensionality of embeddings.
    pipeline = Pipeline([
        ("scaler", StandardScaler()),
        ("clf", XGBClassifier(
            n_estimators=150,
            max_depth=4,
            learning_rate=0.08,
            subsample=0.8,
            colsample_bytree=0.6,
            min_child_weight=2,
            eval_metric="logloss",
            use_label_encoder=False,
            random_state=42,
            n_jobs=-1
        ))
    ])

    # Cross-validate only if we have enough samples
    if len(y) >= 10:
        n_folds = min(5, sum(y == 1), sum(y == 0))  # Can't have more folds than samples in minority class
        if n_folds >= 2:
            scores = cross_val_score(pipeline, X, y, cv=n_folds, scoring="roc_auc")
            print(f"[INFO] Cross-val AUC-ROC ({n_folds}-fold): {scores.mean():.3f} ± {scores.std():.3f}")
            if scores.mean() < 0.6:
                print("[WARN] AUC below 0.6 — model may not be useful yet. Add more liked items and feedback.")

    pipeline.fit(X, y)

    os.makedirs(settings.ML_MODELS_DIR, exist_ok=True)
    import joblib
    model_path = os.path.join(settings.ML_MODELS_DIR, "affinity_model.pkl")
    joblib.dump(pipeline, model_path)
    print(f"[✓] Affinity model saved → {model_path}")
    print("    predict_affinity() will use XGBoost from the next call onwards.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train the Ogun AI affinity model.")
    parser.add_argument(
        "--user-id", type=int, default=None,
        help="Train for a specific user ID. Omit to train on all users."
    )
    args = parser.parse_args()
    train(args.user_id)