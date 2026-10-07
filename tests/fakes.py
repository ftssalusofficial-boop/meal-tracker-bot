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
