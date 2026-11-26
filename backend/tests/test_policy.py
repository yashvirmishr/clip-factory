from clipper import policy


def test_version_is_deterministic_and_changes_with_payload():
    payload = {"a": 1, "b": [2, 3]}
    assert policy.version_for(payload) == policy.version_for({"b": [2, 3], "a": 1})
    assert policy.version_for(payload) != policy.version_for({"a": 2})
    assert policy.version_for(payload).startswith("p_")


def test_activate_promotes_exactly_one_version(clean_db):
    one = policy.activate("p_one", payload={"x": 1})
    two = policy.activate("p_two", payload={"x": 2})
    assert one.version == "p_one"
    assert two.version == "p_two"
    assert policy.active().version == "p_two"
    versions = {item["version"]: item for item in policy.list_versions()}
    assert versions["p_two"]["active"] is True
    assert versions["p_one"]["active"] is False


def test_active_creates_a_policy_from_current_settings(clean_db):
    active = policy.active()
    assert active.version == policy.version_for(active.payload)
    assert policy.active().version == active.version


def test_unknown_version_cannot_be_activated_without_a_payload(clean_db):
    import pytest

    with pytest.raises(KeyError):
        policy.activate("p_missing")
