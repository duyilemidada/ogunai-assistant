# backend/app/services/agents/fitness_logic.py
"""
Injury-risk logic, shared by the live tool (tools.py) and the trainer
(ml/train_injury_model.py).

Why a shared module: the two used to carry separate copies of the feature code
and had drifted. The trainer built features from the 7 days BEFORE a day
(excluding it); the live tool used the last 8 days INCLUDING today. A model
trained on one shape was scored on another. Both now call injury_features().

Window rule (one definition, used everywhere):
    features for day D  = the 7 days ending on D, inclusive  [D-6 .. D]
    label for day D     = max pain on the following 3 days   (D .. D+3], exclusive of D
"""
import datetime as dt
import os
from statistics import mean
from typing import Any, Dict, Iterable, List, Optional, Tuple

FEATURE_NAMES = [
    "training_days", "total_volume", "avg_rpe", "max_rpe",
    "avg_sleep", "avg_pain", "max_pain", "low_sleep_days",
]
WINDOW_DAYS = 7
LABEL_DAYS = 3

# A model is only allowed to influence advice if it passes ALL of these.
MIN_SAMPLES = 30
MIN_PER_CLASS = 5
MIN_CV_AUC = 0.60


def injury_model_paths(models_dir: str, user_id: int) -> Tuple[str, str]:
    """(model file, metadata file). One model per user: a shared file would score
    one person with another person's training history."""
    base = os.path.join(models_dir, f"injury_model_u{user_id}")
    return base + ".pkl", base + ".json"


def window_bounds(as_of: dt.date) -> Tuple[dt.date, dt.date]:
    return as_of - dt.timedelta(days=WINDOW_DAYS - 1), as_of


def injury_features(workouts: Iterable[Any], statuses: Iterable[Any], as_of: dt.date):
    """
    Returns (features | None, summary). features follows FEATURE_NAMES.
    Status rows are collapsed to one value per DAY (max pain, mean sleep), so
    logging twice in a day cannot double-count.
    """
    start, end = window_bounds(as_of)
    w = [x for x in workouts if start <= x.date <= end]
    s = [x for x in statuses if start <= x.date <= end]
    if not w and not s:
        return None, {"days_logged": 0, "status_days_logged": 0, "training_days_last_7": 0}

    by_day: Dict[dt.date, list] = {}
    for x in s:
        by_day.setdefault(x.date, []).append(x)
    daily_pain = [max(e.pain_level for e in es) for es in by_day.values()]
    daily_sleep = [mean([e.sleep_hours for e in es]) for es in by_day.values()]
    has_status = bool(by_day)

    training_days = len({x.date for x in w})
    total_volume = float(sum(x.sets * x.reps * x.load_kg for x in w))
    rpes = [float(x.rpe) for x in w if x.rpe is not None]
    avg_rpe = mean(rpes) if rpes else 5.0
    max_rpe = max(rpes) if rpes else 5.0
    avg_sleep = mean(daily_sleep) if has_status else 7.0
    avg_pain = mean(daily_pain) if has_status else 0.0
    max_pain = float(max(daily_pain)) if has_status else 0.0
    low_sleep_days = float(sum(1 for v in daily_sleep if v < 6.0))

    recent_cut = as_of - dt.timedelta(days=2)
    recent = [e.pain_level for e in s if e.date >= recent_cut]
    recent_max = float(max(recent)) if recent else 0.0

    notes = []
    if not has_status:
        notes.append("No pain or sleep logged in the last 7 days, so recovery risk is UNKNOWN, not low.")
    if not w:
        notes.append("No workouts logged in the last 7 days.")

    features = [float(training_days), total_volume, avg_rpe, max_rpe,
                avg_sleep, avg_pain, max_pain, low_sleep_days]
    summary = {
        "days_logged": len(by_day) + training_days,
        "training_days_last_7": training_days,
        "total_volume_kg": round(total_volume, 1),
        "avg_rpe": round(avg_rpe, 1),
        "avg_sleep_hours": round(avg_sleep, 1),
        "avg_pain_level": round(avg_pain, 1),
        "max_pain_level": round(max_pain, 1),
        "recent_max_pain_3d": recent_max,
        "low_sleep_days": int(low_sleep_days),
        "status_days_logged": len(by_day),
        "data_notes": notes,
    }
    return features, summary


def heuristic_injury_risk(summary: Dict[str, Any]) -> float:
    """Rule engine used when there is no trusted model."""
    risk = 0.0
    td = summary.get("training_days_last_7", 0)
    if td >= 6:
        risk += 0.30
    elif td >= 5:
        risk += 0.10
    avg_rpe = summary.get("avg_rpe", 0)
    if avg_rpe >= 8.5:
        risk += 0.25
    elif avg_rpe >= 7.0:
        risk += 0.10

    if summary.get("status_days_logged", 0) > 0:      # no data must not read as "slept fine"
        avg_sleep = summary.get("avg_sleep_hours", 8)
        if avg_sleep < 6.0:
            risk += 0.25
        elif avg_sleep < 7.0:
            risk += 0.10

    pain = 0.0
    avg_pain = summary.get("avg_pain_level", 0)
    max_pain = summary.get("max_pain_level", 0)
    if avg_pain >= 5.0:
        pain = 0.30
    elif avg_pain >= 3.0:
        pain = 0.15
    if max_pain >= 7:                                  # one bad day is a signal, even if the average is low
        pain = max(pain, 0.30)
    elif max_pain >= 5:
        pain = max(pain, 0.15)
    return min(risk + pain, 1.0)


def safety_floor(summary: Dict[str, Any]) -> float:
    """Hard rule: recent high pain sets a minimum risk that no model can undercut."""
    recent = summary.get("recent_max_pain_3d", 0)
    if recent >= 7:
        return 0.75
    if recent >= 5:
        return 0.45
    return 0.0


def risk_label(p: float) -> str:
    return "high" if p > 0.7 else "moderate" if p > 0.4 else "low"


def combine_risk(model_prob: Optional[float], summary: Dict[str, Any]) -> Tuple[float, str]:
    base = model_prob if model_prob is not None else heuristic_injury_risk(summary)
    source = "xgboost" if model_prob is not None else "heuristic"
    floor = safety_floor(summary)
    if floor > base:
        return floor, source + "+safety_floor"
    return base, source


def model_is_trusted(meta: Dict[str, Any]) -> bool:
    n = int(meta.get("n_samples", 0) or 0)
    pos = int(meta.get("n_pos", 0) or 0)
    auc = meta.get("cv_auc")
    return (n >= MIN_SAMPLES and min(pos, n - pos) >= MIN_PER_CLASS
            and auc is not None and auc >= MIN_CV_AUC)


def build_training_windows(workouts: List[Any], statuses: List[Any], pain_threshold: int = 5):
    """
    One labelled example per day that has 3 days of logged follow-up.
    Returns (X, y, stats). Caller passes ONE user's rows (mixing users would
    blend different people's days together).
    """
    by_date: Dict[dt.date, list] = {}
    for s in statuses:
        by_date.setdefault(s.date, []).append(s)
    if not by_date:
        return [], [], {"skipped": 0}
    max_date = max(by_date)
    X, y, skipped = [], [], 0
    for anchor in sorted(by_date):
        label_end = anchor + dt.timedelta(days=LABEL_DAYS)
        if label_end > max_date:
            skipped += 1
            continue
        features, _ = injury_features(workouts, statuses, anchor)
        future = [s.pain_level for d, es in by_date.items() if anchor < d <= label_end for s in es]
        if features is None or not future:
            skipped += 1
            continue
        X.append(features)
        y.append(1 if max(future) > pain_threshold else 0)
    return X, y, {"skipped": skipped}
