"""
google-cloud-firestore の gRPC クライアントがこのプロジェクトの Firestore データベースに対して
常に "Invalid database id (default)" で失敗する問題を回避するための、
Firestore REST API v1 を直接叩く軽量な互換レイヤー。

main.py / dashboard.py からは、これまでの
    db.collection("meals").document(user_id).collection(date_str).order_by("timestamp").stream()
のような書き方をほぼそのまま使えるようにしてある。
"""

import json
import random
import string
import time

import requests
from google.auth.transport.requests import Request
from google.oauth2 import service_account

_BASE = "https://firestore.googleapis.com/v1"
_ID_CHARS = string.ascii_letters + string.digits


def _new_doc_id():
    return "".join(random.choices(_ID_CHARS, k=20))


def _encode_value(v):
    if v is None:
        return {"nullValue": None}
    if isinstance(v, bool):
        return {"booleanValue": v}
    if isinstance(v, int):
        return {"integerValue": str(v)}
    if isinstance(v, float):
        return {"doubleValue": v}
    if isinstance(v, str):
        return {"stringValue": v}
    if isinstance(v, dict):
        return {"mapValue": {"fields": {k: _encode_value(val) for k, val in v.items()}}}
    if isinstance(v, list):
        return {"arrayValue": {"values": [_encode_value(x) for x in v]}}
    raise TypeError(f"Unsupported Firestore value type: {type(v)}")


def _decode_value(fv):
    if "nullValue" in fv:
        return None
    if "booleanValue" in fv:
        return fv["booleanValue"]
    if "integerValue" in fv:
        return int(fv["integerValue"])
    if "doubleValue" in fv:
        return fv["doubleValue"]
    if "stringValue" in fv:
        return fv["stringValue"]
    if "timestampValue" in fv:
        return fv["timestampValue"]
    if "mapValue" in fv:
        return _decode_fields(fv["mapValue"].get("fields", {}))
    if "arrayValue" in fv:
        return [_decode_value(x) for x in fv["arrayValue"].get("values", [])]
    return None


def _encode_fields(data: dict) -> dict:
    return {k: _encode_value(v) for k, v in data.items()}


def _decode_fields(fields: dict) -> dict:
    return {k: _decode_value(v) for k, v in fields.items()}


class Query:
    ASCENDING = "ASCENDING"
    DESCENDING = "DESCENDING"


class DocSnapshot:
    def __init__(self, doc_id, fields, exists):
        self.id = doc_id
        self._fields = fields
        self.exists = exists

    def to_dict(self):
        return self._fields


class _RefBase:
    def __init__(self, client, path_segments):
        self._client = client
        self._segments = path_segments

    @property
    def _path(self):
        return "/".join(self._segments)


class DocumentRef(_RefBase):
    @property
    def id(self):
        return self._segments[-1]

    def collection(self, collection_id):
        return CollectionRef(self._client, self._segments + [collection_id])

    def get(self):
        return self._client._get_document(self._segments)

    def set(self, data):
        self._client._write_document(self._segments, data)

    def update(self, data):
        self._client._update_document(self._segments, data)

    def delete(self):
        self._client._delete_document(self._segments)


class CollectionRef(_RefBase):
    def document(self, doc_id=None):
        if doc_id is None:
            doc_id = _new_doc_id()
        return DocumentRef(self._client, self._segments + [doc_id])

    def order_by(self, field, direction=Query.ASCENDING):
        return _OrderedQuery(self._client, self._segments, field, direction, None)

    def stream(self):
        return self._client._list_collection(self._segments)


class _OrderedQuery:
    def __init__(self, client, segments, order_field, direction, limit):
        self._client = client
        self._segments = segments
        self._order_field = order_field
        self._direction = direction
        self._limit = limit

    def limit(self, n):
        return _OrderedQuery(self._client, self._segments, self._order_field, self._direction, n)

    def stream(self):
        return self._client._run_query(self._segments, self._order_field, self._direction, self._limit)


class FirestoreRestClient:
    def __init__(self, cred_dict):
        self._project_id = cred_dict["project_id"]
        self._creds = service_account.Credentials.from_service_account_info(
            cred_dict,
            scopes=["https://www.googleapis.com/auth/datastore", "https://www.googleapis.com/auth/cloud-platform"],
        )
        self._documents_base = f"{_BASE}/projects/{self._project_id}/databases/(default)/documents"
        self._session = requests.Session()

    def collection(self, collection_id):
        return CollectionRef(self, [collection_id])

    def _headers(self):
        if not self._creds.valid:
            self._creds.refresh(Request())
        return {"Authorization": f"Bearer {self._creds.token}"}

    def _request(self, method, url, **kwargs):
        for attempt in range(3):
            resp = self._session.request(method, url, headers=self._headers(), timeout=15, **kwargs)
            if resp.status_code < 500:
                return resp
            time.sleep(1)
        return resp

    def _get_document(self, segments):
        url = f"{self._documents_base}/{'/'.join(segments)}"
        resp = self._request("GET", url)
        if resp.status_code == 404:
            return DocSnapshot(segments[-1], {}, False)
        resp.raise_for_status()
        body = resp.json()
        return DocSnapshot(segments[-1], _decode_fields(body.get("fields", {})), True)

    def _write_document(self, segments, data):
        # Full replace, matching google-cloud-firestore's DocumentReference.set()
        # (without merge=True): the document ends up containing exactly `data`.
        url = f"{self._documents_base}/{'/'.join(segments)}"
        body = {"fields": _encode_fields(data)}
        resp = self._request("PATCH", url, json=body)
        resp.raise_for_status()

    def _update_document(self, segments, data):
        # Partial merge, matching google-cloud-firestore's DocumentReference.update():
        # only the given fields are touched, everything else on the document is kept.
        # Firestore's REST API requires an explicit updateMask for merge semantics --
        # a PATCH with no updateMask replaces the whole document instead.
        url = f"{self._documents_base}/{'/'.join(segments)}"
        body = {"fields": _encode_fields(data)}
        params = [("updateMask.fieldPaths", key) for key in data.keys()]
        resp = self._request("PATCH", url, json=body, params=params)
        resp.raise_for_status()

    def _delete_document(self, segments):
        url = f"{self._documents_base}/{'/'.join(segments)}"
        resp = self._request("DELETE", url)
        if resp.status_code not in (200, 404):
            resp.raise_for_status()

    def _list_collection(self, segments):
        # segments = [..., collection_id] ; parent is everything before the last segment
        parent_segments = segments[:-1]
        collection_id = segments[-1]
        parent_url = self._documents_base if not parent_segments else f"{self._documents_base}/{'/'.join(parent_segments)}"
        url = f"{parent_url}/{collection_id}"
        results = []
        page_token = None
        while True:
            params = {"pageSize": 300}
            if page_token:
                params["pageToken"] = page_token
            resp = self._request("GET", url, params=params)
            if resp.status_code == 404:
                break
            resp.raise_for_status()
            body = resp.json()
            for doc in body.get("documents", []):
                doc_id = doc["name"].rsplit("/", 1)[-1]
                results.append(DocSnapshot(doc_id, _decode_fields(doc.get("fields", {})), True))
            page_token = body.get("nextPageToken")
            if not page_token:
                break
        return results

    def _run_query(self, segments, order_field, direction, limit):
        parent_segments = segments[:-1]
        collection_id = segments[-1]
        parent_url = self._documents_base if not parent_segments else f"{self._documents_base}/{'/'.join(parent_segments)}"
        url = f"{parent_url}:runQuery"
        structured_query = {
            "from": [{"collectionId": collection_id}],
            "orderBy": [{"field": {"fieldPath": order_field}, "direction": direction}],
        }
        if limit:
            structured_query["limit"] = limit
        resp = self._request("POST", url, json={"structuredQuery": structured_query})
        resp.raise_for_status()
        results = []
        for item in resp.json():
            doc = item.get("document")
            if not doc:
                continue
            doc_id = doc["name"].rsplit("/", 1)[-1]
            results.append(DocSnapshot(doc_id, _decode_fields(doc.get("fields", {})), True))
        return results


def client(cred_dict):
    return FirestoreRestClient(cred_dict)
