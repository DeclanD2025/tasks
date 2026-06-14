from __future__ import annotations

import pandas as pd

from app import services


def test_default_user_exists():
    assert services.get_default_user_id() is not None


def test_net_worth_series_has_data():
    uid = services.get_default_user_id()
    df = services.net_worth_series(uid)
    assert isinstance(df, pd.DataFrame)
    assert not df.empty
    assert {"day", "value"}.issubset(df.columns)
    assert (df["value"] > 0).all()


def test_health_and_activity_frames():
    uid = services.get_default_user_id()
    hf = services.health_frame(uid)
    af = services.activity_frame(uid)
    assert not hf.empty and not af.empty
    assert hf["sleep_minutes"].notna().any()
    assert af["deep_work_minutes"].notna().any()


def test_overview_metrics_shape():
    uid = services.get_default_user_id()
    metrics = services.overview_metrics(uid)
    labels = {m.label for m in metrics}
    # The placeholder card set from the brief should be present.
    for required in ["Net Worth", "Sleep Average", "Weekly Insight"]:
        assert required in labels
