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
