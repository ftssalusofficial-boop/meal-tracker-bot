from tests.fakes import Resp, make_monitor


def test_alert_sends_push_to_staff_and_stamps():
    m, clock = make_monitor()
    assert m.alert_staff("k", "hello") is True
    pushes = m.http.pushes()
    assert len(pushes) == 1
    assert pushes[0][2]["json"]["to"] == "Ustaff"
    assert pushes[0][2]["json"]["messages"][0]["text"] == "hello"
    assert m.db.docs[("system", "alerts")]["k"] == clock.now.isoformat()


def test_alert_is_rate_limited_per_key():
    m, clock = make_monitor()
    assert m.alert_staff("k", "1") is True
    clock.advance(minutes=29)
    assert m.alert_staff("k", "2") is False
    assert m.alert_staff("other", "3") is True  # different key is independent
    clock.advance(minutes=2)
    assert m.alert_staff("k", "4") is True
    assert len(m.http.pushes()) == 3


def test_alert_disabled_without_staff_user():
    m, _ = make_monitor(alert_user_id=None)
    assert m.alert_staff("k", "hello") is False
    assert m.http.calls == []


def test_alert_push_failure_does_not_stamp_and_retries():
    m, _ = make_monitor()
    m.http.routes[("POST", "/v2/bot/message/push")] = Resp(429, {})
    assert m.alert_staff("k", "hello") is False
    assert ("system", "alerts") not in m.db.docs
    m.http.routes[("POST", "/v2/bot/message/push")] = Resp(200, {})
    assert m.alert_staff("k", "hello") is True


def test_alert_push_network_error_is_swallowed():
    m, _ = make_monitor()
    m.http.routes[("POST", "/v2/bot/message/push")] = ConnectionError("down")
    assert m.alert_staff("k", "hello") is False


def test_daily_alert_cap_protects_the_push_quota():
    m, clock = make_monitor()
    sent = sum(1 for i in range(10) if m.alert_staff(f"k{i}", "x"))  # distinct keys: only the cap limits
    assert sent == 4
    clock.advance(days=1)
    assert m.alert_staff("again", "x") is True


def test_alert_still_sent_once_when_firestore_is_down():
    m, _ = make_monitor()
    m.db.fail = True
    assert m.alert_staff("k", "hello") is True
    assert m.alert_staff("k", "again") is False  # in-memory rate limit holds
    assert len(m.http.pushes()) == 1
