from clipper import secrets


def test_memory_store_round_trips_without_touching_disk():
    store = secrets.MemorySecretStore()
    store.set("a", "b")
    assert store.get("a") == "b"
    assert store.available()[0] is True
    store.delete("a")
    assert store.get("a") is None


def test_json_helpers_and_status_use_the_configured_store():
    secrets.set_json("provider.youtube", {"client_id": "cid", "client_secret": "sec"})
    assert secrets.get_json("provider.youtube")["client_id"] == "cid"
    payload = secrets.status()
    assert payload["backend"] == "memory"
    assert payload["available"] is True


def test_redact_never_returns_the_full_secret():
    assert secrets.redact("abcdefghijkl") == "abcd…********"
    assert secrets.redact("") == ""
    assert "abcdefghijkl" not in secrets.redact("abcdefghijkl")


def test_corrupt_json_is_an_empty_dict_instead_of_a_crash():
    secrets.set_secret("bad", "{not json")
    assert secrets.get_json("bad") == {}
