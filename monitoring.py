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
        self._maybe_start_morning_report(now)
        return payload, (200 if payload["ok"] else 503)

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
