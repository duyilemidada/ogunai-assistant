#!/usr/bin/env python3
"""
Trains an XGBoost injury risk model from your workout and physical status logs.

Approach (sliding window):
    For each day D where PhysicalStatus data exists:
    - Features: aggregated workout + recovery data from the 7 days BEFORE D
    - Label   : 1 if max pain_level in the 3 days AFTER D exceeds the threshold, else 0

    This teaches the model: "given this training load and recovery pattern,
    will injury-level pain appear in the next 3 days?"

Minimum data needed:
    At least 30 logged days with both WorkoutLog and PhysicalStatus entries.
    The model improves significantly with 60–90 days.

Output: ml_models/injury_model.pkl  (sklearn Pipeline: StandardScaler + XGBClassifier)

Usage:
    python -m ml.train_injury_model
    python -m ml.train_injury_model --user-id 1 --pain-threshold 5
"""

import sys
import argparse
import os
import datetime as dt
import numpy as np
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.config import settings
from backend.app.database import SessionLocal
from backend.app.models import WorkoutLog, PhysicalStatus


def build_dataset(user_id=None, pain_threshold=5):
    """
    Constructs labelled feature vectors using a 7-day lookback, 3-day forecast window.

    Feature vector (8 values — must match _build_injury_features in tools.py):
        [training_days, total_volume, avg_rpe, max_rpe,
         avg_sleep, avg_pain, max_pain, low_sleep_days]
    """
    db = SessionLocal()
    try:
        w_query = db.query(WorkoutLog)
        s_query = db.query(PhysicalStatus)

        if user_id:
            w_query = w_query.filter(WorkoutLog.user_id == user_id)
            s_query = s_query.filter(PhysicalStatus.user_id == user_id)

        all_workouts = w_query.all()
        all_statuses = s_query.order_by(PhysicalStatus.date).all()

        if len(all_statuses) < 10:
            print(f"[ERROR] Only {len(all_statuses)} physical status entries found.")
            print("        Log at least 30 days of data before training.")
            return None, None

        print(f"[INFO] Found {len(all_workouts)} workout entries across {len(all_statuses)} status days.")

        # Index data by date for fast lookups
        status_by_date = {}
        for s in all_statuses:
            status_by_date.setdefault(s.date, []).append(s)

        workout_by_date = {}
        for w in all_workouts:
            workout_by_date.setdefault(w.date, []).append(w)

        unique_status_dates = sorted(status_by_date.keys())
        max_date = max(unique_status_dates)

        X, y = [], []
        skipped = 0

        for anchor_date in unique_status_dates:
            # We need at least 3 days of future data to create a label
            label_end = anchor_date + dt.timedelta(days=3)
            if label_end > max_date:
                skipped += 1
                continue

            # ── Build features from 7-day window BEFORE anchor_date ──
            window_start = anchor_date - dt.timedelta(days=7)

            window_workouts = [
                w for w in all_workouts
                if window_start <= w.date < anchor_date
            ]
            window_statuses = [
                s for date, entries in status_by_date.items()
                for s in entries
                if window_start <= date < anchor_date
            ]

            # Skip if window has no data at all (can't compute meaningful features)
            if not window_workouts and not window_statuses:
                skipped += 1
                continue

            # Workout features
            training_days = len(set(w.date for w in window_workouts))
            total_volume = sum(w.sets * w.reps * w.load_kg for w in window_workouts)
            rpe_values = [w.rpe for w in window_workouts if w.rpe is not None]
            avg_rpe = float(np.mean(rpe_values)) if rpe_values else 5.0
            max_rpe = float(max(rpe_values)) if rpe_values else 5.0

            # Recovery features
            sleep_vals = [s.sleep_hours for s in window_statuses]
            avg_sleep = float(np.mean(sleep_vals)) if sleep_vals else 7.0
            pain_vals = [s.pain_level for s in window_statuses]
            avg_pain = float(np.mean(pain_vals)) if pain_vals else 0.0
            max_pain_in_window = float(max(pain_vals)) if pain_vals else 0.0
            low_sleep_days = float(sum(1 for s in window_statuses if s.sleep_hours < 6.0))

            features = [
                float(training_days),
                float(total_volume),
                avg_rpe,
                max_rpe,
                avg_sleep,
                avg_pain,
                max_pain_in_window,
                low_sleep_days
            ]

            # ── Build label from 3 days AFTER anchor_date ──
            future_statuses = [
                s for date, entries in status_by_date.items()
                for s in entries
                if anchor_date < date <= label_end
            ]

            if future_statuses:
                future_max_pain = max(s.pain_level for s in future_statuses)
                label = 1 if future_max_pain > pain_threshold else 0
            else:
                # No status logged in the future window — skip to avoid noise
                skipped += 1
                continue

            X.append(features)
            y.append(label)

        print(f"[INFO] Created {len(y)} labelled windows (skipped {skipped} incomplete windows).")
        print(f"[INFO] Class distribution — injury (1): {sum(y)}, safe (0): {len(y) - sum(y)}")

        if len(y) < 10:
            print("[ERROR] Not enough labelled samples to train. Need at least 10.")
            print("        Continue logging daily status and retry after more data accumulates.")
            return None, None

        return np.array(X, dtype=np.float32), np.array(y, dtype=np.int32)

    finally:
        db.close()


def train(user_id=None, pain_threshold=5):
    from xgboost import XGBClassifier
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.model_selection import cross_val_score
    from sklearn.utils.class_weight import compute_sample_weight

    X, y = build_dataset(user_id, pain_threshold)
    if X is None:
        return

    # Class imbalance is common here (fewer injury days than safe days).
    # XGBoost's scale_pos_weight handles this without oversampling.
    n_neg = sum(y == 0)
    n_pos = sum(y == 1)
    scale_pos = n_neg / n_pos if n_pos > 0 else 1.0
    print(f"[INFO] scale_pos_weight = {scale_pos:.2f} (compensates for class imbalance).")

    pipeline = Pipeline([
        ("scaler", StandardScaler()),
        ("clf", XGBClassifier(
            n_estimators=200,
            max_depth=3,            # Keep shallow — we have very few features (8)
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            min_child_weight=3,
            scale_pos_weight=scale_pos,  # Handles injury/safe class imbalance
            eval_metric="aucpr",    # Area under Precision-Recall — better than AUC for imbalanced data
            use_label_encoder=False,
            random_state=42,
            n_jobs=-1
        ))
    ])

    if len(y) >= 10:
        n_folds = min(5, n_pos, n_neg)  # Can't fold more than minority class size
        if n_folds >= 2:
            scores = cross_val_score(pipeline, X, y, cv=n_folds, scoring="roc_auc")
            print(f"[INFO] Cross-val AUC-ROC ({n_folds}-fold): {scores.mean():.3f} ± {scores.std():.3f}")
            pr_scores = cross_val_score(pipeline, X, y, cv=n_folds, scoring="average_precision")
            print(f"[INFO] Cross-val Avg Precision: {pr_scores.mean():.3f} ± {pr_scores.std():.3f}")
            if scores.mean() < 0.6:
                print("[WARN] Model performance is low — more data will improve it significantly.")

    pipeline.fit(X, y)

    # Print feature importances so you can understand what the model learned
    importances = pipeline.named_steps["clf"].feature_importances_
    feature_names = [
        "training_days", "total_volume", "avg_rpe", "max_rpe",
        "avg_sleep", "avg_pain", "max_pain", "low_sleep_days"
    ]
    print("\n[INFO] Feature importances:")
    for name, imp in sorted(zip(feature_names, importances), key=lambda x: -x[1]):
        bar = "█" * int(imp * 40)
        print(f"  {name:<20} {bar} {imp:.3f}")

    os.makedirs(settings.ML_MODELS_DIR, exist_ok=True)
    import joblib
    model_path = os.path.join(settings.ML_MODELS_DIR, "injury_model.pkl")
    joblib.dump(pipeline, model_path)
    print(f"\n[✓] Injury model saved → {model_path}")
    print("    predict_injury_risk() will use XGBoost from the next call onwards.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train the Ogun AI injury risk model.")
    parser.add_argument(
        "--user-id", type=int, default=None,
        help="Train for a specific user. Omit to train on all users."
    )
    parser.add_argument(
        "--pain-threshold", type=int, default=5,
        help="Pain level above which a future window is labelled as 'injury'. Default: 5."
    )
    args = parser.parse_args()
    train(args.user_id, args.pain_threshold)