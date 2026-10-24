"""v0.7.0 P03D — typed developer mode and the gated reference-transcript tools.

What is pinned (the letters are the P03D regression matrix):

* A-D, O: ``[development] developer_mode`` is ``True`` only for a genuine TOML ``true``; missing, ``false``, strings,
  numbers, tables and malformed files all resolve to ``False`` with the normal diagnostics; the tracked root file and
  every packaged archive say exactly ``false`` (``test_release_packaging`` pins the archives).
* E, F: ``settings.json`` and environment variables cannot switch it on; the snapshot is immutable and cached, a new load
  (a restart) reads the file again, and nothing ever writes ``config.toml``.
* G-I: in normal mode the transcript tools are not on screen, every restricted operation refuses when called directly, the
  eight voices and the install/repair path are unchanged, nothing touches the speech recognizer, and neither the ambient
  local store, ``ACT_QWEN3_TRANSCRIPTS`` nor a selection file can shadow the shipped bundle.
* J-N: in developer mode exactly the one clearly labelled entry point appears; a local text is used for narration only
  after a deliberate, confirmed selection bound to the stable voice id, the recording's hash and the text's hash; a stale,
  changed or damaged selection fails that clone closed (never the bundle, never a guess); a failed save keeps the previous
  file and the user's edits; and nothing is downloaded or transcribed without an explicit, confirmed request.

Developer mode is always switched on through the real loader reading a disposable ``config.toml`` (``use_config``); the
tracked root file is only ever read.
"""

from __future__ import annotations

import ast
import dataclasses
import hashlib
import json
import os
import subprocess
import sys
import tkinter as tk
import tomllib
from pathlib import Path

import pytest

from shared import config
from tts import qwen3_clone_setup as qt
from tts import qwen3_install_ui as install_ui
from tts import qwen3_runtime as rt
from tts import qwen3_setup as su

from test_qwen3_runtime import (  # noqa: F401
    install_bundle, install_clone_fixture, install_environment, install_model, sandbox)
from source_probe import application_python_files
from test_tts_importing import tk_root  # noqa: F401

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"
sys.path.insert(0, str(REPO_ROOT / "files" / "dev-tools"))

import qwen3_transcript_review as review  # noqa: E402
import voice_previews as vp  # noqa: E402

CLONES = ["qwen3-female-1", "qwen3-female-2", "qwen3-male-1", "qwen3-male-2", "qwen3-male-3", "qwen3-male-4"]
PRESETS = ["qwen3-aiden", "qwen3-ryan"]
KEY = "development.developer_mode"


def use_config(monkeypatch, folder: Path, body: str) -> config.EffectiveConfig:
    """Make *body* the process's configuration through the real loader (a disposable file, never the tracked one)."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "config.toml").write_text(body, encoding="utf-8")
    snapshot = config.load(config_path=folder / "config.toml", settings_data={}, repo_root=folder)
    monkeypatch.setattr(config, "_cache", snapshot)
    return snapshot


def load_body(tmp_path: Path, body: str, **kwargs) -> config.EffectiveConfig:
    (tmp_path / "config.toml").write_text(body, encoding="utf-8")
    kwargs.setdefault("settings_data", {})
    return config.load(config_path=tmp_path / "config.toml", repo_root=tmp_path, **kwargs)


def diagnostics_for(effective, key: str) -> list:
    return [d for d in effective.diagnostics if d.key == key]


@pytest.fixture()
def normal(tmp_path, monkeypatch):
    """Normal mode from a disposable file, so these tests do not depend on what the tracked file says (O pins that)."""
    return use_config(monkeypatch, tmp_path / "normal-config", "[development]\ndeveloper_mode = false\n")


@pytest.fixture()
def developer(tmp_path, monkeypatch):
    return use_config(monkeypatch, tmp_path / "developer-config", "[development]\ndeveloper_mode = true\n")


# --------------------------------------------------------------------------- #
# A-D: the typed value
# --------------------------------------------------------------------------- #
def test_a_missing_section_or_key_is_false_from_the_built_in_default(tmp_path):
    for body in ("", '[project]\nname = "x"\n', "[development]\n"):
        effective = load_body(tmp_path, body)
        assert effective.development.developer_mode is False
        assert effective.source_of(KEY) == config.SOURCE_DEFAULT and not diagnostics_for(effective, KEY)
    assert config.DEFAULTS[KEY] is False and config.DevelopmentConfig().developer_mode is False


def test_an_explicit_false_is_false_from_config_toml(tmp_path):
    effective = load_body(tmp_path, "[development]\ndeveloper_mode = false\n")
    assert effective.development.developer_mode is False and effective.source_of(KEY) == config.SOURCE_TOML
    assert not effective.diagnostics


def test_only_a_genuine_toml_true_turns_it_on(tmp_path):
    effective = load_body(tmp_path, "[development]\ndeveloper_mode = true\n")
    assert effective.development.developer_mode is True and effective.source_of(KEY) == config.SOURCE_TOML
    assert not effective.diagnostics


@pytest.mark.parametrize("raw", ['"true"', '"TRUE"', '"yes"', '"false"', "1", "0", "1.0", "[true]", "{ on = true }",
                                 "2026-10-24"])
def test_anything_but_a_boolean_is_false_with_a_diagnostic(tmp_path, raw):
    effective = load_body(tmp_path, f"[development]\ndeveloper_mode = {raw}\n")
    assert effective.development.developer_mode is False and effective.source_of(KEY) == config.SOURCE_DEFAULT
    (diag,) = diagnostics_for(effective, KEY)
    assert diag.source == config.SOURCE_TOML and "true or false" in diag.message and "using false" in diag.message
    assert "developer_mode" in effective.warning_summary()


@pytest.mark.parametrize("body, key", [
    ("[development\ndeveloper_mode = true\n", ""),                 # the file does not parse at all
    ("development = true\n", "development"),                        # not a section
    ("[development]\ndeveloper_mod = true\n", ""),                  # a typo is reported, never honoured
    ("[project]\ndeveloper_mode = true\n", ""),                     # the right key in the wrong section
])
def test_a_malformed_file_or_misplaced_key_is_false_with_a_diagnostic(tmp_path, body, key):
    effective = load_body(tmp_path, body)
    assert effective.development.developer_mode is False
    assert [d for d in effective.diagnostics if d.key == key and d.source == config.SOURCE_TOML]


def test_the_snapshot_is_immutable():
    effective = config.load(settings_data={})
    with pytest.raises(dataclasses.FrozenInstanceError):
        effective.development.developer_mode = True  # type: ignore[misc]
    with pytest.raises(TypeError):
        effective.sources[KEY] = config.SOURCE_TOML  # type: ignore[index]


# --------------------------------------------------------------------------- #
# E: only config.toml can switch it on
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("settings_key", ["developer_mode", KEY, "development"])
def test_settings_json_can_neither_enable_nor_disable_it(tmp_path, settings_key):
    on = load_body(tmp_path, "", settings_data={settings_key: True})
    assert on.development.developer_mode is False and on.source_of(KEY) == config.SOURCE_DEFAULT
    assert any(d.source == config.SOURCE_SETTINGS and settings_key in d.detail for d in on.diagnostics)
    off = load_body(tmp_path, "[development]\ndeveloper_mode = true\n", settings_data={settings_key: False})
    assert off.development.developer_mode is True and off.source_of(KEY) == config.SOURCE_TOML
    assert not config.is_allowlisted_setting(settings_key)
    assert KEY not in config.SETTINGS_OVERLAY.values() and settings_key not in config.USER_STATE_SETTINGS


@pytest.mark.parametrize("name", ["ACT_DEVELOPER_MODE", "DEVELOPER_MODE", "ACT_DEV_MODE", "AUDIOBOOK_DEVELOPER_MODE"])
def test_no_environment_variable_is_a_shortcut(normal, monkeypatch, name):
    monkeypatch.setenv(name, "true")
    assert config.developer_mode() is False and rt.developer_mode() is False
    assert config.load(settings_data={}).development.developer_mode is False  # the tracked file, re-read


def _environment_reads(tree: ast.AST) -> list[str]:
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in {"environ", "getenv", "environb"}:
            found.append(node.attr)
        if isinstance(node, ast.Name) and node.id in {"environ", "getenv"}:
            found.append(node.id)
    return found


def test_the_configuration_loader_never_reads_the_environment():
    assert _environment_reads(ast.parse((SCRIPTS / "shared" / "config.py").read_text(encoding="utf-8"))) == []


def test_the_only_production_gate_is_the_configuration_value():
    """Every ``developer_mode`` read in the app goes through ``config.developer_mode``; nothing keys it off a variable."""
    readers = []
    for path in application_python_files():  # the shared, machine-independent production tree (not a raw walk)
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args or not isinstance(node.args[0], ast.Constant):
                continue
            func = node.func
            from_environment = isinstance(func, ast.Attribute) and (func.attr == "getenv" or (
                func.attr == "get" and isinstance(func.value, ast.Attribute) and func.value.attr == "environ"))
            if from_environment and isinstance(node.args[0].value, str) and "DEVELOP" in node.args[0].value.upper():
                readers.append(f"{path.relative_to(REPO_ROOT).as_posix()}:{node.lineno}")
    assert readers == []
    gate = ast.parse((SCRIPTS / "tts" / "qwen3_runtime.py").read_text(encoding="utf-8"))
    fn = next(n for n in gate.body if isinstance(n, ast.FunctionDef) and n.name == "developer_mode")
    assert _environment_reads(fn) == [] and "config.developer_mode" in ast.unparse(fn)


# --------------------------------------------------------------------------- #
# F: a restart reads the file again; the app never writes it
# --------------------------------------------------------------------------- #
def test_the_cached_snapshot_holds_until_the_app_loads_again(tmp_path, monkeypatch):
    folder = tmp_path / "cfg"
    use_config(monkeypatch, folder, "[development]\ndeveloper_mode = false\n")
    (folder / "config.toml").write_text("[development]\ndeveloper_mode = true\n", encoding="utf-8")
    assert config.developer_mode() is False and rt.developer_mode() is False  # edited while running: no effect yet
    restarted = config.load(config_path=folder / "config.toml", settings_data={}, repo_root=folder)
    monkeypatch.setattr(config, "_cache", restarted)
    assert config.developer_mode() is True and rt.developer_mode() is True  # the next start reads it


def test_loading_reloading_and_saving_preferences_never_write_config_toml(tmp_path, monkeypatch):
    root_config = REPO_ROOT / "config.toml"
    before = (root_config.read_bytes(), root_config.stat().st_mtime_ns)
    config.reload()
    config.get_effective()
    assert config.set_output_base(str(tmp_path / "outputs")) in (True, False)  # writes the isolated settings.json only
    config.reset_preferences()
    config.reload()
    assert (root_config.read_bytes(), root_config.stat().st_mtime_ns) == before
    assert config.developer_mode() is False


def test_the_toml_documents_the_restart_and_the_shipped_value():
    text = (REPO_ROOT / "config.toml").read_text(encoding="utf-8")
    section = text[text.index("[development]"):]
    assert "Restart the application after" in section and "settings.json" in section and "never edits it" in section


# --------------------------------------------------------------------------- #
# O: the tracked file and the repository gate
# --------------------------------------------------------------------------- #
def test_the_tracked_config_toml_says_exactly_developer_mode_false():
    data = tomllib.loads((REPO_ROOT / "config.toml").read_text(encoding="utf-8"))
    assert data["development"] == {"developer_mode": False}
    shipped = config.load(config_path=REPO_ROOT / "config.toml", settings_data={})
    assert shipped.development.developer_mode is False and shipped.source_of(KEY) == config.SOURCE_TOML


def _verify():
    sys.path.insert(0, str(SCRIPTS))
    import verify

    return verify


@pytest.mark.parametrize("tail, message", [
    ("[development]\ndeveloper_mode = true\n", "must never be committed"),
    ("", "must state developer_mode = false"),
    ("[development]\n", "must state developer_mode = false"),
    ('[development]\ndeveloper_mode = "false"\n', "developer_mode"),
])
def test_the_repository_gate_refuses_anything_but_an_explicit_false(tmp_path, tail, message):
    verify = _verify()
    real = (REPO_ROOT / "config.toml").read_text(encoding="utf-8")
    head = real[:real.index("[development]")]
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "launcher.py").write_text("# stand-in\n", encoding="utf-8")
    good = tmp_path / "good.toml"
    good.write_text(real, encoding="utf-8")
    assert verify.check_config(good, tmp_path)[1] is True
    bad = tmp_path / "bad.toml"
    bad.write_text(head + tail, encoding="utf-8")
    name, ok, detail = verify.check_config(bad, tmp_path)
    assert name == "config" and ok is False and message in detail
    assert verify.check_config()[1] is True  # and the committed file passes


# --------------------------------------------------------------------------- #
# Shared fixtures for the Qwen3 side
# --------------------------------------------------------------------------- #
@pytest.fixture()
def clones(sandbox, monkeypatch):
    """Engine, both models, six registered recordings and a valid shipped bundle, all inside the sandbox."""
    install_environment(sandbox)
    install_model(sandbox, "base")
    install_model(sandbox, "customvoice")
    voices = {vid: install_clone_fixture(sandbox, monkeypatch, vid) for vid in CLONES}
    install_bundle(sandbox, monkeypatch)
    monkeypatch.setattr(rt, "environment_status", lambda: (True, "ok"))
    data = b"tiny recognizer"  # a manifest entry only: nothing is installed, so the recognizer reads as absent
    rt.load_manifest()["transcriber"] = {
        "label": "speech recognizer (test)", "repo": "openai/whisper-small.en", "revision": "c" * 40,
        "license": "apache-2.0", "dir": "whisper-test",
        "files": {"model.safetensors": {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}}}
    return voices


def bundled(voice_id: str) -> str:
    return f"bundled words for {rt.get_voice(voice_id).reference_name}"


def approved_store(voices, path: Path, **texts) -> None:
    """A local store with an approved entry per clone (or the given texts), bound to the registered recordings."""
    data = {v.reference_name: {"text": texts.get(vid, f"local words for {v.reference_name}"), "approved": True,
                               "wav_sha256": v.reference_sha256, "approved_by": "unit test"}
            for vid, v in voices.items()}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def selection_doc(voices, ids=("qwen3-male-1",), store: Path | None = None) -> dict:
    store_data = json.loads((store or rt.local_transcripts_path()).read_text(encoding="utf-8"))
    return {"schema": 1, "voices": {vid: {"reference_id": voices[vid].reference_name,
                                          "wav_sha256": voices[vid].reference_sha256,
                                          "text_sha256": rt.transcript_sha256(store_data[voices[vid].reference_name]["text"])}
                                    for vid in ids}}


def guard_recognizer(monkeypatch) -> None:
    """Fail on any attempt to download, verify or run the speech recognizer."""
    def refuse(*args, **kwargs):
        pytest.fail("the speech recognizer was touched")

    monkeypatch.setattr(su, "install_model", refuse)
    monkeypatch.setattr(rt, "transcriber_status", refuse)
    from tts import qwen3_synth

    monkeypatch.setattr(qwen3_synth, "run_worker", refuse)


# --------------------------------------------------------------------------- #
# G: normal-mode UI
# --------------------------------------------------------------------------- #
def _texts(widget) -> list[str]:
    out = []
    for child in widget.winfo_children():
        try:
            out.append(str(child.cget("text")))
        except tk.TclError:
            pass
        out.extend(_texts(child))
    return out


def test_normal_mode_the_install_dialog_has_no_transcript_tools(tk_root, normal, clones, monkeypatch):
    guard_recognizer(monkeypatch)
    win = install_ui.build_dialog(tk_root, confirm=lambda *a: pytest.fail("asked"),
                                  open_clones=lambda parent: pytest.fail("the transcript tools opened"))
    try:
        win.refresh()
        assert win.btn_clones is None
        shown = " ".join(_texts(win))
        for word in ("Developer", "Reference transcripts", "Set up cloned", "recognizer", "Whisper"):
            assert word not in shown, word
        # ordinary installation and repair are exactly as before
        for button in (win.btn_customvoice, win.btn_base, win.btn_both, win.btn_repair, win.btn_cancel, win.btn_close):
            assert button.winfo_exists()
        assert "Cloned voice transcripts: included with the app." in install_ui.state_lines()
        assert not any("Developer mode" in line for line in install_ui.state_lines())
    finally:
        win.destroy()


def test_normal_mode_the_reference_transcript_dialog_cannot_be_built(tk_root, normal, clones, monkeypatch):
    from tts import qwen3_clone_setup_ui as ui

    guard_recognizer(monkeypatch)
    before = set(tk_root.winfo_children())
    with pytest.raises(su.SetupError, match="developer_mode = true"):
        ui.build_dialog(tk_root, confirm=lambda *a: True, player=None)
    assert set(tk_root.winfo_children()) == before  # no window was created


def test_normal_mode_all_eight_voices_are_ready_from_the_bundle_without_the_recognizer(normal, clones, monkeypatch):
    guard_recognizer(monkeypatch)
    for voice_id in PRESETS + CLONES:
        assert rt.voice_availability(voice_id) == (True, "ok"), voice_id
    for voice_id in CLONES:
        loaded = rt.load_transcript(voice_id)
        assert loaded.ok and loaded.text == bundled(voice_id) and not loaded.developer_override


# --------------------------------------------------------------------------- #
# H: normal-mode backend refuses direct calls
# --------------------------------------------------------------------------- #
def test_normal_mode_every_restricted_clone_setup_step_refuses_when_called_directly(normal, clones, monkeypatch, tmp_path):
    guard_recognizer(monkeypatch)
    store = rt.local_transcripts_path()
    selection = rt.override_selection_path()

    result = qt.install_recognizer(disk_free=lambda path: 10**15)
    assert not result.ok and result.message == rt.DEVELOPER_MODE_REQUIRED
    assert qt.drafting_problem() == rt.DEVELOPER_MODE_REQUIRED
    result = qt.create_drafts(jobs_root=tmp_path / "jobs")
    assert not result.ok and result.message == rt.DEVELOPER_MODE_REQUIRED and not (tmp_path / "jobs").exists()
    # each step refuses up front, before reading the store: no step relies on a later guard (write_store's) alone
    monkeypatch.setattr(qt, "read_store", lambda path=None: pytest.fail("the local store was read in normal mode"))
    for call in (lambda: qt.approve({"qwen3-male-1": ("words", True)}),
                 lambda: qt.write_store({"Male-1": {"text": "x"}}),
                 lambda: qt.select_for_narration(["qwen3-male-1"]),
                 lambda: qt.return_to_shipped(),
                 lambda: qt.return_to_shipped(["qwen3-male-1"]),
                 qt.require_developer_mode):
        with pytest.raises(su.SetupError, match="developer_mode = true"):
            call()
    with pytest.raises(rt.DeveloperModeRequired):
        rt.require_developer_mode()
    assert qt.selected_voice_ids() == []
    assert not store.exists() and not selection.exists()  # nothing was written anywhere


def test_normal_mode_an_explicit_local_store_is_refused(normal, clones):
    store = rt.local_transcripts_path()
    approved_store(clones, store)
    refused = rt.load_transcript("qwen3-male-1", override=store)
    assert not refused.ok and refused.text == "" and refused.reason == rt.DEVELOPER_MODE_REQUIRED


def test_normal_mode_the_transcript_review_tool_refuses_its_local_operations(normal, tmp_path):
    drafts = tmp_path / "verified.json"
    drafts.write_text("{}", encoding="utf-8")
    for call in (lambda: review.build(drafts, tmp_path / "out" / "review.html"),
                 lambda: review.apply(tmp_path / "decisions.json", drafts_path=drafts, target=tmp_path / "t.json"),
                 lambda: review.apply(tmp_path / "decisions.json", write=True, drafts_path=drafts, target=tmp_path / "t.json"),
                 lambda: review.status(tmp_path / "t.json")):
        with pytest.raises(review.ReviewError, match="developer_mode = true"):
            call()
    assert not (tmp_path / "out").exists() and not (tmp_path / "t.json").exists()
    assert review.status() == [f"{v.label}: approved" for v in review.clone_voices()]  # the bundle: both modes
    assert review.main(["status", "--store", str(tmp_path / "t.json")]) == 2


def test_normal_mode_the_preview_tool_refuses_provisional_transcripts(normal, tmp_path, monkeypatch):
    monkeypatch.setattr(vp, "synthesize", lambda *a: pytest.fail("an engine ran"))
    with pytest.raises(vp.PreviewError, match="developer_mode = true"):
        vp.provisional_transcripts(tmp_path / "drafts.json")
    with pytest.raises(vp.PreviewError, match="developer_mode = true"):
        with vp.provisional_loader({"qwen3-male-1": "draft words"}):
            pytest.fail("the provisional loader was entered")
    with vp.provisional_loader({}):  # the ordinary, bundle-only path is unchanged
        assert rt.load_transcript("qwen3-male-1").ok
    with pytest.raises(vp.PreviewError, match="developer_mode = true"):
        vp.generate(["qwen3-male-1"], log=lambda line: None, provisional=True)


# --------------------------------------------------------------------------- #
# I: nothing local shadows the bundle in normal mode, and developer mode alone activates nothing
# --------------------------------------------------------------------------- #
def _plant_every_local_source(clones, tmp_path, monkeypatch) -> Path:
    approved_store(clones, rt.local_transcripts_path(), **{vid: "ambient local words" for vid in CLONES})
    env_store = tmp_path / "env" / "transcripts.json"
    approved_store(clones, env_store, **{vid: "environment words" for vid in CLONES})
    monkeypatch.setenv(rt.TRANSCRIPTS_ENV, str(env_store))
    return env_store


def test_normal_mode_ambient_store_variable_and_selection_never_shadow_the_bundle(normal, clones, tmp_path, monkeypatch):
    env_store = _plant_every_local_source(clones, tmp_path, monkeypatch)
    selection = rt.override_selection_path()
    selection.write_text(json.dumps(selection_doc(clones, CLONES, store=env_store)), encoding="utf-8")
    monkeypatch.setattr(rt, "read_override_selection", lambda path=None: pytest.fail("the selection was read"))
    assert rt.local_store_path() == rt.local_transcripts_path()  # the variable names nothing in normal mode
    for voice_id in CLONES:
        loaded = rt.load_transcript(voice_id)
        assert loaded.ok and loaded.text == bundled(voice_id) and not loaded.developer_override, voice_id
        assert rt.voice_availability(voice_id) == (True, "ok")


def test_developer_mode_alone_activates_neither_the_ambient_store_nor_the_variable(developer, clones, tmp_path,
                                                                                    monkeypatch):
    env_store = _plant_every_local_source(clones, tmp_path, monkeypatch)
    assert rt.local_store_path() == env_store  # the maintainer tools now see the variable ...
    assert not rt.override_selection_path().exists()
    for voice_id in CLONES:  # ... but narration still reads the bundle: nothing was selected
        loaded = rt.load_transcript(voice_id)
        assert loaded.ok and loaded.text == bundled(voice_id) and not loaded.developer_override, voice_id


# --------------------------------------------------------------------------- #
# J: developer-mode UI
# --------------------------------------------------------------------------- #
def test_developer_mode_adds_exactly_the_one_labelled_entry_point(tk_root, tmp_path, clones, monkeypatch):
    guard_recognizer(monkeypatch)
    use_config(monkeypatch, tmp_path / "off", "[development]\ndeveloper_mode = false\n")
    plain = install_ui.build_dialog(tk_root, confirm=lambda *a: True)
    use_config(monkeypatch, tmp_path / "on", "[development]\ndeveloper_mode = true\n")
    opened = []
    dev = install_ui.build_dialog(tk_root, confirm=lambda *a: True, open_clones=lambda parent: opened.append(parent))
    try:
        assert sorted(set(_texts(dev)) - set(_texts(plain))) == [install_ui.DEVELOPER_TOOLS_LABEL]
        assert install_ui.DEVELOPER_TOOLS_LABEL == "Developer tools → Reference transcripts..."
        dev.refresh()
        assert str(dev.btn_clones.cget("state")) == tk.NORMAL  # engine + Base installed
        dev.btn_clones.invoke()
        assert opened == [dev]
    finally:
        plain.destroy()
        dev.destroy()


def test_developer_mode_the_dialog_is_marked_and_says_the_bundle_is_not_replaced(tk_root, developer, clones, monkeypatch):
    from tts import qwen3_clone_setup_ui as ui

    monkeypatch.setattr(su, "install_model", lambda *a, **k: pytest.fail("downloaded on open"))
    from tts import qwen3_synth

    monkeypatch.setattr(qwen3_synth, "run_worker", lambda *a, **k: pytest.fail("transcribed on open"))
    win = ui.build_dialog(tk_root, confirm=lambda *a: pytest.fail("asked on open"), player=None)
    try:
        assert win.title() == ui.DIALOG_TITLE == "Developer tools → Reference transcripts"
        shown = " ".join(_texts(win))
        assert "does not replace the transcripts shipped with the app" in shown
        assert not win.session.running and "narration uses the shipped texts" in win.status_var.get()
        assert str(win.btn_shipped.cget("state")) == tk.DISABLED  # nothing selected yet
    finally:
        win.destroy()


# --------------------------------------------------------------------------- #
# K: deliberate selection, bound to voice id + recording hash + text hash
# --------------------------------------------------------------------------- #
def test_a_selection_is_explicit_bound_and_private(developer, clones):
    store = rt.local_transcripts_path()
    approved_store(clones, store)
    assert qt.select_for_narration(["qwen3-male-1"]) == [clones["qwen3-male-1"].label]
    raw = rt.override_selection_path().read_bytes()
    doc = json.loads(raw)
    assert doc == selection_doc(clones, ["qwen3-male-1"])
    assert b"local words" not in raw and str(store).encode() not in raw  # hashes only: no text, no path
    picked = rt.load_transcript("qwen3-male-1")
    assert picked.ok and picked.text == "local words for Male-1" and picked.developer_override and picked.source == store
    other = rt.load_transcript("qwen3-male-2")
    assert other.text == bundled("qwen3-male-2") and not other.developer_override  # only what was chosen
    assert qt.selected_voice_ids() == ["qwen3-male-1"] and rt.voice_availability("qwen3-male-1") == (True, "ok")
    assert "Developer mode: 1 cloned voice(s) narrate" in "\n".join(install_ui.state_lines())


def test_a_selection_is_ignored_in_normal_mode_and_removed_by_returning_to_the_shipped_text(developer, clones, tmp_path,
                                                                                             monkeypatch):
    approved_store(clones, rt.local_transcripts_path())
    qt.select_for_narration(["qwen3-male-1", "qwen3-female-2"])
    use_config(monkeypatch, tmp_path / "off", "[development]\ndeveloper_mode = false\n")
    assert rt.load_transcript("qwen3-male-1").text == bundled("qwen3-male-1")  # the file is still there, and ignored
    use_config(monkeypatch, tmp_path / "on", "[development]\ndeveloper_mode = true\n")
    qt.return_to_shipped(["qwen3-male-1"])
    assert qt.selected_voice_ids() == ["qwen3-female-2"]
    assert rt.load_transcript("qwen3-male-1").text == bundled("qwen3-male-1")
    qt.return_to_shipped()
    assert not rt.override_selection_path().exists()
    assert all(rt.load_transcript(v).text == bundled(v) for v in CLONES)


@pytest.mark.parametrize("entry, message", [
    (None, "approve its transcript"),
    ({"approved": False}, "approve its transcript"),
    ({"approved": "true"}, "approve its transcript"),
    ({"wav_sha256": "0" * 64}, "approve its transcript"),
    ({"text": 42}, "approve its transcript"),
    ({"text": " padded words "}, "cannot be used"),
    ({"text": ""}, "cannot be used"),
])
def test_only_an_approved_bound_usable_local_text_can_be_selected(developer, clones, entry, message):
    store = rt.local_transcripts_path()
    approved_store(clones, store)
    data = json.loads(store.read_text(encoding="utf-8"))
    if entry is None:
        data.pop("Male-1")
    else:
        data["Male-1"].update(entry)
    store.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(su.SetupError, match=message):
        qt.select_for_narration(["qwen3-female-1", "qwen3-male-1"])
    assert not rt.override_selection_path().exists()  # all or nothing: Female-1 was not selected either


def test_selection_refuses_unknown_voices_presets_an_empty_choice_and_a_changed_recording(developer, clones):
    approved_store(clones, rt.local_transcripts_path())
    for ids, message in ((["qwen3-aiden"], "not one of the six"), (["Male-1"], "not one of the six"), ([], "at least one")):
        with pytest.raises(su.SetupError, match=message):
            qt.select_for_narration(ids)
    rt.reference_path(clones["qwen3-male-3"]).write_bytes(b"a different recording")
    with pytest.raises(su.SetupError, match="does not match"):
        qt.select_for_narration(["qwen3-male-3"])
    assert not rt.override_selection_path().exists()


def test_a_preview_never_records_a_developer_selected_text_as_the_shipped_one(developer, clones):
    """Published previews state the shipped transcript; a selected local text is refused, not relabelled (P03D)."""
    approved_store(clones, rt.local_transcripts_path())
    assert vp.transcript_record("qwen3-male-2", {}) == {
        "status": vp.TRANSCRIPT_APPROVED, "text_sha256": rt.transcript_sha256(bundled("qwen3-male-2"))}
    qt.select_for_narration(["qwen3-male-2"])
    with pytest.raises(vp.PreviewError, match="developer-selected local transcript"):
        vp.transcript_record("qwen3-male-2", {})
    _edit_store(lambda d: d["Male-2"].update(text="changed"))  # a failed selection is refused the same way
    with pytest.raises(vp.PreviewError, match="developer-selected local transcript"):
        vp.transcript_record("qwen3-male-2", {})


def test_the_selection_is_keyed_by_stable_voice_id_not_label(developer, clones, monkeypatch):
    approved_store(clones, rt.local_transcripts_path())
    qt.select_for_narration(["qwen3-male-1"])
    relabelled = dataclasses.replace(rt.get_voice("qwen3-male-1"))
    monkeypatch.setattr(type(relabelled), "label", property(lambda self: "Completely Renamed"))
    loaded = rt.load_transcript("qwen3-male-1")
    assert loaded.ok and loaded.developer_override and loaded.text == "local words for Male-1"


# --------------------------------------------------------------------------- #
# L: a stale or damaged selection fails that clone closed -- never the bundle, never a guess
# --------------------------------------------------------------------------- #
def _assert_closed(voice_id: str, fragment: str) -> None:
    loaded = rt.load_transcript(voice_id)
    assert not loaded.ok and loaded.text == "" and loaded.developer_override and fragment in loaded.reason, loaded
    ok, reason = rt.voice_availability(voice_id)
    assert not ok and "Developer tools → Reference transcripts" in reason and fragment in reason
    assert bundled(voice_id) not in reason and "Extract a fresh copy" not in reason


@pytest.fixture()
def selected(developer, clones):
    approved_store(clones, rt.local_transcripts_path())
    qt.select_for_narration(["qwen3-male-1"])
    return clones


def _edit_store(change) -> None:
    store = rt.local_transcripts_path()
    data = json.loads(store.read_text(encoding="utf-8"))
    change(data)
    store.write_text(json.dumps(data), encoding="utf-8")


@pytest.mark.parametrize("change, fragment", [
    (lambda d: d["Male-1"].update(text="re-approved different words"), "changed after it was selected"),
    (lambda d: d["Male-1"].update(approved=False), "no longer approved"),
    (lambda d: d["Male-1"].update(approved="true"), "no longer approved"),
    (lambda d: d.pop("Male-1"), "no longer approved"),
    (lambda d: d["Male-1"].update(wav_sha256="0" * 64), "not bound to the current reference recording"),
    (lambda d: d["Male-1"].update(text="local words for Male-1 "), "unusable"),
    (lambda d: d["Male-1"].update(text="x" * 2001), "unusable"),
])
def test_a_changed_local_store_fails_the_selected_clone_closed(selected, change, fragment):
    _edit_store(change)
    _assert_closed("qwen3-male-1", fragment)
    assert rt.load_transcript("qwen3-male-2").text == bundled("qwen3-male-2")  # unselected clones are unaffected


@pytest.mark.parametrize("damage", ["missing", "not json", "list"])
def test_a_missing_or_unreadable_store_fails_the_selected_clone_closed(selected, damage):
    store = rt.local_transcripts_path()
    if damage == "missing":
        store.unlink()
    else:
        store.write_text("{not json" if damage == "not json" else "[]", encoding="utf-8")
    _assert_closed("qwen3-male-1", "missing or could not be read")


def test_a_selection_for_a_different_recording_fails_closed(selected):
    path = rt.override_selection_path()
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["voices"]["qwen3-male-1"]["wav_sha256"] = "a" * 64
    path.write_text(json.dumps(doc), encoding="utf-8")
    _assert_closed("qwen3-male-1", "made for a different reference recording")


def _damaged_selections(doc: dict) -> dict[str, str]:
    entry = doc["voices"]["qwen3-male-1"]
    variants = {
        "not json": "{",
        "a list": "[]",
        "duplicate key": '{"schema": 1, "schema": 1, "voices": {}}',
        "extra top-level field": json.dumps({**doc, "note": "x"}),
        "no schema": json.dumps({"voices": doc["voices"]}),
        "wrong schema": json.dumps({**doc, "schema": 2}),
        "schema as text": json.dumps({**doc, "schema": "1"}),
        "schema as boolean": json.dumps({**doc, "schema": True}),
        "voices not a table": json.dumps({**doc, "voices": []}),
        "unknown voice id": json.dumps({**doc, "voices": {"qwen3-male-9": entry}}),
        "a preset": json.dumps({**doc, "voices": {"qwen3-aiden": entry}}),
        # a preset's own (empty) reference id, so only the "clones only" rule can refuse it
        "a preset, self-consistent": json.dumps({**doc, "voices": {"qwen3-aiden": {
            **entry, "reference_id": rt.get_voice("qwen3-aiden").reference_name}}}),
        "keyed by label": json.dumps({**doc, "voices": {"Qwen3 - Male 1": entry}}),
        "extra entry field": json.dumps({**doc, "voices": {"qwen3-male-1": {**entry, "text": "x"}}}),
        "missing entry field": json.dumps({**doc, "voices": {"qwen3-male-1": {k: v for k, v in entry.items()
                                                                               if k != "text_sha256"}}}),
        "wrong reference id": json.dumps({**doc, "voices": {"qwen3-male-1": {**entry, "reference_id": "Male-2"}}}),
        "short hash": json.dumps({**doc, "voices": {"qwen3-male-1": {**entry, "text_sha256": "ab"}}}),
        "upper-case hash": json.dumps({**doc, "voices": {"qwen3-male-1": {**entry,
                                                                          "wav_sha256": entry["wav_sha256"].upper()}}}),
        "hash as number": json.dumps({**doc, "voices": {"qwen3-male-1": {**entry, "text_sha256": 7}}}),
        "oversized": json.dumps(doc) + " " * (rt.OVERRIDE_MAX_BYTES + 1),
        "not utf-8": b"\xff\xfe".decode("latin-1"),
    }
    return variants


def test_a_damaged_selection_file_fails_every_clone_closed_and_can_be_cleared(selected):
    path = rt.override_selection_path()
    doc = json.loads(path.read_text(encoding="utf-8"))
    for name, text in _damaged_selections(doc).items():
        path.write_bytes(text.encode("latin-1") if name == "not utf-8" else text.encode("utf-8"))
        for voice_id in CLONES:  # it cannot say which voices were chosen, so none is trusted
            loaded = rt.load_transcript(voice_id)
            assert not loaded.ok and loaded.developer_override and "damaged" in loaded.reason, (name, voice_id)
        assert qt.selected_voice_ids() == CLONES, name
        with pytest.raises(su.SetupError, match="damaged"):
            qt.select_for_narration(["qwen3-male-2"])
        with pytest.raises(su.SetupError, match="damaged"):
            qt.return_to_shipped(["qwen3-male-1"])
    qt.return_to_shipped()  # clearing as a whole always works
    assert not path.exists() and all(rt.load_transcript(v).text == bundled(v) for v in CLONES)


def test_a_selection_folder_or_link_in_place_of_the_file_fails_closed(selected):
    path = rt.override_selection_path()
    path.unlink()
    path.mkdir()
    loaded = rt.load_transcript("qwen3-male-1")
    assert not loaded.ok and "damaged" in loaded.reason


# --------------------------------------------------------------------------- #
# M: a failed save keeps the previous file and the user's work
# --------------------------------------------------------------------------- #
def test_a_selection_that_cannot_be_saved_changes_nothing(developer, clones, monkeypatch):
    approved_store(clones, rt.local_transcripts_path())
    qt.select_for_narration(["qwen3-male-1"])
    before = rt.override_selection_path().read_bytes()

    def locked(src, dst):
        raise PermissionError(13, "simulated: the file is locked by another program")

    monkeypatch.setattr(rt.os, "replace", locked)
    with pytest.raises(su.SetupError, match="could not be saved.*locked by another program"):
        qt.select_for_narration(["qwen3-male-2"])
    assert rt.override_selection_path().read_bytes() == before
    assert [p.name for p in rt.override_selection_path().parent.iterdir() if "selection" in p.name] == [
        "transcript-selection.json"]  # no half-written temporary left behind


def test_the_dialog_selects_only_after_confirming_and_keeps_unsaved_edits(tk_root, developer, clones, monkeypatch):
    from tts import qwen3_clone_setup_ui as ui
    from tts import qwen3_synth

    # the dialog reads the recognizer's on-disk status (a file check); it must never download or run it
    monkeypatch.setattr(su, "install_model", lambda *a, **k: pytest.fail("downloaded"))
    monkeypatch.setattr(qwen3_synth, "run_worker", lambda *a, **k: pytest.fail("transcribed"))
    approved_store(clones, rt.local_transcripts_path())
    answers, asked = [False, True], []
    win = ui.build_dialog(tk_root, confirm=lambda parent, title, text: asked.append(text) or answers.pop(0), player=None)
    try:
        row = win.rows[3]  # Male-2: an unsaved edit and tick that a selection must not discard
        row["text"].delete("1.0", tk.END)
        row["text"].insert("1.0", "an edit not yet approved")
        row["listened"].set(True)
        win.btn_select.invoke()  # declined
        assert not rt.override_selection_path().exists() and "shipped transcripts are not changed" in asked[0]
        win.btn_select.invoke()  # confirmed
        assert qt.selected_voice_ids() == CLONES and win.rows[0]["state_var"].get().endswith(ui.SELECTED_WORDS)
        assert row["text"].get("1.0", tk.END).strip() == "an edit not yet approved" and row["listened"].get() is True
        assert "now uses your approved text" in win.message_var.get()
        assert str(win.btn_shipped.cget("state")) == tk.NORMAL
        win.btn_shipped.invoke()
        assert not rt.override_selection_path().exists() and "shipped with the app again" in win.message_var.get()
        assert not win.rows[0]["state_var"].get().endswith(ui.SELECTED_WORDS)
    finally:
        win.destroy()


def test_the_dialog_reports_a_failed_selection_save_and_keeps_everything(tk_root, developer, clones, monkeypatch):
    from tts import qwen3_clone_setup_ui as ui

    approved_store(clones, rt.local_transcripts_path())
    win = ui.build_dialog(tk_root, confirm=lambda *a: True, player=None)
    try:
        win.rows[0]["text"].insert("1.0", "kept ")
        monkeypatch.setattr(rt.os, "replace", lambda src, dst: (_ for _ in ()).throw(OSError(28, "simulated: disk full")))
        win.btn_select.invoke()
        assert "could not be saved" in win.message_var.get() and "disk full" in win.message_var.get()
        assert not rt.override_selection_path().exists()
        assert win.rows[0]["text"].get("1.0", tk.END).startswith("kept ")
    finally:
        win.destroy()


def test_the_dialog_says_to_approve_first_when_nothing_is_approved(tk_root, developer, clones):
    from tts import qwen3_clone_setup_ui as ui

    win = ui.build_dialog(tk_root, confirm=lambda *a: pytest.fail("asked with nothing to select"), player=None)
    try:
        win.btn_select.invoke()
        assert win.message_var.get() == ui.NOTHING_APPROVED and not rt.override_selection_path().exists()
    finally:
        win.destroy()


# --------------------------------------------------------------------------- #
# N: the recognizer is acquired only on an explicit, confirmed request
# --------------------------------------------------------------------------- #
def test_developer_mode_drafting_without_the_recognizer_downloads_nothing(developer, clones, monkeypatch, tmp_path):
    monkeypatch.setattr(su, "install_model", lambda *a, **k: pytest.fail("downloaded without being asked"))
    result = qt.create_drafts(jobs_root=tmp_path / "jobs",
                              run_worker=lambda *a, **k: pytest.fail("transcribed without the recognizer"))
    assert not result.ok and not (tmp_path / "jobs").exists()


def test_declining_the_recognizer_confirmation_downloads_nothing(tk_root, developer, clones, monkeypatch):
    from tts import qwen3_clone_setup_ui as ui

    monkeypatch.setattr(qt, "install_recognizer", lambda **kw: pytest.fail("installed without consent"))
    asked = []
    win = ui.build_dialog(tk_root, confirm=lambda parent, title, text: asked.append((title, text)) or False, player=None)
    try:
        win.btn_install.invoke()
        assert asked and asked[0][0] == "Install speech recognizer" and not win.session.running
    finally:
        win.destroy()


# --------------------------------------------------------------------------- #
# Privacy: the selection, like the store, is local state that never ships
# --------------------------------------------------------------------------- #
def test_the_selection_file_is_ignored_and_outside_the_packaged_tree():
    target = REPO_ROOT / "files" / "runtime-data" / "qwen3" / "transcript-selection.json"
    assert subprocess.run(["git", "check-ignore", "-q", str(target)], cwd=REPO_ROOT).returncode == 0
    assert not target.is_relative_to(SCRIPTS)  # the packager walks scripts/ (plus a closed root/reference allowlist)
    assert os.path.relpath(rt.override_selection_path(), rt.runtime_dir()) == "transcript-selection.json"
