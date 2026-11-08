#!/usr/bin/env python3
"""
Trains the injury-risk model for ONE user from their workout and status logs.

    python -m ml.train_injury_model --user-id 1 [--pain-threshold 5]

It refuses to save a model unless there are at least 30 labelled days with 5 of
each outcome. Even a saved model is only used by predict_injury_risk if its
chronological cross-validation score is at least 0.60, and it can never lower
the risk below the hard pain rule. See app/services/agents/fitness_logic.py.
"""
import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.config import settings
from backend.app.database import SessionLocal
from backend.app.models import WorkoutLog, PhysicalStatus
from backend.app.services.agents.fitness_logic import build_training_windows, injury_model_paths, FEATURE_NAMES
from backend.app.services.agents.ml_training import fit_injury_model, save_model


def main():
    p = argparse.ArgumentParser(description="Train the Ogun AI injury risk model for one user.")
    p.add_argument("--user-id", type=int, required=True, help="Required: models are per user.")
    p.add_argument("--pain-threshold", type=int, default=5, help="Future pain above this counts as a bad outcome.")
    args = p.parse_args()

    db = SessionLocal()
    try:
        workouts = db.query(WorkoutLog).filter(WorkoutLog.user_id == args.user_id).all()
        statuses = db.query(PhysicalStatus).filter(PhysicalStatus.user_id == args.user_id).all()
    finally:
        db.close()

    X, y, stats = build_training_windows(workouts, statuses, args.pain_threshold)
    print(f"[INFO] {len(workouts)} workouts, {len(statuses)} status rows -> {len(y)} labelled days "
          f"({sum(y)} high-pain, {len(y) - sum(y)} safe, {stats['skipped']} skipped).")

    pipeline, meta, problems = fit_injury_model(X, y)
    if pipeline is None:
        print("[NOT TRAINED]")
        for line in problems:
            print("  -", line)
        print("  Keep logging pain and sleep daily; the rule-based estimate is used meanwhile.")
        return

    print(f"[INFO] Chronological CV AUC: {meta['cv_auc'] if meta['cv_auc'] is not None else 'unavailable'}")
    for name, imp in sorted(zip(FEATURE_NAMES, pipeline.named_steps["clf"].feature_importances_), key=lambda t: -t[1]):
        print(f"  {name:<16} {imp:.3f}")
    pkl, meta_path = injury_model_paths(settings.ML_MODELS_DIR, args.user_id)
    save_model(pipeline, meta, pkl, meta_path)
    print(f"[SAVED] {pkl}")
    print("[IN USE] The model will influence advice." if meta["trusted"]
          else "[NOT IN USE] Saved, but too weak to trust yet (needs CV AUC >= 0.60). Rules stay in charge.")


if __name__ == "__main__":
    main()
