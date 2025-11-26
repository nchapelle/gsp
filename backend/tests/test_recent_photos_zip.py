import io
import os
import zipfile

import pytest

import backend.app as appmod


class DummyCursor:
    def __init__(self, photos):
        self._photos = photos

    def execute(self, *args, **kwargs):
        return None

    def fetchone(self):
        return ("Dummy Venue",)

    def fetchall(self):
        return [(p,) for p in self._photos]


class DummyConn:
    def __init__(self, photos):
        self._photos = photos

    def cursor(self):
        return DummyCursor(self._photos)

    def close(self):
        pass


class DummyResponse:
    def __init__(self, parts, status_code=200, headers=None):
        self._parts = parts
        self.status_code = status_code
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("status %s" % self.status_code)

    def iter_content(self, size):
        for p in self._parts:
            yield p

    def close(self):
        pass


def test_recent_photos_zip_stops_on_total_cap(monkeypatch):
    # Two photos. First yields 300 bytes, second yields 800 bytes.
    photos = [
        "http://example.com/photo1.jpg",
        "http://example.com/photo2.jpg",
        "http://example.com/photo3.jpg",
    ]

    # Replace getconn to return our fake results
    monkeypatch.setattr(appmod, "getconn", lambda: DummyConn(photos))

    # Force small caps via env so first+second > MAX_ZIP_BYTES but each <= MAX_FILE_BYTES
    monkeypatch.setenv("MAX_ZIP_BYTES", str(500))
    monkeypatch.setenv("MAX_FILE_BYTES", str(1024))

    # HEAD: return small content-lengths so we stream
    def fake_head(url, timeout=10):
        # Pretend no content-length header for streaming path
        return DummyResponse([], headers={})

    # GET: the first file is 300 bytes, second is 250 (300+250 > 500 so hitting total cap), third 100
    def fake_get(url, stream=True, timeout=30):
        if "photo1" in url:
            return DummyResponse([b"x" * 300])
        if "photo2" in url:
            return DummyResponse([b"y" * 250])
        return DummyResponse([b"z" * 100])

    monkeypatch.setattr(appmod, "httpx", type("X", (), {"head": fake_head, "get": fake_get}))

    client = appmod.app.test_client()
    res = client.get("/venues/123/recent-photos-zip")

    assert res.status_code == 200
    # Validate that the returned zip only contains the first file (300 bytes)
    z = zipfile.ZipFile(io.BytesIO(res.data))
    names = z.namelist()
    assert len(names) >= 1
    # Ensure we didn't exceed MAX_ZIP_BYTES
    total_sz = sum(z.getinfo(n).file_size for n in names)
    assert total_sz <= 500
