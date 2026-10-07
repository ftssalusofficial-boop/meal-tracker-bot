# Monitoring, Instant Alerts and Morning Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the LINE meal bot report its own failures immediately, prove its health with a periodic canary, and send a morning report based on real activity instead of a bare `/health` check.

**Architecture:** A new `monitoring.py` holds all monitoring logic in one `Monitor` class with injected dependencies (Firestore client, HTTP client, clock, Gemini classify function, thread spawner) so it is fully unit-testable with in-memory fakes. `main.py` is wired to it: each LINE event is wrapped so its outcome is recorded and failures alert the staff; a new `/status` endpoint (hit every ~5 min by UptimeRobot) lazily starts the canary and the 07:00 JST morning report in background threads.

**Tech Stack:** Python 3.11, Flask 3.1, requests, Firestore REST shim (`firestore_rest.py`), pytest (dev only).

**Spec:** `docs/superpowers/specs/2026-10-07-monitoring-and-alerting-design.md` (read it first; this plan implements it). Later, separate spec: `2026-10-07-meal-bot-hardening-design.md` (not part of this plan).

## Global Constraints

- Cost stays 0 yen: no new paid service, no new runtime dependency (`requests`/`flask` only; `pytest` is dev-only in `requirements-dev.txt`).
- Python 3.11 (`runtime.txt` = `python-3.11.9`). All timestamps are JST (`timezone(timedelta(hours=9))`), stored as `datetime.isoformat()` strings.
- Monitoring/logging/alerting failures must never block or alter the user-facing reply: every monitoring call is wrapped so exceptions are printed (`traceback.print_exc()`) and swallowed.
- `bot_events` documents never contain message text; `error` is truncated to 200 characters.
- Canary interval 15 min; Gemini canary check at most once per 60 min (re-checked on the next run if the last Gemini check failed); `/status` state `ok` requires the last canary result to be successful and at most 45 min old; warm-up window 10 min after process start; alert rate limit 30 min per key; morning report window 07:00 (inclusive) to 07:30 (exclusive) JST.
- Canary failure alert fires only on the 2nd consecutive failure and after.
- LINE push is used only for failure alerts and the single morning report (free plan quota is 200/month; 7 used at planning time).
- `.env` is never committed. Do not put `ALERT_LINE_USER_ID` into the local `.env` (a local run would then push to the staff).
- Commit messages end with the trailer `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. Do not `git push` before Task 8.

## Review Focus

1. LINE sends events that are neither `follow` nor `message` (e.g. `unfollow`) or lack `source.userId`: must return 200, record nothing, not crash. (pinned in Task 7)
2. Firestore is down while recording an event, alerting, or running the canary: replies still go out, nothing raises. (Tasks 2, 3, 4, 5)
3. UptimeRobot and the GitHub keep-alive ping `/status` at the same moment: only one canary and at most one morning report may start. (Tasks 5, 6)
4. Time boundaries: 06:59/07:00/07:29/07:30 for the report window, and "yesterday" computed in JST across midnight. (Tasks 2, 6)
5. The alert push itself fails (HTTP 429 quota, network error): no crash, no rate-limit stamp, so the next failure retries. (Task 3)

---

## File Structure

- Create `monitoring.py` — `Monitor` class + `build_morning_report()`; no Flask, no Firestore/HTTP imports (all injected).
- Create `tests/__init__.py`, `tests/fakes.py` (FakeDb, FakeHttp, Resp, Clock, `make_monitor`, `docs_under`), `tests/test_fakes.py`, `tests/test_events.py`, `tests/test_alerts.py`, `tests/test_canary.py`, `tests/test_status.py`, `tests/test_morning.py`, `tests/test_callback_integration.py`.
- Create `pytest.ini`, `requirements-dev.txt`.
- Modify `main.py` — `push_message`/`reply_message` return results; `log_error`; per-event `process_event`/`handle_event`; `monitor` wiring; `/status`.
- Modify `.github/workflows/keep-alive.yml`, delete `.github/workflows/morning-health-check.yml`, modify `render.yaml` (Task 8).

---

### Task 1: Test infrastructure and fakes

**Files:**
- Create: `pytest.ini`, `requirements-dev.txt`, `tests/__init__.py`, `tests/fakes.py`, `tests/test_fakes.py`

**Interfaces:**
- Produces (used by all later tasks):
  - `tests.fakes.JST`, `Clock(start=None)` (callable returning aware datetime; `.now`, `.advance(**timedelta_kwargs)`; default start `2026-10-08 12:00 JST`)
  - `FakeDb` (`.docs` dict keyed by path tuple, `.fail` bool, `.collection(name)`; refs support `.document(id=None)`, `.collection()`, `.get()`, `.set()`, `.update()`, `.delete()`, `.stream()`)
  - `docs_under(db, *path) -> list[dict]` (data of documents directly under a collection path)
  - `Resp(status_code=200, data=None)`, `FakeHttp(routes)` with `.get/.post(url, **kw)`, `.calls`, `.pushes()`; route key `(METHOD, url_suffix)` -> `Resp` | callable(kw)->`Resp` | `Exception` instance (raised)
  - `healthy_http(base="https://example.test")`
  - `make_monitor(db=None, http=None, clock=None, alert_user_id="Ustaff", classify=None, spawn=None) -> (monitor, clock)`

- [ ] **Step 1: Install pytest and create config files**

Run (PowerShell, repo root):
```powershell
.\venv\Scripts\python.exe -m pip install "pytest>=8,<9"
```

Create `requirements-dev.txt`:
```
-r requirements.txt
pytest>=8,<9
```

Create `pytest.ini`:
```ini
[pytest]
pythonpath = .
testpaths = tests
```

Create empty `tests/__init__.py`.

- [ ] **Step 2: Write the failing test** — `tests/test_fakes.py`

```python
from tests.fakes import Clock, FakeDb, FakeHttp, Resp, docs_under, healthy_http


def test_fake_db_roundtrip_stream_update_delete():
    db = FakeDb()
    ref = db.collection("a").document("x").collection("b").document("y")
    assert ref.get().exists is False
    ref.set({"n": 1})
    assert ref.get().to_dict() == {"n": 1}
    assert [s.id for s in db.collection("a").document("x").collection("b").stream()] == ["y"]
    assert db.collection("a").stream() == []  # parent docs are virtual
    ref.update({"m": 2})
    assert ref.get().to_dict() == {"n": 1, "m": 2}
    assert docs_under(db, "a", "x", "b") == [{"n": 1, "m": 2}]
    ref.delete()
    assert ref.get().exists is False


def test_fake_db_fail_flag_raises():
    db = FakeDb()
    db.fail = True
    try:
        db.collection("a").document("x").get()
        assert False, "expected RuntimeError"
    except RuntimeError:
        pass


def test_clock_advances():
    clock = Clock()
    start = clock()
    clock.advance(minutes=5)
    assert (clock() - start).total_seconds() == 300


def test_fake_http_routes_and_default_404():
    http = FakeHttp({("GET", "/ok"): Resp(200, {"a": 1})})
    assert http.get("https://x.test/ok").json() == {"a": 1}
    assert http.get("https://x.test/missing").status_code == 404
    assert len(http.calls) == 2


def test_healthy_http_records_pushes():
    http = healthy_http()
    http.post("https://api.line.me/v2/bot/message/push", json={"to": "U1", "messages": []})
    assert len(http.pushes()) == 1
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.\venv\Scripts\python.exe -m pytest tests/test_fakes.py -v`
Expected: FAIL / ERROR with `ModuleNotFoundError: No module named 'tests.fakes'`.

- [ ] **Step 4: Write `tests/fakes.py`**

```python
import itertools
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))
_counter = itertools.count(1)


class Clock:
    def __init__(self, start=None):
        self.now = start or datetime(2026, 10, 8, 12, 0, tzinfo=JST)

    def __call__(self):
        return self.now

    def advance(self, **kwargs):
        self.now += timedelta(**kwargs)


class _Snap:
    def __init__(self, doc_id, data):
        self.id = doc_id
        self._data = data
        self.exists = data is not None

    def to_dict(self):
        return dict(self._data) if self._data is not None else {}


class FakeDb:
    def __init__(self):
        self.docs = {}
        self.fail = False

    def _check(self):
        if self.fail:
            raise RuntimeError("firestore down")

    def collection(self, name):
        return _Col(self, (name,))


class _Col:
    def __init__(self, db, path):
        self.db = db
        self.path = path

    def document(self, doc_id=None):
        return _Doc(self.db, self.path + (doc_id or f"auto{next(_counter)}",))

    def stream(self):
        self.db._check()
        n = len(self.path)
        return [
            _Snap(p[-1], d)
            for p, d in self.db.docs.items()
            if len(p) == n + 1 and p[:n] == self.path
        ]


class _Doc:
    def __init__(self, db, path):
        self.db = db
        self.path = path

    @property
    def id(self):
        return self.path[-1]

    def collection(self, name):
        return _Col(self.db, self.path + (name,))

    def get(self):
        self.db._check()
        return _Snap(self.path[-1], self.db.docs.get(self.path))

    def set(self, data):
        self.db._check()
        self.db.docs[self.path] = dict(data)

    def update(self, data):
        self.db._check()
        self.db.docs[self.path] = {**self.db.docs.get(self.path, {}), **data}

    def delete(self):
        self.db._check()
        self.db.docs.pop(self.path, None)


def docs_under(db, *path):
    n = len(path)
    return [d for p, d in db.docs.items() if len(p) == n + 1 and p[:n] == tuple(path)]


class Resp:
    def __init__(self, status_code=200, data=None):
        self.status_code = status_code
        self._data = data if data is not None else {}

    def json(self):
        return self._data


class FakeHttp:
    def __init__(self, routes=None):
        self.routes = routes or {}
        self.calls = []

    def _do(self, method, url, **kw):
        self.calls.append((method, url, kw))
        for (m, suffix), handler in self.routes.items():
            if m == method and url.endswith(suffix):
                if isinstance(handler, Exception):
                    raise handler
                return handler(kw) if callable(handler) else handler
        return Resp(404, {})

    def get(self, url, **kw):
        return self._do("GET", url, **kw)

    def post(self, url, **kw):
        return self._do("POST", url, **kw)

    def pushes(self):
        return [c for c in self.calls if c[0] == "POST" and c[1].endswith("/message/push")]


def healthy_http(base="https://example.test"):
    return FakeHttp({
        ("GET", "/v2/bot/channel/webhook/endpoint"): Resp(200, {"endpoint": base + "/callback", "active": True}),
        ("POST", "/v2/bot/channel/webhook/test"): Resp(200, {"success": True, "statusCode": 200, "reason": "OK"}),
        ("POST", "/v2/bot/message/validate/reply"): Resp(200, {}),
        ("POST", "/v2/bot/message/push"): Resp(200, {}),
    })


def make_monitor(db=None, http=None, clock=None, alert_user_id="Ustaff", classify=None, spawn=None):
    from monitoring import Monitor

    clock = clock or Clock()
    monitor = Monitor(
        db=db or FakeDb(),
        http=http or healthy_http(),
        line_token="tok",
        alert_user_id=alert_user_id,
        public_base_url="https://example.test",
        classify_fn=classify or (lambda t: {"type": "食事", "dish": t, "calories": 500, "protein": 20, "fat": 10, "carbs": 60}),
        now_fn=clock,
        spawn=spawn or (lambda fn: fn()),
    )
    return monitor, clock
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.\venv\Scripts\python.exe -m pytest tests/test_fakes.py -v`
Expected: 5 passed.

- [ ] **Step 6: Commit**

```bash
git add pytest.ini requirements-dev.txt tests/__init__.py tests/fakes.py tests/test_fakes.py
git commit -m "Add pytest infrastructure and in-memory fakes" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Event log (`record_event`, `yesterday_summary`)

**Files:**
- Create: `monitoring.py`
- Test: `tests/test_events.py`

**Interfaces:**
- Consumes: `tests.fakes` from Task 1.
- Produces: `monitoring.Monitor.__init__(db, http, line_token, alert_user_id, public_base_url, classify_fn, now_fn, spawn=None)`; `Monitor.record_event(user_id, kind, outcome, duration_ms, reply, error=None) -> None` (never raises); `Monitor.yesterday_summary() -> {"date", "received", "ok", "failed", "last_received_at"}`; module constants and `_parse(iso)` used by later tasks.

- [ ] **Step 1: Write the failing test** — `tests/test_events.py`

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\venv\Scripts\python.exe -m pytest tests/test_events.py -v`
Expected: ERROR `ModuleNotFoundError: No module named 'monitoring'`.

- [ ] **Step 3: Create `monitoring.py`**

```python
import threading
import traceback
from datetime import datetime, timedelta

LINE_API = "https://api.line.me"
CANARY_INTERVAL_MIN = 15
GEMINI_CHECK_INTERVAL_MIN = 60
STATUS_OK_MAX_AGE_MIN = 45
WARMUP_MIN = 10
ALERT_INTERVAL_MIN = 30
MORNING_START_MIN = 7 * 60
MORNING_END_MIN = 7 * 60 + 30
STATUS_CACHE_SEC = 30


def _parse(iso):
    return datetime.fromisoformat(iso) if iso else None


class Monitor:
    def __init__(self, db, http, line_token, alert_user_id, public_base_url,
                 classify_fn, now_fn, spawn=None):
        self.db = db
        self.http = http
        self.line_token = line_token
        self.alert_user_id = alert_user_id
        self.public_base_url = public_base_url.rstrip("/")
        self.classify_fn = classify_fn
        self._now = now_fn
        self._spawn = spawn or self._spawn_thread
        self._started_at = now_fn()
        self._lock = threading.Lock()
        self._canary_running = False
        self._report_running = False
        self._ran_this_process = False
        self._cache = None
        self._alert_last = {}

    @staticmethod
    def _spawn_thread(fn):
        threading.Thread(target=fn, daemon=True).start()

    def _headers(self):
        return {"Authorization": f"Bearer {self.line_token}", "Content-Type": "application/json"}

    def record_event(self, user_id, kind, outcome, duration_ms, reply, error=None):
        try:
            now = self._now()
            date_str = now.strftime("%Y-%m-%d")
            reply = reply or {}
            self.db.collection("bot_events").document(date_str).collection("items").document().set({
                "ts": now.isoformat(),
                "user_id": user_id,
                "kind": kind,
                "outcome": outcome,
                "duration_ms": int(duration_ms),
                "reply_via": reply.get("via"),
                "reply_status": reply.get("status"),
                "error": (error or "")[:200],
            })
        except Exception:
            traceback.print_exc()

    def yesterday_summary(self):
        date_str = (self._now() - timedelta(days=1)).strftime("%Y-%m-%d")
        items = [s.to_dict() for s in self.db.collection("bot_events").document(date_str).collection("items").stream()]
        received = len(items)
        ok = sum(1 for i in items if i.get("outcome") == "ok")
        last = max((i.get("ts") for i in items), default=None)
        return {"date": date_str, "received": received, "ok": ok, "failed": received - ok, "last_received_at": last}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\venv\Scripts\python.exe -m pytest tests/test_events.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add monitoring.py tests/test_events.py
git commit -m "Add Monitor event log and yesterday summary" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Staff alerts with rate limiting

**Files:**
- Modify: `monitoring.py` (add `_push`, `alert_staff` to `Monitor`)
- Test: `tests/test_alerts.py`

**Interfaces:**
- Consumes: `Monitor` skeleton from Task 2.
- Produces: `Monitor._push(user_id, text) -> bool` (True only on HTTP 200, never raises); `Monitor.alert_staff(key, text) -> bool` (rate-limited 30 min per key; in-memory stamp in `self._alert_last` plus Firestore `system/alerts`).

- [ ] **Step 1: Write the failing test** — `tests/test_alerts.py`

```python
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


def test_alert_still_sent_once_when_firestore_is_down():
    m, _ = make_monitor()
    m.db.fail = True
    assert m.alert_staff("k", "hello") is True
    assert m.alert_staff("k", "again") is False  # in-memory rate limit holds
    assert len(m.http.pushes()) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\venv\Scripts\python.exe -m pytest tests/test_alerts.py -v`
Expected: FAIL with `AttributeError: 'Monitor' object has no attribute 'alert_staff'`.

- [ ] **Step 3: Add the methods to `Monitor` in `monitoring.py`** (append after `yesterday_summary`)

```python
    def _push(self, user_id, text):
        try:
            resp = self.http.post(
                f"{LINE_API}/v2/bot/message/push",
                headers=self._headers(),
                json={"to": user_id, "messages": [{"type": "text", "text": text[:2000]}]},
                timeout=10,
            )
            return resp.status_code == 200
        except Exception:
            traceback.print_exc()
            return False

    def alert_staff(self, key, text):
        if not self.alert_user_id:
            return False
        now = self._now()
        last = self._alert_last.get(key)
        try:
            doc = self.db.collection("system").document("alerts").get()
            stored = _parse((doc.to_dict() or {}).get(key)) if doc.exists else None
            if stored and (last is None or stored > last):
                last = stored
        except Exception:
            traceback.print_exc()
        if last and (now - last) < timedelta(minutes=ALERT_INTERVAL_MIN):
            return False
        if not self._push(self.alert_user_id, text):
            return False
        self._alert_last[key] = now
        try:
            self.db.collection("system").document("alerts").update({key: now.isoformat()})
        except Exception:
            traceback.print_exc()
        return True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\venv\Scripts\python.exe -m pytest tests/test_alerts.py tests/test_events.py -v`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add monitoring.py tests/test_alerts.py
git commit -m "Add rate-limited staff alerts" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Canary

**Files:**
- Modify: `monitoring.py` (canary methods)
- Modify: `docs/superpowers/specs/2026-10-07-monitoring-and-alerting-design.md` (one bullet, see Step 5)
- Test: `tests/test_canary.py`

**Interfaces:**
- Consumes: `Monitor._push`, `alert_staff` (Task 3), `_parse` and constants (Task 2).
- Produces: `Monitor.run_canary() -> dict` (never raises; saves to `system/canary`: `{ran_at, ok, checks, gemini_checked_at, consecutive_failures, last_ok_at}`); `Monitor._load_canary() -> dict`; `Monitor._load_canary_cached() -> dict`; `Monitor._run_canary_guarded()`; `Monitor._canary_running`, `_ran_this_process`, `_cache` attributes used by Task 5. Check values are `"ok"`, `"skipped"`, or `"fail: <reason>"`.

- [ ] **Step 1: Write the failing test** — `tests/test_canary.py`

```python
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


def test_failed_gemini_check_is_retried_on_next_run():
    state = {"ok": False}
    m, clock = make_monitor(classify=lambda t: GOOD_CLASSIFY if state["ok"] else {"type": "x"})
    assert m.run_canary()["checks"]["gemini"].startswith("fail")
    state["ok"] = True
    clock.advance(minutes=5)
    r = m.run_canary()
    assert r["checks"]["gemini"] == "ok" and r["ok"] is True and r["consecutive_failures"] == 0


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\venv\Scripts\python.exe -m pytest tests/test_canary.py -v`
Expected: FAIL with `AttributeError: 'Monitor' object has no attribute 'run_canary'`.

- [ ] **Step 3: Add the canary methods to `Monitor`** (append after `alert_staff`)

```python
    def _load_canary(self):
        doc = self.db.collection("system").document("canary").get()
        return doc.to_dict() if doc.exists else {}

    def _load_canary_cached(self):
        now = self._now()
        if self._cache and (now - self._cache[0]).total_seconds() < STATUS_CACHE_SEC:
            return self._cache[1]
        try:
            data = self._load_canary()
        except Exception:
            traceback.print_exc()
            data = self._cache[1] if self._cache else {}
        self._cache = (now, data)
        return data

    def _check_line_webhook(self):
        try:
            expected = self.public_base_url + "/callback"
            r = self.http.get(f"{LINE_API}/v2/bot/channel/webhook/endpoint", headers=self._headers(), timeout=10)
            if r.status_code != 200:
                return f"fail: endpoint api {r.status_code}"
            info = r.json()
            if not info.get("active"):
                return "fail: webhook inactive"
            if info.get("endpoint") != expected:
                return f"fail: endpoint is {info.get('endpoint')}"
            t = self.http.post(f"{LINE_API}/v2/bot/channel/webhook/test", headers=self._headers(),
                               json={"endpoint": expected}, timeout=30)
            body = t.json()
            if t.status_code != 200 or not body.get("success") or body.get("statusCode") != 200:
                return f"fail: webhook test {body.get('statusCode')} {body.get('reason')}"
            return "ok"
        except Exception as e:
            traceback.print_exc()
            return f"fail: {type(e).__name__}"

    def _check_reply_api(self):
        try:
            r = self.http.post(f"{LINE_API}/v2/bot/message/validate/reply", headers=self._headers(),
                               json={"messages": [{"type": "text", "text": "canary"}]}, timeout=10)
            if r.status_code == 200:
                return "ok"
            if r.status_code in (404, 405):
                return "skipped"
            return f"fail: validate {r.status_code}"
        except Exception as e:
            traceback.print_exc()
            return f"fail: {type(e).__name__}"

    def _check_gemini(self):
        try:
            data = self.classify_fn("ラーメン")
            calories = data.get("calories")
            if data.get("type") != "食事" or isinstance(calories, bool) or not isinstance(calories, (int, float)):
                return f"fail: unexpected result {str(data)[:80]}"
            return "ok"
        except Exception as e:
            traceback.print_exc()
            return f"fail: {type(e).__name__}"

    def _check_firestore(self):
        try:
            now = self._now().isoformat()
            ref = self.db.collection("system").document("canary_probe")
            ref.set({"ts": now})
            return "ok" if ref.get().to_dict().get("ts") == now else "fail: read-back mismatch"
        except Exception as e:
            return f"fail: {type(e).__name__}"

    def _gemini_due(self, prev, now):
        checked = _parse(prev.get("gemini_checked_at"))
        if checked is None or (prev.get("checks") or {}).get("gemini") != "ok":
            return True
        return (now - checked) >= timedelta(minutes=GEMINI_CHECK_INTERVAL_MIN)

    def _alert_canary_failure(self, failures, checks):
        bad = ", ".join(f"{k}: {v}" for k, v in checks.items() if v not in ("ok", "skipped"))
        self.alert_staff("canary_failure", f"⚠️ SALUS MEAL 自動テストが{failures}回連続で失敗しています。\n{bad}")

    def run_canary(self):
        now = self._now()
        try:
            prev = self._load_canary()
        except Exception:
            traceback.print_exc()
            prev = {}
        checks = {
            "line_webhook": self._check_line_webhook(),
            "line_reply_api": self._check_reply_api(),
        }
        if self._gemini_due(prev, now):
            checks["gemini"] = self._check_gemini()
            gemini_checked_at = now.isoformat()
        else:
            checks["gemini"] = (prev.get("checks") or {}).get("gemini", "ok")
            gemini_checked_at = prev.get("gemini_checked_at")
        checks["firestore"] = self._check_firestore()
        ok = all(v in ("ok", "skipped") for v in checks.values())
        failures = 0 if ok else int(prev.get("consecutive_failures") or 0) + 1
        result = {
            "ran_at": now.isoformat(),
            "ok": ok,
            "checks": checks,
            "gemini_checked_at": gemini_checked_at,
            "consecutive_failures": failures,
            "last_ok_at": now.isoformat() if ok else prev.get("last_ok_at"),
        }
        try:
            self.db.collection("system").document("canary").set(result)
        except Exception:
            traceback.print_exc()
        self._cache = (now, result)
        self._ran_this_process = True
        if failures >= 2:
            self._alert_canary_failure(failures, checks)
        return result

    def _record_canary_crash(self, exc):
        try:
            now = self._now()
            prev = self._load_canary()
            failures = int(prev.get("consecutive_failures") or 0) + 1
            checks = {"canary": f"fail: {type(exc).__name__}"}
            result = {
                "ran_at": now.isoformat(),
                "ok": False,
                "checks": checks,
                "gemini_checked_at": prev.get("gemini_checked_at"),
                "consecutive_failures": failures,
                "last_ok_at": prev.get("last_ok_at"),
            }
            self.db.collection("system").document("canary").set(result)
            self._cache = (now, result)
            if failures >= 2:
                self._alert_canary_failure(failures, checks)
        except Exception:
            traceback.print_exc()

    def _run_canary_guarded(self):
        try:
            self.run_canary()
        except Exception as e:
            traceback.print_exc()
            self._record_canary_crash(e)
        finally:
            with self._lock:
                self._canary_running = False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\venv\Scripts\python.exe -m pytest tests/ -v`
Expected: all passed.

- [ ] **Step 5: Reconcile the spec wording** — edit `docs/superpowers/specs/2026-10-07-monitoring-and-alerting-design.md`, replace the bullet

```
4. `firestore`: `system/canary` 自体の書き込みと読み戻しで確認。
```
with
```
4. `firestore`: `system/canary_probe` に現在時刻を書き込み、読み戻して一致を確認。
```

- [ ] **Step 6: Commit**

```bash
git add monitoring.py tests/test_canary.py docs/superpowers/specs/2026-10-07-monitoring-and-alerting-design.md
git commit -m "Add Monitor canary checks" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 5: `/status` logic (`get_status`)

**Files:**
- Modify: `monitoring.py` (add `get_status`, `_maybe_start_canary`)
- Test: `tests/test_status.py`

**Interfaces:**
- Consumes: `_load_canary_cached`, `_run_canary_guarded`, `_canary_running`, `_ran_this_process`, `yesterday_summary`.
- Produces: `Monitor.get_status(detail=False) -> (payload_dict, http_status_int)`. Payload keys: `state` (`ok`/`warming_up` => 200; `failing`/`stale`/`no_data` => 503), `ok`, `canary_ok`, `canary_age_min`, `last_ok_at`, `alerts_configured`, `checks`, and `yesterday` when `detail=True` (`None` if it cannot be computed). Task 6 adds a call to `self._maybe_start_morning_report(now)` inside `get_status`.

- [ ] **Step 1: Write the failing test** — `tests/test_status.py`

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\venv\Scripts\python.exe -m pytest tests/test_status.py -v`
Expected: FAIL with `AttributeError: 'Monitor' object has no attribute 'get_status'`.

- [ ] **Step 3: Add the methods to `Monitor`** (append after `_run_canary_guarded`)

```python
    def _maybe_start_canary(self, canary, now):
        ran_at = _parse(canary.get("ran_at"))
        if ran_at is not None and (now - ran_at) < timedelta(minutes=CANARY_INTERVAL_MIN):
            return
        with self._lock:
            if self._canary_running:
                return
            self._canary_running = True
        self._spawn(self._run_canary_guarded)

    def get_status(self, detail=False):
        now = self._now()
        canary = self._load_canary_cached()
        ran_at = _parse(canary.get("ran_at"))
        age_min = None if ran_at is None else (now - ran_at).total_seconds() / 60
        canary_ok = None if ran_at is None else bool(canary.get("ok"))
        warming = (now - self._started_at) < timedelta(minutes=WARMUP_MIN) and not self._ran_this_process
        if canary_ok and age_min <= STATUS_OK_MAX_AGE_MIN:
            state = "ok"
        elif warming:
            state = "warming_up"
        elif canary_ok is None:
            state = "no_data"
        elif not canary_ok:
            state = "failing"
        else:
            state = "stale"
        payload = {
            "state": state,
            "ok": state in ("ok", "warming_up"),
            "canary_ok": canary_ok,
            "canary_age_min": None if age_min is None else round(age_min, 1),
            "last_ok_at": canary.get("last_ok_at"),
            "alerts_configured": bool(self.alert_user_id),
            "checks": canary.get("checks"),
        }
        if detail:
            try:
                payload["yesterday"] = self.yesterday_summary()
            except Exception:
                traceback.print_exc()
                payload["yesterday"] = None
        self._maybe_start_canary(canary, now)
        return payload, (200 if payload["ok"] else 503)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\venv\Scripts\python.exe -m pytest tests/ -v`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add monitoring.py tests/test_status.py
git commit -m "Add Monitor status endpoint logic" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Morning report

**Files:**
- Modify: `monitoring.py` (add `build_morning_report`, `_fmt`, report methods, hook in `get_status`)
- Test: `tests/test_morning.py`

**Interfaces:**
- Consumes: `yesterday_summary`, `_load_canary`, `_push`, `get_status` (Task 5), constants.
- Produces: module function `build_morning_report(yesterday: dict, canary: dict, now: datetime) -> str`; `Monitor.send_morning_report() -> bool` (idempotent via Firestore `system/morning_report.sent_date`); `Monitor._maybe_start_morning_report(now)`; `Monitor._send_morning_report_guarded()`.

- [ ] **Step 1: Write the failing test** — `tests/test_morning.py`

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\venv\Scripts\python.exe -m pytest tests/test_morning.py -v`
Expected: ERROR `ImportError: cannot import name 'build_morning_report' from 'monitoring'`.

- [ ] **Step 3: Add the module-level functions to `monitoring.py`** (between `_parse` and `class Monitor`)

```python
def _fmt(iso):
    dt = _parse(iso)
    return dt.strftime("%m/%d %H:%M") if dt else "なし"


def build_morning_report(yesterday, canary, now):
    received, ok, failed = yesterday["received"], yesterday["ok"], yesterday["failed"]
    ran_at = _parse(canary.get("ran_at"))
    problems = []
    if failed > 0:
        problems.append(f"昨日の失敗が{failed}件あります")
    if ran_at is None:
        problems.append("自動テストが未実行です")
    elif (now - ran_at) > timedelta(minutes=STATUS_OK_MAX_AGE_MIN):
        problems.append("自動テストが止まっています")
    elif not canary.get("ok"):
        bad = ", ".join(k for k, v in (canary.get("checks") or {}).items() if v not in ("ok", "skipped"))
        problems.append(f"自動テストが失敗しています（{bad}）")
    icon = "⚠️" if problems else ("ℹ️" if received == 0 else "✅")
    lines = [
        f"{icon} SALUS MEAL 朝の確認（{now.strftime('%m/%d')}）",
        f"昨日の利用：受信{received}件 / 成功{ok}件 / 失敗{failed}件",
        f"最後の受信：{_fmt(yesterday.get('last_received_at'))}",
        f"最後の自動テスト：{_fmt(canary.get('ran_at'))}（{'成功' if canary.get('ok') else '失敗または未実行'}）",
    ]
    if problems:
        lines.append("要確認：" + "、".join(problems))
    elif received == 0:
        lines.append("昨日の利用はありませんでした。サーバーとWebhookは正常です。")
    else:
        lines.append("異常は検知されていません。")
    return "\n".join(lines)
```

- [ ] **Step 4: Add the methods to `Monitor`** (append after `get_status`) and the hook

```python
    def _maybe_start_morning_report(self, now):
        if not self.alert_user_id:
            return
        minutes = now.hour * 60 + now.minute
        if not (MORNING_START_MIN <= minutes < MORNING_END_MIN):
            return
        with self._lock:
            if self._report_running:
                return
            self._report_running = True
        self._spawn(self._send_morning_report_guarded)

    def _send_morning_report_guarded(self):
        try:
            self.send_morning_report()
        except Exception:
            traceback.print_exc()
        finally:
            with self._lock:
                self._report_running = False

    def send_morning_report(self):
        now = self._now()
        today = now.strftime("%Y-%m-%d")
        ref = self.db.collection("system").document("morning_report")
        doc = ref.get()
        if doc.exists and doc.to_dict().get("sent_date") == today:
            return False
        text = build_morning_report(self.yesterday_summary(), self._load_canary(), now)
        ref.set({"sent_date": today})
        if self._push(self.alert_user_id, text):
            return True
        ref.set({"sent_date": ""})
        return False
```

In `get_status`, add one line just before `return payload, ...`:
```python
        self._maybe_start_morning_report(now)
```
(so the final lines read `self._maybe_start_canary(canary, now)` / `self._maybe_start_morning_report(now)` / `return payload, (200 if payload["ok"] else 503)`).

- [ ] **Step 5: Run the whole suite**

Run: `.\venv\Scripts\python.exe -m pytest tests/ -v`
Expected: all passed (including the earlier status tests: they run at 12:00 so no report spawns).

- [ ] **Step 6: Commit**

```bash
git add monitoring.py tests/test_morning.py
git commit -m "Add activity-based morning report" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Wire the monitor into `main.py`

**Files:**
- Modify: `main.py` (imports; `push_message`; `reply_message`; callback region)
- Test: `tests/test_callback_integration.py`

**Interfaces:**
- Consumes: `monitoring.Monitor` (all methods above); `tests.fakes`.
- Produces in `main.py`: `push_message(user_id, text) -> int|None` (HTTP status); `reply_message(reply_token, user_id, text) -> {"ok": bool, "via": "reply"|"push", "status": int|None}`; `log_error()`; `display_name_of(user_id) -> str`; `process_event(event) -> dict|None`; `handle_event(event)`; module-level `monitor`; routes `/callback` and `/status`.

- [ ] **Step 1: Write the failing integration test** — `tests/test_callback_integration.py`

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\venv\Scripts\python.exe -m pytest tests/test_callback_integration.py -v`
Expected: FAIL with `AttributeError: module 'main' has no attribute 'monitor'` (or similar).

- [ ] **Step 3: Update imports in `main.py`**

Replace `from flask import Flask, request, session, jsonify` with:
```python
from flask import Flask, request, session, jsonify, g
```
and add `import sys` on its own line after `import os`.

- [ ] **Step 4: Replace `push_message` and `reply_message` in `main.py`**

Replace the existing `push_message` function with:
```python
def push_message(user_id, text):
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"
    }
    data = {
        "to": user_id,
        "messages": [{"type": "text", "text": text}]
    }
    try:
        resp = requests.post("https://api.line.me/v2/bot/message/push", headers=headers, json=data, timeout=10)
        return resp.status_code
    except Exception:
        traceback.print_exc()
        return None
```
Replace the existing `reply_message` function with:
```python
def reply_message(reply_token, user_id, text):
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"
    }
    data = {
        "replyToken": reply_token,
        "messages": [{"type": "text", "text": text}]
    }
    try:
        resp = requests.post("https://api.line.me/v2/bot/message/reply", headers=headers, json=data, timeout=10)
        if resp.status_code == 200:
            return {"ok": True, "via": "reply", "status": 200}
    except Exception:
        traceback.print_exc()
    # A reply token expires shortly after the webhook fires (slow cold start +
    # Gemini call) and LINE then returns a 4xx; fall back to a push keyed on the
    # user id instead of silently losing the reply.
    status = push_message(user_id, text)
    return {"ok": status == 200, "via": "push", "status": status}
```

- [ ] **Step 5: Transform the callback region with a script**

Write this script to the scratchpad directory as `transform_callback.py`, then run it from the repo root with `.\venv\Scripts\python.exe <scratchpad>\transform_callback.py`. It moves the body of the existing `for event in ...:` loop into `process_event(event)`, converts `continue` to `return`, returns each `reply_message(...)` result, and swaps the 14 `traceback.print_exc()` calls in that body for `log_error()`. Every replacement is guarded by an assertion; if one fails, stop and re-read `main.py` instead of forcing it.

```python
path = "main.py"
src = open(path, encoding="utf-8", newline="").read().replace("\r\n", "\n")

head = '@app.route("/callback", methods=["POST"])\ndef callback():\n    body = request.get_json()\n    for event in body.get("events", []):\n'
tail = '    return "OK"\n\n@app.route("/health")'
i = src.index(head)
j = src.index(tail, i)
body = src[i + len(head):j]

lines = []
for ln in body.split("\n"):
    if ln.strip() == "":
        lines.append("")
    else:
        assert ln.startswith("        "), repr(ln)
        lines.append(ln[4:])
new_body = "\n".join(lines)

assert new_body.count("continue") == 2
new_body = new_body.replace("continue", "return None")

assert new_body.count("reply_message(") == 4
new_body = new_body.replace("reply_message(", "return reply_message(")
pair = "        return reply_message(reply_token, user_id, welcome)\n        return None\n"
assert new_body.count(pair) == 1
new_body = new_body.replace(pair, "        return reply_message(reply_token, user_id, welcome)\n")

assert new_body.count("traceback.print_exc()") == 14, new_body.count("traceback.print_exc()")
new_body = new_body.replace("traceback.print_exc()", "log_error()")

new_block = '''def log_error():
    traceback.print_exc()
    exc = sys.exc_info()[1]
    desc = f"{type(exc).__name__}: {exc}"[:150] if exc else "unknown"
    try:
        g.event_errors.append(desc)
    except (AttributeError, RuntimeError):
        pass

def display_name_of(user_id):
    try:
        return (db.collection("users").document(user_id).get().to_dict() or {}).get("display_name") or user_id[:10]
    except Exception:
        return user_id[:10]

from monitoring import Monitor
monitor = Monitor(
    db=db,
    http=requests,
    line_token=LINE_CHANNEL_ACCESS_TOKEN,
    alert_user_id=os.environ.get("ALERT_LINE_USER_ID"),
    public_base_url=os.environ.get("PUBLIC_BASE_URL", "https://meal-tracker-bot-yzd1.onrender.com"),
    classify_fn=lambda text: classify_and_analyze(text),
    now_fn=lambda: datetime.now(JST),
)
if not monitor.alert_user_id:
    print("WARNING: ALERT_LINE_USER_ID is not set; failure alerts and the morning report are disabled.", flush=True)

def process_event(event):
''' + new_body.rstrip("\n") + '''

def handle_event(event):
    etype = event.get("type")
    if etype not in ("follow", "message"):
        return
    if etype == "follow":
        kind = "follow"
    else:
        mtype = (event.get("message") or {}).get("type")
        kind = mtype if mtype in ("text", "image") else "other"
    user_id = (event.get("source") or {}).get("userId", "")
    g.event_errors = []
    started = time.time()
    reply = None
    try:
        reply = process_event(event)
    except Exception:
        log_error()
    duration_ms = (time.time() - started) * 1000
    errors = list(getattr(g, "event_errors", []))
    if errors:
        outcome, error = "handler_error", " | ".join(errors)
    elif reply is not None and not reply["ok"]:
        outcome, error = "reply_failed", f"reply status {reply['status']} via {reply['via']}"
    else:
        outcome, error = "ok", None
    monitor.record_event(user_id, kind, outcome, duration_ms, reply, error)
    if outcome != "ok":
        monitor.alert_staff(
            "event_failure",
            f"⚠️ SALUS MEAL 返信に失敗した可能性があります\\n"
            f"時刻：{datetime.now(JST).strftime('%m/%d %H:%M')}\\n"
            f"お客様：{display_name_of(user_id)}\\n"
            f"種別：{kind} / 結果：{outcome}\\n"
            f"原因：{error}",
        )

@app.route("/callback", methods=["POST"])
def callback():
    body = request.get_json()
    for event in body.get("events", []):
        handle_event(event)
    return "OK"

@app.route("/status", methods=["GET", "HEAD"])
def status():
    payload, code = monitor.get_status(detail=request.args.get("detail") == "1")
    return jsonify(payload), code
'''

out = src[:i] + new_block + "\n" + src[j + len('    return "OK"\n\n'):]
open(path, "w", encoding="utf-8", newline="\n").write(out)
print("ok")
```

- [ ] **Step 6: Run the integration tests and the whole suite**

Run: `.\venv\Scripts\python.exe -m pytest tests/ -v`
Expected: all passed. If `test_callback_integration` errors while importing `main`, read the traceback (the most likely cause is an environment variable `main.py` reads at import time) and fix the fixture, not the production code.

- [ ] **Step 7: Review the diff for accidental changes**

Run: `git diff --stat main.py` and `git diff main.py`
Expected: only the import line, `push_message`/`reply_message`, the removed old `callback`, and the inserted block (`log_error`, `display_name_of`, `monitor`, `process_event`, `handle_event`, `callback`, `status`). The body of `process_event` must be the old loop body dedented by 4 spaces with `continue`→`return None`, `return reply_message(...)`, and `log_error()` substitutions only.

- [ ] **Step 8: Commit**

```bash
git add main.py tests/test_callback_integration.py
git commit -m "Wire Monitor into the LINE webhook and add /status" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Release preparation, deploy and verification

**Files:**
- Modify: `.github/workflows/keep-alive.yml`, `render.yaml`
- Delete: `.github/workflows/morning-health-check.yml`

This task touches production. Before each production-affecting step (marked **ASK**), confirm with the user in chat.

- [ ] **Step 1: Point the GitHub keep-alive at `/status`**

In `.github/workflows/keep-alive.yml` change the ping step to:
```yaml
      - name: Ping production status endpoint
        run: curl -sf -o /dev/null https://meal-tracker-bot-yzd1.onrender.com/status
```

- [ ] **Step 2: Remove the old morning workflow and document env vars**

```bash
git rm .github/workflows/morning-health-check.yml
```
In `render.yaml` add under `envVars` (same style as the existing entries):
```yaml
      - key: ALERT_LINE_USER_ID
        sync: false
      - key: PUBLIC_BASE_URL
        sync: false
```

- [ ] **Step 3: Full test run, then commit**

Run: `.\venv\Scripts\python.exe -m pytest tests/ -v` — expected: all passed.
```bash
git add .github/workflows/keep-alive.yml render.yaml
git commit -m "Point keep-alive at /status and retire the /health-only morning check" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 4: ASK — get the staff LINE user id and set it on Render**

Ask the user for the LINE user id that should receive alerts and the morning report. After they confirm, set it via the Render API (key in `.env` as `RENDER_API_KEY`, service `srv-d8ugmanlk1mc73fqms80`):
```
PUT https://api.render.com/v1/services/srv-d8ugmanlk1mc73fqms80/env-vars/ALERT_LINE_USER_ID
Authorization: Bearer <RENDER_API_KEY>
Content-Type: application/json
{"value": "<LINE user id>"}
```
Expected: HTTP 200. (Render redeploys on env var change; the next step's push will also redeploy.)

- [ ] **Step 5: ASK — push and watch the deploy**

After the user agrees, `git push origin main`. Poll the latest deploy status through the Render API (`GET /v1/services/srv-d8ugmanlk1mc73fqms80/deploys?limit=1`) until `live`. Expected: `live` within about 2 minutes.

- [ ] **Step 6: Verify `/status`**

Run `curl.exe -s https://meal-tracker-bot-yzd1.onrender.com/status` right after the deploy: expected `"state":"warming_up"` (HTTP 200). Run again after about 2 minutes: expected `"state":"ok"`, `"canary_ok":true`, `"alerts_configured":true`, and `checks` showing `line_webhook`, `gemini`, `firestore` as `ok` (`line_reply_api` may be `skipped`). If a check shows `fail:`, read its reason and the Render logs (`GET /v1/logs`) before changing anything.

- [ ] **Step 7: ASK — one-shot alert delivery test**

With the user's consent for one LINE push, run from the repo root (PowerShell) so the real token sends a single test alert (do NOT add the id to `.env`):
```powershell
$env:ALERT_LINE_USER_ID = "<LINE user id>"
.\venv\Scripts\python.exe -c "import os, requests, monitoring; from datetime import datetime, timezone, timedelta; from dotenv import load_dotenv; load_dotenv(); m = monitoring.Monitor(db=None, http=requests, line_token=os.environ['LINE_CHANNEL_ACCESS_TOKEN'], alert_user_id=os.environ['ALERT_LINE_USER_ID'], public_base_url='https://meal-tracker-bot-yzd1.onrender.com', classify_fn=None, now_fn=lambda: datetime.now(timezone(timedelta(hours=9)))); print(m._push(m.alert_user_id, '[テスト] SALUS MEAL の失敗通知の動作確認です。'))"
Remove-Item Env:ALERT_LINE_USER_ID
```
Expected: prints `True` and the staff LINE receives the test message.

- [ ] **Step 8: Real-message check**

Ask the user to send one meal message to the official account. Then confirm the reply arrived and that a document exists under Firestore `bot_events/<today>/items` with `outcome: "ok"` (query with a short script using `firestore_rest.client` and the `.env` credentials).

- [ ] **Step 9: User action — UptimeRobot**

Ask the user to edit the existing UptimeRobot monitor URL to `https://meal-tracker-bot-yzd1.onrender.com/status` (HTTP(s) monitor, 5 min). From then on a `failing`/`stale` state (HTTP 503) is reported to them by UptimeRobot email.

- [ ] **Step 10: Next-morning check and rollback plan**

The next day between 07:00 and 07:30 JST the staff LINE should receive the morning report (expected `ℹ️` if nobody used the bot, otherwise `✅`). If anything misbehaves: `git revert` the monitoring commits, push, and set the UptimeRobot URL back to `/dashboard/login`; re-adding `.github/workflows/morning-health-check.yml` restores the old check.

---

## Self-Review

**Spec coverage:** §4.1 event log → Tasks 2 and 7; §4.2 alerts (event failures, 2-consecutive canary failures, rate limit, unset user) → Tasks 3, 4 and 7; §4.3 canary (webhook endpoint + test, validate/reply with `skipped`, hourly Gemini, Firestore probe, background trigger from `/status`) → Tasks 4 and 5; §4.4 `/status` states, 503 mapping, `detail=1` → Task 5; §4.5 morning report moved to the server with idempotent window, three verdicts, workflow removal, keep-alive URL → Tasks 6 and 8; §5 config/data → Task 8; §6 error handling (monitoring never blocks replies) → Tasks 2, 3, 4, 5, 7; §7 tests and production verification → Tasks 1–8; §8 rollout/rollback → Task 8. One spec phrase is vacuous by construction: "⚠️ when `alerts_configured:false`" cannot occur in the report because the report is only sent when the staff id exists; `/status` still exposes `alerts_configured`.
**Placeholder scan:** no TBD/TODO; every code step has code; the only angle-bracket values are the user-supplied LINE user id and the Render API key.
**Type consistency:** `reply_message` returns `{"ok","via","status"}` and `record_event(user_id, kind, outcome, duration_ms, reply, error)` consumes exactly those keys; `get_status` returns `(payload, int)`, used the same way in `main.status`; `_run_canary_guarded`/`_send_morning_report_guarded` names match the tests that filter spawned callables by `__name__`.
**Review Focus coverage:** items 1, 2, 3, 4, 5 each map to a named test (Task 7 `test_unfollow_and_userless_events_are_ignored`; Tasks 2/3/4/5 Firestore-outage tests; Tasks 5/6 concurrent-ping tests; Tasks 2 and 6 boundary/midnight tests; Task 3 push-failure tests).
