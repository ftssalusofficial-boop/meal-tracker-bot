import importlib
import json
import sys
from datetime import datetime

import pytest

from tests.fakes import FakeDb, FakeHttp, Resp, docs_under


@pytest.fixture(scope="module")
def app_module():
    mp = pytest.MonkeyPatch()
    mp.setenv("LINE_CHANNEL_ACCESS_TOKEN", "tok")
    mp.setenv("GEMINI_API_KEY", "gem")
    mp.setenv("FIREBASE_CREDENTIALS", json.dumps({"project_id": "test"}))
    mp.setenv("ALERT_LINE_USER_ID", "Ustaff")
    mp.setenv("PUBLIC_BASE_URL", "https://example.test")
    import firestore_rest

    db = FakeDb()
    mp.setattr(firestore_rest, "client", lambda cred: db)
    sys.modules.pop("main", None)
    main = importlib.import_module("main")
    yield main, db
    mp.undo()
    sys.modules.pop("main", None)


@pytest.fixture
def env(app_module, monkeypatch):
    main, db = app_module
    db.docs.clear()
    db.fail = False
    monitor = main.monitor
    monitor._alert_last.clear()
    monitor._cache = None
    monitor._canary_running = False
    monitor._ran_this_process = False
    monitor._started_at = datetime.now(main.JST)
    monkeypatch.setattr(monitor, "_spawn", lambda fn: None)

    def install(http):
        monkeypatch.setattr(main, "requests", http)
        monkeypatch.setattr(monitor, "http", http)
        return http

    return main, db, install


def make_http(reply_status=200, user_push_status=200):
    def push(kw):
        return Resp(user_push_status if kw["json"]["to"] == "Uuser1" else 200, {})

    return FakeHttp({
        ("POST", "/v2/bot/message/reply"): Resp(reply_status, {}),
        ("POST", "/v2/bot/message/push"): push,
        ("POST", "/v2/bot/chat/loading/start"): Resp(202, {}),
        ("GET", "/v2/bot/profile/Uuser1"): Resp(200, {"displayName": "テスト", "pictureUrl": ""}),
    })


def text_event(text="使い方"):
    return {"type": "message", "replyToken": "rt", "source": {"userId": "Uuser1"},
            "message": {"type": "text", "id": "m1", "text": text}}


def items(main, db):
    return docs_under(db, "bot_events", datetime.now(main.JST).strftime("%Y-%m-%d"), "items")


def staff_pushes(http):
    return [c for c in http.pushes() if c[2]["json"]["to"] == "Ustaff"]


def post(main, events):
    return main.app.test_client().post("/callback", json={"events": events})


def test_normal_message_is_logged_as_ok(env, monkeypatch):
    main, db, install = env
    http = install(make_http())
    monkeypatch.setattr(main, "classify_and_analyze", lambda t: {"type": "使い方"})
    assert post(main, [text_event()]).status_code == 200
    rows = items(main, db)
    assert len(rows) == 1
    assert rows[0]["outcome"] == "ok" and rows[0]["kind"] == "text" and rows[0]["reply_via"] == "reply"
    assert "text" not in rows[0] and staff_pushes(http) == []


def test_rejected_reply_token_falls_back_to_push_and_is_ok(env, monkeypatch):
    main, db, install = env
    install(make_http(reply_status=400))
    monkeypatch.setattr(main, "classify_and_analyze", lambda t: {"type": "使い方"})
    post(main, [text_event()])
    row = items(main, db)[0]
    assert row["outcome"] == "ok" and row["reply_via"] == "push"


def test_reply_and_push_both_failing_alerts_staff(env, monkeypatch):
    main, db, install = env
    http = install(make_http(reply_status=400, user_push_status=429))
    monkeypatch.setattr(main, "classify_and_analyze", lambda t: {"type": "使い方"})
    assert post(main, [text_event()]).status_code == 200
    assert items(main, db)[0]["outcome"] == "reply_failed"
    alerts = staff_pushes(http)
    assert len(alerts) == 1 and "テスト" in alerts[0][2]["json"]["messages"][0]["text"]


def test_handler_error_is_recorded_and_alerted(env, monkeypatch):
    main, db, install = env
    http = install(make_http())

    def boom(text):
        raise RuntimeError("gemini down")

    monkeypatch.setattr(main, "classify_and_analyze", boom)
    assert post(main, [text_event("ラーメン")]).status_code == 200
    row = items(main, db)[0]
    assert row["outcome"] == "handler_error" and "RuntimeError" in row["error"]
    assert len(staff_pushes(http)) == 1


def test_empty_events_record_nothing(env):
    main, db, install = env
    install(make_http())
    assert post(main, []).status_code == 200
    assert items(main, db) == []


def test_unfollow_and_userless_events_are_ignored(env):
    main, db, install = env
    install(make_http())
    events = [{"type": "unfollow", "source": {"userId": "Uuser1"}}, {"type": "join"}]
    assert post(main, events).status_code == 200
    assert items(main, db) == []


def test_follow_event_is_logged(env):
    main, db, install = env
    install(make_http())
    event = {"type": "follow", "replyToken": "rt", "source": {"userId": "Uuser1"}}
    assert post(main, [event]).status_code == 200
    row = items(main, db)[0]
    assert row["kind"] == "follow" and row["outcome"] == "ok"


def test_status_endpoint_returns_json(env):
    main, db, install = env
    install(make_http())
    r = main.app.test_client().get("/status")
    assert r.status_code == 200
    assert r.get_json()["state"] == "warming_up"
