from datetime import datetime

import pytest

from monitoring import build_morning_report
from tests.fakes import JST, Resp, make_monitor

NOW = datetime(2026, 10, 8, 7, 5, tzinfo=JST)
OK_CANARY = {"ran_at": "2026-10-08T07:00:00+09:00", "ok": True, "checks": {"line_webhook": "ok"}}


def summary(received, ok, failed, last="2026-10-07T20:15:00+09:00"):
    return {"date": "2026-10-07", "received": received, "ok": ok, "failed": failed, "last_received_at": last}


def test_report_normal_day():
    text = build_morning_report(summary(3, 3, 0), OK_CANARY, NOW)
    assert text.startswith("✅")
    assert "受信3件 / 成功3件 / 失敗0件" in text
    assert "10/07 20:15" in text and "異常は検知されていません" in text


def test_report_no_usage_is_distinct_from_normal():
    text = build_morning_report(summary(0, 0, 0, last=None), OK_CANARY, NOW)
    assert text.startswith("ℹ️")
    assert "昨日の利用はありませんでした" in text and "最後の受信：なし" in text


def test_report_failures_warn():
    text = build_morning_report(summary(3, 2, 1), OK_CANARY, NOW)
    assert text.startswith("⚠️") and "昨日の失敗が1件" in text


def test_report_stale_missing_and_failing_canary_warn():
    stale = {"ran_at": "2026-10-08T05:00:00+09:00", "ok": True, "checks": {}}
    assert "止まっています" in build_morning_report(summary(1, 1, 0), stale, NOW)
    assert "未実行" in build_morning_report(summary(1, 1, 0), {}, NOW)
    failing = {"ran_at": "2026-10-08T07:00:00+09:00", "ok": False,
               "checks": {"gemini": "fail: x", "line_webhook": "ok"}}
    text = build_morning_report(summary(1, 1, 0), failing, NOW)
    assert text.startswith("⚠️") and "gemini" in text and "失敗しています" in text


def test_send_morning_report_is_idempotent():
    m, clock = make_monitor()
    clock.now = datetime(2026, 10, 8, 7, 5, tzinfo=JST)
    m.run_canary()
    assert m.send_morning_report() is True
    assert m.send_morning_report() is False
    pushes = m.http.pushes()
    assert len(pushes) == 1 and "朝の確認" in pushes[0][2]["json"]["messages"][0]["text"]
    assert m.db.docs[("system", "morning_report")]["sent_date"] == "2026-10-08"


def test_failed_push_clears_the_stamp_so_it_retries():
    m, _ = make_monitor()
    m.http.routes[("POST", "/v2/bot/message/push")] = Resp(500, {})
    assert m.send_morning_report() is False
    assert m.db.docs[("system", "morning_report")]["sent_date"] == ""
    m.http.routes[("POST", "/v2/bot/message/push")] = Resp(200, {})
    assert m.send_morning_report() is True


def test_summary_failure_leaves_no_stamp():
    m, _ = make_monitor()

    def boom():
        raise RuntimeError("x")

    m.yesterday_summary = boom
    with pytest.raises(RuntimeError):
        m.send_morning_report()
    assert ("system", "morning_report") not in m.db.docs


def names(spawned):
    return [getattr(f, "__name__", "") for f in spawned]


@pytest.mark.parametrize("hour,minute,expected", [(6, 59, False), (7, 0, True), (7, 29, True), (7, 30, False)])
def test_report_window_boundaries(hour, minute, expected):
    spawned = []
    m, clock = make_monitor(spawn=spawned.append)
    clock.now = datetime(2026, 10, 8, hour, minute, tzinfo=JST)
    m.get_status()
    assert ("_send_morning_report_guarded" in names(spawned)) is expected


def test_no_report_without_staff_user():
    spawned = []
    m, clock = make_monitor(alert_user_id=None, spawn=spawned.append)
    clock.now = datetime(2026, 10, 8, 7, 10, tzinfo=JST)
    m.get_status()
    assert "_send_morning_report_guarded" not in names(spawned)


def test_repeated_pings_in_window_send_only_one_report():
    m, clock = make_monitor()  # synchronous spawn
    clock.now = datetime(2026, 10, 8, 7, 10, tzinfo=JST)
    m.get_status()
    m.get_status()
    assert len(m.http.pushes()) == 1


def test_concurrent_pings_start_only_one_report_thread():
    spawned = []
    m, clock = make_monitor(spawn=spawned.append)
    clock.now = datetime(2026, 10, 8, 7, 10, tzinfo=JST)
    m.get_status()
    m.get_status()
    assert names(spawned).count("_send_morning_report_guarded") == 1
