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


def test_error_field_never_contains_exception_message(env, monkeypatch):
    main, db, install = env
    install(make_http())

    def boom(text):
        raise RuntimeError("secret meal text")

    monkeypatch.setattr(main, "classify_and_analyze", boom)
    post(main, [text_event("ラーメン")])
    row = items(main, db)[0]
    assert row["error"] == "RuntimeError" and "secret meal text" not in row["error"]


def test_input_typos_are_not_failures_and_store_no_message_text(env, monkeypatch):
    main, db, install = env
    http = install(make_http())
    monkeypatch.setattr(main, "show_delete_list", lambda user_id: "list")
    assert post(main, [text_event("目標設定 にせん")]).status_code == 200
    assert post(main, [text_event("削除 abc")]).status_code == 200
    rows = items(main, db)
    assert len(rows) == 2
    assert all(r["outcome"] == "ok" and not r["error"] for r in rows)
    assert staff_pushes(http) == []


def test_message_without_user_id_is_ignored(env):
    main, db, install = env
    http = install(make_http())
    event = {"type": "message", "replyToken": "rt", "source": {"type": "group", "groupId": "G1"},
             "message": {"type": "text", "id": "m1", "text": "hello"}}
    assert post(main, [event]).status_code == 200
    assert items(main, db) == [] and staff_pushes(http) == []


def test_gemini_generate_attempts_parameter(env, monkeypatch):
    main, db, install = env
    calls = []

    class Models:
        def generate_content(self, **kw):
            calls.append(1)
            raise RuntimeError("boom")

    class Client:
        models = Models()

    monkeypatch.setattr(main, "client", Client())
    monkeypatch.setattr(main.time, "sleep", lambda s: None)
    with pytest.raises(RuntimeError):
        main.gemini_generate("p", attempts=1)
    assert len(calls) == 1
    calls.clear()
    with pytest.raises(RuntimeError):
        main.gemini_generate("p")
    assert len(calls) == 3


def test_canary_gemini_check_uses_a_single_attempt(env, monkeypatch):
    main, db, install = env
    seen = []
    monkeypatch.setattr(
        main, "classify_and_analyze",
        lambda t, attempts=3: seen.append(attempts) or {"type": "食事", "calories": 1})
    main.monitor.classify_fn("ラーメン")
    assert seen == [1]


VALID_MEAL = '{"type":"食事","dish":"ラーメン","calories":500,"protein":20,"fat":15,"carbs":60}'
NULL_MEAL = '{"type":"食事","dish":"ラーメン","calories":null,"protein":null,"fat":null,"carbs":null}'


def fake_gemini(responses, calls):
    def fake(prompt, image_bytes=None, attempts=3):
        calls.append(attempts)
        item = responses[min(len(calls) - 1, len(responses) - 1)]
        if isinstance(item, Exception):
            raise item
        return item
    return fake


def test_analysis_with_null_numbers_is_retried(env, monkeypatch):
    main, db, install = env
    calls = []
    monkeypatch.setattr(main, "gemini_generate", fake_gemini([NULL_MEAL, VALID_MEAL], calls))
    monkeypatch.setattr(main.time, "sleep", lambda s: None)
    data = main.classify_and_analyze("ラーメン")
    assert data["calories"] == 500 and len(calls) == 2


def test_analysis_with_null_numbers_raises_after_all_attempts(env, monkeypatch):
    main, db, install = env
    calls = []
    monkeypatch.setattr(main, "gemini_generate", fake_gemini([NULL_MEAL], calls))
    monkeypatch.setattr(main.time, "sleep", lambda s: None)
    with pytest.raises(ValueError):
        main.classify_and_analyze("ラーメン", attempts=2)
    assert len(calls) == 2


def test_exercise_with_null_calories_is_retried_and_api_errors_too(env, monkeypatch):
    main, db, install = env
    calls = []
    bad = '{"type":"運動","exercise":"ウォーキング","burned_calories":null}'
    good = '{"type":"運動","exercise":"ウォーキング","burned_calories":120}'
    monkeypatch.setattr(main, "gemini_generate", fake_gemini([RuntimeError("api"), bad, good], calls))
    monkeypatch.setattr(main.time, "sleep", lambda s: None)
    assert main.classify_and_analyze("ウォーキング")["burned_calories"] == 120
    assert len(calls) == 3


def test_non_meal_types_need_no_numbers(env, monkeypatch):
    main, db, install = env
    calls = []
    monkeypatch.setattr(main, "gemini_generate", fake_gemini(['{"type":"合計確認"}'], calls))
    assert main.classify_and_analyze("今日の合計") == {"type": "合計確認"}
    assert len(calls) == 1


def test_save_meal_rejects_missing_numbers_and_writes_nothing(env):
    main, db, install = env
    with pytest.raises(ValueError):
        main.save_meal("Uuser1", {"dish": "x", "calories": 1200, "protein": None, "fat": None, "carbs": None})
    with pytest.raises(ValueError):
        main.save_exercise("Uuser1", {"exercise": "x", "burned_calories": None})
    assert db.docs == {}


def test_daily_totals_tolerate_stored_nulls(env):
    main, db, install = env
    today = datetime.now(main.JST).strftime("%Y-%m-%d")
    col = db.collection("meals").document("Uuser1").collection(today)
    col.document("a").set({"dish": "x", "calories": 1200, "protein": None, "fat": None, "carbs": None})
    col.document("b").set({"dish": "y", "calories": 300, "protein": 10, "fat": 5, "carbs": 40})
    total = main.get_daily_total("Uuser1")
    assert total == {"calories": 1500, "protein": 10, "fat": 5, "carbs": 40}


def test_null_analysis_from_ai_gives_retry_message_not_a_saved_record(env, monkeypatch):
    main, db, install = env
    install(make_http())
    monkeypatch.setattr(main, "classify_and_analyze",
                        lambda t, attempts=3: {"type": "食事", "dish": "ラーメン", "calories": None,
                                               "protein": None, "fat": None, "carbs": None})
    assert post(main, [text_event("ラーメン")]).status_code == 200
    today = datetime.now(main.JST).strftime("%Y-%m-%d")
    assert docs_under(db, "meals", "Uuser1", today) == []
    assert items(main, db)[0]["outcome"] == "handler_error"


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
