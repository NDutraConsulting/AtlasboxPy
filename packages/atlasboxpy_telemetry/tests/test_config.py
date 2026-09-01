from atlasboxpy_telemetry import is_enabled, process_default_enabled, trace_override


def test_process_default_is_false_when_env_var_unset(monkeypatch):
    monkeypatch.delenv("ATLASBOXPY_TELEMETRY_ENABLED", raising=False)
    assert process_default_enabled() is False


def test_process_default_reads_env_var_fresh_each_call(monkeypatch):
    monkeypatch.setenv("ATLASBOXPY_TELEMETRY_ENABLED", "true")
    assert process_default_enabled() is True
    monkeypatch.setenv("ATLASBOXPY_TELEMETRY_ENABLED", "false")
    assert process_default_enabled() is False


def test_process_default_accepts_common_truthy_spellings(monkeypatch):
    for value in ["1", "true", "True", "YES", "on"]:
        monkeypatch.setenv("ATLASBOXPY_TELEMETRY_ENABLED", value)
        assert process_default_enabled() is True, value


def test_is_enabled_falls_back_to_process_default_with_no_override(monkeypatch):
    monkeypatch.setenv("ATLASBOXPY_TELEMETRY_ENABLED", "true")
    assert is_enabled() is True
    monkeypatch.setenv("ATLASBOXPY_TELEMETRY_ENABLED", "false")
    assert is_enabled() is False


def test_per_request_override_wins_over_process_default(monkeypatch):
    monkeypatch.setenv("ATLASBOXPY_TELEMETRY_ENABLED", "false")
    token = trace_override.set(True)
    try:
        assert is_enabled() is True
    finally:
        trace_override.reset(token)


def test_override_of_false_also_wins_over_a_true_process_default(monkeypatch):
    monkeypatch.setenv("ATLASBOXPY_TELEMETRY_ENABLED", "true")
    token = trace_override.set(False)
    try:
        assert is_enabled() is False
    finally:
        trace_override.reset(token)
