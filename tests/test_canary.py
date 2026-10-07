from tests.fakes import Resp, make_monitor

WEBHOOK_URL = ("GET", "/v2/bot/channel/webhook/endpoint")
WEBHOOK_TEST = ("POST", "/v2/bot/channel/webhook/test")
VALIDATE = ("POST", "/v2/bot/message/validate/reply")
GOOD_CLASSIFY = {"type": "食事", "calories": 500}


def test_canary_all_ok_saves_result():
    m, clock = make_monitor()
    r = m.run_canary()
    assert r["ok"] is True
    assert r["checks"] == {"line_webhook": "ok", "line_reply_api": "ok", "gemini": "ok", "firestore": "ok"}
    assert r["consecutive_failures"] == 0 and r["last_ok_at"] == clock.now.isoformat()
    assert m.db.docs[("system", "canary")]["ok"] is True


def test_canary_detects_inactive_webhook():
    m, _ = make_monitor()
    m.http.routes[WEBHOOK_URL] = Resp(200, {"endpoint": "https://example.test/callback", "active": False})
    r = m.run_canary()
    assert r["ok"] is False and r["checks"]["line_webhook"].startswith("fail")


def test_canary_detects_wrong_endpoint_url():
    m, _ = make_monitor()
    m.http.routes[WEBHOOK_URL] = Resp(200, {"endpoint": "https://old.ngrok.app/callback", "active": True})
    r = m.run_canary()
    assert r["checks"]["line_webhook"].startswith("fail") and "old.ngrok.app" in r["checks"]["line_webhook"]


def test_canary_detects_failing_webhook_test():
    m, _ = make_monitor()
    m.http.routes[WEBHOOK_TEST] = Resp(200, {"success": False, "statusCode": 500, "reason": "Internal"})
    assert m.run_canary()["checks"]["line_webhook"].startswith("fail")


def test_validate_endpoint_missing_is_skipped_not_failure():
    m, _ = make_monitor()
    m.http.routes[VALIDATE] = Resp(404, {})
    r = m.run_canary()
    assert r["checks"]["line_reply_api"] == "skipped" and r["ok"] is True


def test_validate_unauthorized_is_failure():
    m, _ = make_monitor()
    m.http.routes[VALIDATE] = Resp(401, {})
    r = m.run_canary()
    assert r["checks"]["line_reply_api"].startswith("fail") and r["ok"] is False


def test_gemini_wrong_shape_and_exception_are_failures():
    m, _ = make_monitor(classify=lambda t: {"type": "その他"})
    assert m.run_canary()["checks"]["gemini"].startswith("fail")

    def boom(t):
        raise RuntimeError("quota")

    m2, _ = make_monitor(classify=boom)
    assert "RuntimeError" in m2.run_canary()["checks"]["gemini"]


def test_gemini_is_checked_at_most_once_per_hour():
    calls = []

    def classify(t):
        calls.append(t)
        return GOOD_CLASSIFY

    m, clock = make_monitor(classify=classify)
    m.run_canary()
    clock.advance(minutes=10)
    m.run_canary()
    assert len(calls) == 1
    clock.advance(minutes=51)
    m.run_canary()
    assert len(calls) == 2


def test_failed_gemini_check_is_retried_after_thirty_minutes():
    state = {"ok": False}
    calls = []

    def classify(t):
        calls.append(t)
        return GOOD_CLASSIFY if state["ok"] else {"type": "x"}

    m, clock = make_monitor(classify=classify)
    assert m.run_canary()["checks"]["gemini"].startswith("fail")
    state["ok"] = True
    clock.advance(minutes=15)
    r = m.run_canary()
    assert len(calls) == 1 and r["checks"]["gemini"].startswith("fail")  # carried forward, not re-checked yet
    clock.advance(minutes=16)
    r = m.run_canary()
    assert len(calls) == 2
    assert r["checks"]["gemini"] == "ok" and r["ok"] is True and r["consecutive_failures"] == 0


def test_firestore_outage_does_not_trigger_extra_gemini_calls():
    calls = []

    def classify(t):
        calls.append(t)
        return GOOD_CLASSIFY

    m, clock = make_monitor(classify=classify)
    m.run_canary()
    m.db.fail = True
    clock.advance(minutes=15)
    m.run_canary()
    assert len(calls) == 1


def test_firestore_outage_still_alerts_on_second_consecutive_run():
    m, clock = make_monitor()
    m.db.fail = True
    m.run_canary()
    assert m.http.pushes() == []
    clock.advance(minutes=15)
    m.run_canary()
    assert len(m.http.pushes()) == 1


def test_canary_survives_firestore_outage():
    m, _ = make_monitor()
    m.db.fail = True
    r = m.run_canary()  # must not raise
    assert r["ok"] is False and r["checks"]["firestore"].startswith("fail")


def test_alert_only_from_second_consecutive_failure_and_rate_limited():
    m, clock = make_monitor()
    m.http.routes[WEBHOOK_URL] = Resp(200, {"endpoint": "https://example.test/callback", "active": False})
    m.run_canary()
    assert m.http.pushes() == []
    clock.advance(minutes=15)
    m.run_canary()
    assert len(m.http.pushes()) == 1
    assert "line_webhook" in m.http.pushes()[0][2]["json"]["messages"][0]["text"]
    clock.advance(minutes=15)
    m.run_canary()
    assert len(m.http.pushes()) == 1  # still within the 30-minute window


def test_unexpected_crash_is_recorded_and_lock_released():
    m, _ = make_monitor()

    def boom():
        raise RuntimeError("x")

    m.run_canary = boom
    m._canary_running = True
    m._run_canary_guarded()
    saved = m.db.docs[("system", "canary")]
    assert saved["ok"] is False and saved["checks"] == {"canary": "fail: RuntimeError"}
    assert m._canary_running is False
