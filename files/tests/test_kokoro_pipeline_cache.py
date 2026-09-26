"""_get_pipeline must cache per lang_code (v0.6.5 Phase 1 resource-lifecycle fix).

Discovered running the quality-suite harness: without caching, every call
rebuilt a whole KPipeline from scratch, which is wasteful in any single
process that synthesizes with more than one Kokoro voice in a row (measured
~300+ MB of avoidable working-set growth). ``_instantiate_pipeline`` is
monkeypatched to a counting stub, so neither the kokoro package nor its
model is ever touched — fast, deterministic, no network (plan Section 8).
"""
from __future__ import annotations

import tts.kokoro_synth as ks


def test_get_pipeline_reuses_the_same_instance_per_lang_code(monkeypatch):
    monkeypatch.setattr(ks, "_PIPELINE_CACHE", {})
    monkeypatch.setattr(ks, "_first_pipeline_load_attempted", True)

    calls: list[str] = []

    def _fake_instantiate(lang_code: str) -> object:
        calls.append(lang_code)
        return object()

    monkeypatch.setattr(ks, "_instantiate_pipeline", _fake_instantiate)

    first = ks._get_pipeline("a")
    second = ks._get_pipeline("a")

    assert first is second
    assert calls == ["a"], "a cached lang_code must not be instantiated twice"


def test_get_pipeline_caches_each_lang_code_independently(monkeypatch):
    monkeypatch.setattr(ks, "_PIPELINE_CACHE", {})
    monkeypatch.setattr(ks, "_first_pipeline_load_attempted", True)

    calls: list[str] = []

    def _fake_instantiate(lang_code: str) -> str:
        calls.append(lang_code)
        return f"pipeline-{lang_code}"

    monkeypatch.setattr(ks, "_instantiate_pipeline", _fake_instantiate)

    a1 = ks._get_pipeline("a")
    b1 = ks._get_pipeline("b")
    a2 = ks._get_pipeline("a")
    b2 = ks._get_pipeline("b")

    assert a1 == a2 == "pipeline-a"
    assert b1 == b2 == "pipeline-b"
    assert calls == ["a", "b"], "each lang_code must be instantiated at most once"


def test_get_pipeline_still_retries_once_on_first_load_failure(monkeypatch):
    """The pre-existing Windows Smart App Control retry must survive caching."""
    monkeypatch.setattr(ks, "_PIPELINE_CACHE", {})
    monkeypatch.setattr(ks, "_first_pipeline_load_attempted", False)
    monkeypatch.setattr(ks.time, "sleep", lambda seconds: None)

    attempts: list[int] = []

    def _flaky_instantiate(lang_code: str) -> str:
        attempts.append(1)
        if len(attempts) == 1:
            raise OSError("DLL load failed (Smart App Control)")
        return "pipeline-a"

    monkeypatch.setattr(ks, "_instantiate_pipeline", _flaky_instantiate)

    result = ks._get_pipeline("a")

    assert result == "pipeline-a"
    assert len(attempts) == 2, "the first-load retry must still fire once"
    assert ks._PIPELINE_CACHE["a"] == "pipeline-a", "the successful retry result must be cached"
