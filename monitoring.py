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
