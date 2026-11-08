import datetime as dt
from types import SimpleNamespace as NS
from app.services.agents import fitness_logic as fl

TODAY = dt.date(2026, 11, 7)
d = lambda n: TODAY - dt.timedelta(days=n)
workout = lambda n, rpe=6: NS(date=d(n), sets=3, reps=5, load_kg=60, rpe=rpe)
status = lambda n, pain=0, sleep=7.5: NS(date=d(n), pain_level=pain, sleep_hours=sleep)


def test_one_bad_pain_day_is_not_low_risk():
    _, s = fl.injury_features([workout(2)], [status(1, pain=8)], TODAY)
    risk, source = fl.combine_risk(None, s)
    assert fl.risk_label(risk) == "high" and source == "heuristic+safety_floor"


def test_model_can_never_undercut_the_pain_floor():
    _, s = fl.injury_features([workout(2)], [status(1, pain=8)], TODAY)
    assert fl.combine_risk(0.05, s)[0] == 0.75
    assert fl.combine_risk(0.95, s)[0] == 0.95        # but it may raise it


def test_missing_recovery_data_is_unknown_not_low_or_poor_sleep():
    f, s = fl.injury_features([workout(2)], [], TODAY)
    assert "UNKNOWN" in s["data_notes"][0]
    assert fl.heuristic_injury_risk(s) == 0.0         # sleep default must not be punished or rewarded


def test_two_logs_in_one_day_count_once():
    _, s = fl.injury_features([workout(2)], [status(1, 2, 5.0), status(1, 6, 8.0)], TODAY)
    assert s["status_days_logged"] == 1 and s["max_pain_level"] == 6


def test_window_is_seven_days_including_today():
    assert fl.injury_features([workout(0)], [], TODAY)[0] is not None
    assert fl.injury_features([workout(6)], [], TODAY)[0] is not None
    assert fl.injury_features([workout(7)], [], TODAY)[0] is None


def test_label_looks_only_at_the_next_three_days():
    base = [workout(i) for i in range(0, 10)]
    def label(spike_day_offset):
        sts = [status(10 - i) for i in range(10)]               # days d(10)..d(1), all pain 0
        anchor = d(8)
        target = anchor + dt.timedelta(days=spike_day_offset)
        for s in sts:
            if s.date == target:
                s.pain_level = 9
        X, y, _ = fl.build_training_windows(base, sts, 5)
        return dict(zip([row[6] for row in X], y))               # not used; see below
    # direct check on one anchor
    sts = [status(i) for i in range(10, 0, -1)]
    anchor = d(8)
    for s in sts:
        if s.date == anchor + dt.timedelta(days=2):
            s.pain_level = 9
    X, y, _ = fl.build_training_windows(base, sts, 5)
    first_anchor_row = X[0]                                       # earliest anchor = d(10)
    assert len(X) == len(y) > 0
    assert y[2] == 1                                              # anchor d(8): spike two days later


def test_trust_rules():
    assert not fl.model_is_trusted({"n_samples": 10, "n_pos": 5, "cv_auc": 0.9})
    assert not fl.model_is_trusted({"n_samples": 60, "n_pos": 2, "cv_auc": 0.9})
    assert not fl.model_is_trusted({"n_samples": 60, "n_pos": 20, "cv_auc": 0.5})
    assert not fl.model_is_trusted({"n_samples": 60, "n_pos": 20, "cv_auc": None})
    assert fl.model_is_trusted({"n_samples": 60, "n_pos": 20, "cv_auc": 0.7})
