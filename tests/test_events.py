from datetime import datetime

from tests.fakes import JST, docs_under, make_monitor

OK_REPLY = {"ok": True, "via": "reply", "status": 200}


def test_record_event_stores_metadata_only():
    m, clock = make_monitor()
    m.record_event("Uabc", "text", "ok", 123.7, OK_REPLY, None)
    items = docs_under(m.db, "bot_events", "2026-10-08", "items")
    assert len(items) == 1
    item = items[0]
    assert item["user_id"] == "Uabc" and item["kind"] == "text" and item["outcome"] == "ok"
    assert item["duration_ms"] == 123
    assert item["reply_via"] == "reply" and item["reply_status"] == 200
    assert item["ts"] == clock.now.isoformat()
    assert "text" not in item and "message" not in item


def test_record_event_without_reply_and_error_is_truncated():
    m, _ = make_monitor()
    m.record_event("Uabc", "text", "handler_error", 5, None, "x" * 500)
    item = docs_under(m.db, "bot_events", "2026-10-08", "items")[0]
    assert item["reply_via"] is None and item["reply_status"] is None
    assert len(item["error"]) == 200


def test_record_event_swallows_firestore_failure():
    m, _ = make_monitor()
    m.db.fail = True
    m.record_event("Uabc", "text", "ok", 5, OK_REPLY, None)  # must not raise


def test_yesterday_summary_counts_and_midnight_rollover():
    m, clock = make_monitor()
    clock.now = datetime(2026, 10, 7, 23, 59, tzinfo=JST)
    m.record_event("U1", "text", "ok", 10, OK_REPLY, None)
    m.record_event("U2", "text", "handler_error", 10, None, "boom")
    clock.now = datetime(2026, 10, 8, 0, 1, tzinfo=JST)
    m.record_event("U3", "text", "ok", 10, OK_REPLY, None)  # today: not counted
    assert m.yesterday_summary() == {
        "date": "2026-10-07",
        "received": 2,
        "ok": 1,
        "failed": 1,
        "last_received_at": "2026-10-07T23:59:00+09:00",
    }


def test_yesterday_summary_empty():
    m, _ = make_monitor()
    assert m.yesterday_summary() == {
        "date": "2026-10-07", "received": 0, "ok": 0, "failed": 0, "last_received_at": None,
    }
