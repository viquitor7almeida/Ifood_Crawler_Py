import pytest
from pathlib import Path
from src.infra.cookie_store import CookieStore, StoredCookie


def test_cookie_store_save_and_load(tmp_path):
    path = tmp_path / "cookies.json"
    store = CookieStore(path)
    assert store.cookies == []

    store.update([StoredCookie(name="cf_clearance", value="abc", domain=".ifood.com.br")])
    assert len(store.cookies) == 1
    assert store.cookies[0].name == "cf_clearance"

    store2 = CookieStore(path)
    assert len(store2.cookies) == 1
    assert store2.cookies[0].value == "abc"


def test_cookie_store_update_replaces():
    path = Path("/tmp/test_cookies.json")
    path.unlink(missing_ok=True)
    store = CookieStore(path)
    store.update([StoredCookie(name="a", value="1", domain=".x.com")])
    store.update([StoredCookie(name="a", value="2", domain=".x.com")])
    assert len(store.cookies) == 1
    assert store.cookies[0].value == "2"
    path.unlink(missing_ok=True)


def test_cookie_store_clear(tmp_path):
    store = CookieStore(tmp_path / "c.json")
    store.update([StoredCookie(name="x", value="y", domain=".z.com")])
    store.clear()
    assert store.cookies == []


def test_cookie_store_empty_update_no_side_effect(tmp_path):
    store = CookieStore(tmp_path / "c.json")
    store.update([])
    assert store.cookies == []
