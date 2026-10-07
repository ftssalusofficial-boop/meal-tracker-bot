from datetime import datetime

from tests.fakes import JST, Resp, make_monitor

OK_REPLY = {"ok": True, "via": "reply", "status": 200}


def test_first_call_is_warming_up_then_ok():
    m, _ = make_monitor()  # synchronous spawn: the canary runs during the first call
    payload, code = m.get_status()
    assert (payload["state"], code) == ("warming_up", 200)
    payload, code = m.get_status()
    assert (payload["state"], code) == ("ok", 200)
    assert payload["canary_ok"] is True and payload["alerts_configured"] is True


def test_failing_canary_returns_503_after_warmup():
    m, clock = make_monitor()
    m.http.routes[("GET", "/v2/bot/channel/webhook/endpoint")] = Resp(
        200, {"endpoint": "https://example.test/callback", "active": False})
    m.get_status()
    clock.advance(minutes=11)
    payload, code = m.get_status()
    assert (payload["state"], code) == ("failing", 503)


def test_stale_canary_returns_503_and_requests_a_new_run():
    spawned = []
    m, clock = make_monitor(spawn=spawned.append)
    m.run_canary()
    clock.advance(minutes=50)
    payload, code = m.get_status()
    assert (payload["state"], code) == ("stale", 503)
    assert len(spawned) == 1


def test_hung_canary_is_restarted_after_five_minutes():
    spawned = []
    m, clock = make_monitor(spawn=spawned.append)  # the spawned canary never finishes
    m.get_status()
    assert len(spawned) == 1
    clock.advance(minutes=4)
    m.get_status()
    assert len(spawned) == 1  # still considered running
    clock.advance(minutes=2)
    m.get_status()
    assert len(spawned) == 2  # watchdog starts a replacement


def test_no_data_after_warmup_returns_503():
    m, clock = make_monitor(spawn=lambda fn: None)
    clock.advance(minutes=11)
    payload, code = m.get_status()
    assert (payload["state"], code) == ("no_data", 503)


def test_concurrent_pings_start_only_one_canary():
    spawned = []
    m, _ = make_monitor(spawn=spawned.append)
    m.get_status()
    m.get_status()
    assert len(spawned) == 1


def test_detail_includes_yesterday_summary():
    m, clock = make_monitor(spawn=lambda fn: None)
    clock.now = datetime(2026, 10, 7, 10, 0, tzinfo=JST)
    m.record_event("U1", "text", "ok", 5, OK_REPLY, None)
    clock.now = datetime(2026, 10, 8, 12, 0, tzinfo=JST)
    payload, _ = m.get_status(detail=True)
    assert payload["yesterday"]["received"] == 1


def test_status_survives_firestore_outage():
    m, _ = make_monitor(spawn=lambda fn: None)
    m.db.fail = True
    payload, code = m.get_status(detail=True)  # must not raise
    assert payload["yesterday"] is None
    assert code in (200, 503)


def test_alerts_configured_false_without_staff_user():
    m, _ = make_monitor(alert_user_id=None, spawn=lambda fn: None)
    payload, _ = m.get_status()
    assert payload["alerts_configured"] is False
