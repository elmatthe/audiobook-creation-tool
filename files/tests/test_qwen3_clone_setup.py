"""v0.6.7 — setting the six cloned Qwen3 voices up in the app: draft their reference transcripts locally, then confirm.

What is pinned:

* the speech recognizer is a pinned, verified model that is installed only when asked, never by "Install Both";
* drafts are made from verified copies of the bundled recordings, inside ``.venv-qwen3``, and are saved ``approved: false``;
  an approval already given is never replaced by a draft; nothing of the text reaches a log or the event stream;
* only the user's own confirmation (text, "I listened", the recording on disk unchanged) writes ``approved: true``, bound to
  the recording's SHA-256, and the app's loader then accepts it;
* the dialog drives exactly those steps and the install dialog opens it once the Base model is installed.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
import types
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from tts import qwen3_install_ui as install_ui
from tts import qwen3_runtime as rt
from tts import qwen3_setup as su
from tts import qwen3_synth
from tts import qwen3_clone_setup as qt
from tts import qwen3_worker as worker

from test_qwen3_runtime import install_clone_fixture, install_environment, install_model, sandbox  # noqa: F401
from test_tts_importing import tk_root  # noqa: F401

REPO_ROOT = Path(__file__).resolve().parents[2]
TINY = {"model.safetensors": b"tiny weights", "config.json": b"{}"}
CLONES = ["qwen3-female-1", "qwen3-female-2", "qwen3-male-1", "qwen3-male-2", "qwen3-male-3", "qwen3-male-4"]


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# --------------------------------------------------------------------------- #
# The pinned recognizer
# --------------------------------------------------------------------------- #
def test_the_real_manifest_pins_the_recognizer_and_keeps_it_out_of_the_voice_models():
    raw = json.loads((REPO_ROOT / "scripts" / "tts" / "qwen3_models.json").read_text("utf-8"))
    entry = raw["transcriber"]
    assert entry["repo"] == "openai/whisper-small.en" and entry["revision"] == "e8727524f962ee844a7319d92be39ac1bd25655a"
    assert entry["license"] == "apache-2.0" and len(entry["files"]) == 11
    assert entry["files"]["model.safetensors"] == {
        "size": 966992008, "sha256": entry["files"]["model.safetensors"]["sha256"]}
    assert sum(f["size"] for f in entry["files"].values()) == entry["total_bytes"] == 970930930
    assert rt.TRANSCRIBER not in rt.MODEL_KEYS and "transcriber" not in raw["models"]  # not a voice model
    spec = rt.model_spec(rt.TRANSCRIBER)
    assert spec.voices == () and spec.directory.name == "whisper-small.en-e8727524"
    assert rt.TRANSCRIBER not in su.normalize_components(["both"])  # "Install Both" never fetches the recognizer


@pytest.fixture()
def with_recognizer(sandbox, monkeypatch):
    """The sandbox manifest plus a tiny recognizer entry."""
    manifest = rt.load_manifest()
    manifest["transcriber"] = {"label": "speech recognizer (test)", "repo": "openai/whisper-small.en", "revision": "c" * 40,
                               "license": "apache-2.0", "dir": "whisper-test",
                               "files": {name: {"size": len(data), "sha256": _sha(data)} for name, data in TINY.items()}}
    return sandbox


def put_recognizer(*, marker=True, corrupt=None):
    spec = rt.model_spec(rt.TRANSCRIBER)
    for name, data in TINY.items():
        path = spec.directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data[:-1] if name == corrupt else data)  # truncated: what the cheap status check can see
    if marker:
        rt.write_model_marker(rt.TRANSCRIBER)


def test_recognizer_status_is_honest_about_absent_partial_damaged_and_installed(with_recognizer):
    ok, reason = rt.transcriber_status()
    assert not ok and reason.startswith("The speech recognizer (") and reason.endswith("is not installed.")
    put_recognizer(marker=False)
    assert "partly installed" in rt.transcriber_status()[1]
    put_recognizer(corrupt="config.json")
    assert not rt.transcriber_status()[0]
    put_recognizer()
    assert rt.transcriber_status() == (True, "ok")


def test_installing_the_recognizer_uses_the_verified_installer_under_the_install_lock(with_recognizer, monkeypatch):
    calls = []
    monkeypatch.setattr(su, "install_model", lambda key, **kw: (calls.append(key), put_recognizer()))
    result = qt.install_recognizer(disk_free=lambda path: 10**12)
    assert result.ok and calls == [rt.TRANSCRIBER] and "Create drafts" in result.message
    assert qt.install_recognizer(disk_free=lambda path: 10**12).message.startswith("The speech recognizer is already installed")
    assert calls == [rt.TRANSCRIBER]  # not downloaded twice


def test_the_recognizer_is_refused_without_disk_space_and_reports_a_cancel(with_recognizer, monkeypatch):
    monkeypatch.setattr(su, "install_model", lambda key, **kw: pytest.fail("downloaded without space"))
    result = qt.install_recognizer(disk_free=lambda path: 10)
    assert not result.ok and "Not enough free disk space" in result.message

    def cancelled(key, **kw):
        raise su.SetupCancelled()

    monkeypatch.setattr(su, "install_model", cancelled)
    assert qt.install_recognizer(disk_free=lambda path: 10**12).cancelled


# --------------------------------------------------------------------------- #
# Where each clone stands
# --------------------------------------------------------------------------- #
def store(tmp_path, monkeypatch, data=None):
    path = tmp_path / "transcripts.json"
    monkeypatch.setenv(rt.TRANSCRIPTS_ENV, str(path))
    if data is not None:
        path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_rows_say_missing_draft_approved_or_stale_for_each_of_the_six(tmp_path, monkeypatch):
    voice = {v.voice_id: v for v in qt.clone_voices()}
    path = store(tmp_path, monkeypatch, {
        "Female-1": {"text": "words", "approved": True, "wav_sha256": voice["qwen3-female-1"].reference_sha256},
        "Female-2": {"text": "words", "approved": False, "wav_sha256": voice["qwen3-female-2"].reference_sha256},
        "Male-1": {"text": "words", "approved": True, "wav_sha256": "0" * 64}})
    states = {r.voice_id: r.state for r in qt.rows()}
    assert [r.voice_id for r in qt.rows()] == CLONES
    assert states == {"qwen3-female-1": "approved", "qwen3-female-2": "draft", "qwen3-male-1": "stale",
                      "qwen3-male-2": "missing", "qwen3-male-3": "missing", "qwen3-male-4": "missing"}
    assert qt.store_path() == path  # the same file the loader reads
    path.write_text("not json", encoding="utf-8")
    assert {r.state for r in qt.rows()} == {"missing"}  # a broken file never crashes the dialog
    with pytest.raises(su.SetupError, match="could not be read"):
        qt.read_store()


# --------------------------------------------------------------------------- #
# Drafts
# --------------------------------------------------------------------------- #
class FakeWorker:
    """Stands in for ``qwen3_synth.run_worker``: checks the job, writes the result file, reports the outcome."""

    def __init__(self, texts=None, terminal="done", cancel=False):
        self.jobs, self.texts, self.terminal, self.cancel = [], texts or {}, terminal, cancel

    def __call__(self, job, job_dir, *, python, script, env, cancel_check=None, log=print, **kw):
        self.jobs.append(job)
        self.seen = {i["name"]: (Path(i["wav"]).parent == job_dir, _sha(Path(i["wav"]).read_bytes())) for i in job["items"]}
        log("library chatter")
        if self.cancel:
            from shared.cancellation import ConversionCancelled

            raise ConversionCancelled("Conversion cancelled by user.")
        Path(job["out_file"]).write_text(json.dumps({i["name"]: self.texts.get(i["name"], f"Draft words for {i['name']}.")
                                                     for i in job["items"]}), encoding="utf-8")
        return qwen3_synth.WorkerRun(terminal={"event": self.terminal, "message": "the recognizer failed"},
                                     chunk_events=[], loaded={}, returncode=0)


@pytest.fixture()
def drafting(with_recognizer, monkeypatch, tmp_path):
    install_environment(with_recognizer)
    put_recognizer()
    voices = {vid: install_clone_fixture(with_recognizer, monkeypatch, vid) for vid in CLONES}
    monkeypatch.setattr(rt, "environment_status", lambda: (True, "ok"))
    path = store(tmp_path, monkeypatch)
    return voices, path, tmp_path / "jobs"


def test_drafts_are_made_from_verified_copies_saved_unapproved_and_the_job_folder_is_removed(drafting):
    voices, path, jobs = drafting
    fake = FakeWorker()
    result = qt.create_drafts(run_worker=fake, jobs_root=jobs)
    assert result.ok and "Drafts made for 6 voice(s)" in result.message
    job = fake.jobs[0]
    assert job["kind"] == "transcribe" and Path(job["model_dir"]) == rt.model_spec(rt.TRANSCRIBER).directory
    assert all(inside and sha == voices[f"qwen3-{n.lower()}"].reference_sha256 for n, (inside, sha) in fake.seen.items())
    saved = json.loads(path.read_text("utf-8"))
    for vid, voice in voices.items():
        entry = saved[voice.reference_name]
        assert entry["approved"] is False and entry["wav_sha256"] == voice.reference_sha256
        assert entry["text"] == f"Draft words for {voice.reference_name}." and entry["source"] == qt.DRAFT_SOURCE
        assert not rt.load_transcript(vid).ok  # a draft is never usable by the app
    assert not any(jobs.iterdir())  # the copies and the result file are gone


def test_an_approval_is_never_replaced_by_a_draft(drafting):
    voices, path, jobs = drafting
    female = voices["qwen3-female-1"]
    path.write_text(json.dumps({female.reference_name: {"text": "my words", "approved": True,
                                                        "wav_sha256": female.reference_sha256}}), encoding="utf-8")
    fake = FakeWorker()
    qt.create_drafts(run_worker=fake, jobs_root=jobs)
    assert "Female-1" not in [i["name"] for i in fake.jobs[0]["items"]]  # not even transcribed again
    assert json.loads(path.read_text("utf-8"))["Female-1"]["text"] == "my words"
    path.write_text(json.dumps({v.reference_name: {"text": "w", "approved": True, "wav_sha256": v.reference_sha256}
                                for v in voices.values()}), encoding="utf-8")
    assert qt.create_drafts(run_worker=lambda *a, **k: pytest.fail("ran"), jobs_root=jobs).message.startswith("All six")


@pytest.mark.parametrize("fake, expected", [(FakeWorker(terminal="failed"), "the recognizer failed"),
                                            (FakeWorker(cancel=True), "Cancelled")])
def test_a_failed_or_cancelled_draft_run_saves_nothing(drafting, fake, expected):
    voices, path, jobs = drafting
    result = qt.create_drafts(run_worker=fake, jobs_root=jobs)
    assert not result.ok and expected in result.message and not path.exists() and not any(jobs.iterdir())


def test_a_recording_that_is_not_the_registered_one_is_skipped_not_transcribed(drafting, monkeypatch):
    voices, path, jobs = drafting
    rt.reference_path(voices["qwen3-male-2"]).write_bytes(b"RIFF a different recording")
    fake = FakeWorker()
    result = qt.create_drafts(run_worker=fake, jobs_root=jobs)
    assert "Male-2" not in fake.seen and "Skipped" in result.message and "Qwen3 - Male 2" in result.message
    assert "Male-2" not in json.loads(path.read_text("utf-8"))


def test_drafting_needs_the_engine_and_the_recognizer_first(with_recognizer, monkeypatch, tmp_path):
    store(tmp_path, monkeypatch)
    monkeypatch.setattr(rt, "environment_status", lambda: (False, "The Qwen3 voice engine is not installed."))
    assert "voice engine is needed first" in qt.create_drafts(run_worker=lambda *a, **k: pytest.fail("ran")).message
    monkeypatch.setattr(rt, "environment_status", lambda: (True, "ok"))
    assert "speech recognizer" in qt.create_drafts(run_worker=lambda *a, **k: pytest.fail("ran")).message


def test_the_draft_text_never_reaches_the_log_or_the_events(drafting):
    voices, path, jobs = drafting
    lines = []
    fake = FakeWorker(texts={"Male-4": "secret marmalade words"})

    def run(job, job_dir, **kw):
        kw["log"] = lambda line: lines.append(line)
        return fake(job, job_dir, **kw)

    qt.create_drafts(run_worker=run, jobs_root=jobs)
    assert lines and all("marmalade" not in line for line in lines)  # the fake worker logged; the words were not in it


# --------------------------------------------------------------------------- #
# The user's confirmation
# --------------------------------------------------------------------------- #
def test_approving_requires_listening_and_text_and_binds_to_the_recording(drafting):
    voices, path, jobs = drafting
    with pytest.raises(su.SetupError, match="I listened"):
        qt.approve({"qwen3-male-1": ("Words.", False)})
    with pytest.raises(su.SetupError, match="1-2000 characters"):
        qt.approve({"qwen3-male-1": ("   ", True)})
    with pytest.raises(su.SetupError, match="not one of the six"):
        qt.approve({"qwen3-aiden": ("Words.", True)})
    assert not path.exists()  # nothing written by a refused approval
    assert qt.approve({"qwen3-male-1": ("  The words\n spoken. ", True)}, today="2026-10-21") == ["Qwen3 - Male 1"]
    entry = json.loads(path.read_text("utf-8"))["Male-1"]
    assert entry == {"text": "The words spoken.", "approved": True, "wav_sha256": voices["qwen3-male-1"].reference_sha256,
                     "text_sha256": rt.transcript_sha256("The words spoken."), "approved_by": qt.APPROVED_BY,
                     "approved_on": "2026-10-21"}
    loaded = rt.load_transcript("qwen3-male-1")
    assert loaded.ok and loaded.text == "The words spoken."  # the app now accepts it
    assert not rt.load_transcript("qwen3-male-2").ok  # and only that one


def test_a_recording_changed_on_disk_cannot_be_approved(drafting):
    voices, path, jobs = drafting
    rt.reference_path(voices["qwen3-female-2"]).write_bytes(b"RIFF swapped")
    with pytest.raises(su.SetupError):
        qt.approve({"qwen3-female-2": ("Words.", True)})
    assert not path.exists()


def test_approving_one_voice_keeps_the_others_drafts(drafting):
    voices, path, jobs = drafting
    qt.create_drafts(run_worker=FakeWorker(), jobs_root=jobs)
    qt.approve({"qwen3-female-2": ("Corrected words.", True)})
    states = {r.voice_id: r.state for r in qt.rows()}
    assert states["qwen3-female-2"] == "approved" and [s for v, s in states.items() if v != "qwen3-female-2"] == ["draft"] * 5


def test_the_store_is_local_and_untracked_and_never_ships():
    import subprocess

    target = rt.local_transcripts_path()
    assert "runtime-data" in target.parts
    assert subprocess.run(["git", "check-ignore", "-q", str(target)], cwd=REPO_ROOT).returncode == 0
    from shared import release

    assert not any("runtime-data" in a or "transcripts" in a for a in release.REFERENCE_ASSETS)


# --------------------------------------------------------------------------- #
# The worker's transcribe job (fake model stack)
# --------------------------------------------------------------------------- #
def fake_stack(monkeypatch, *, text="Heard words."):
    torch = types.ModuleType("torch")
    torch.cuda = types.SimpleNamespace(is_available=lambda: False)
    torch.version = types.SimpleNamespace(cuda=None)
    torch.no_grad = lambda: __import__("contextlib").nullcontext()
    torch.from_numpy = lambda a: a
    torchaudio = types.ModuleType("torchaudio")
    torchaudio.functional = types.SimpleNamespace(resample=lambda a, src, dst: types.SimpleNamespace(
        numpy=lambda: np.zeros(int(len(a) * dst / src), dtype="float32")))
    transformers = types.ModuleType("transformers")
    seen = {}

    class Processor:
        @classmethod
        def from_pretrained(cls, path, local_files_only):
            seen["offline"] = local_files_only
            return cls()

        def __call__(self, audio, sampling_rate, return_tensors):
            seen["rate"], seen["samples"] = sampling_rate, len(audio)
            return types.SimpleNamespace(input_features=types.SimpleNamespace(to=lambda device: "features"))

        def batch_decode(self, ids, skip_special_tokens):
            return [f"  {text}  "]

    class Model:
        @classmethod
        def from_pretrained(cls, path, local_files_only):
            return cls()

        def to(self, device):
            seen["device"] = device
            return self

        def eval(self):
            return self

        def generate(self, features, max_new_tokens):
            return [[1, 2, 3]]

    transformers.WhisperProcessor, transformers.WhisperForConditionalGeneration = Processor, Model
    for name, module in (("torch", torch), ("torchaudio", torchaudio), ("transformers", transformers)):
        monkeypatch.setitem(sys.modules, name, module)
    return seen


def test_the_worker_transcribes_into_a_file_not_into_its_output(tmp_path, monkeypatch, capsys):
    seen = fake_stack(monkeypatch, text="Secret words heard.")
    wav = tmp_path / "Male-1.wav"
    sf.write(str(wav), np.zeros(24000 * 15, dtype="float32"), 24000, subtype="PCM_16")
    job = {"kind": "transcribe", "model_dir": str(tmp_path), "items": [{"name": "Male-1", "wav": str(wav)}],
           "out_file": str(tmp_path / "out.json"), "cancel_file": str(tmp_path / "cancel")}
    assert worker.run_transcribe(job) == worker.EXIT_OK
    assert json.loads((tmp_path / "out.json").read_text("utf-8")) == {"Male-1": "Secret words heard."}
    out = capsys.readouterr().out
    assert "Secret words" not in out and '"event": "done"' in out
    assert seen["offline"] is True and seen["rate"] == 16000 and seen["samples"] == 16000 * 15 and seen["device"] == "cpu"


def test_the_worker_refuses_a_recording_longer_than_it_can_read_and_honours_cancel(tmp_path, monkeypatch, capsys):
    fake_stack(monkeypatch)
    wav = tmp_path / "long.wav"
    sf.write(str(wav), np.zeros(16000 * 31, dtype="float32"), 16000, subtype="PCM_16")
    job = {"kind": "transcribe", "model_dir": str(tmp_path), "items": [{"name": "X", "wav": str(wav)}],
           "out_file": str(tmp_path / "out.json"), "cancel_file": str(tmp_path / "cancel")}
    assert worker.run_transcribe(job) == worker.EXIT_FAILED and not (tmp_path / "out.json").exists()
    assert "longer than 30 s" in capsys.readouterr().out
    (tmp_path / "cancel").write_text("cancel", encoding="utf-8")
    assert worker.run_transcribe(job) == worker.EXIT_CANCELED


def test_main_dispatches_the_transcribe_kind(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(worker, "run_transcribe", lambda job: seen.append(job["kind"]) or 0)
    path = tmp_path / "job.json"
    path.write_text(json.dumps({"kind": "transcribe"}), encoding="utf-8")
    assert worker.main(["w", str(path)]) == 0 and seen == ["transcribe"]


# --------------------------------------------------------------------------- #
# The dialogs
# --------------------------------------------------------------------------- #
tk = pytest.importorskip("tkinter")


def enabled(button) -> bool:
    return str(button.cget("state")) != "disabled"


class FakePlayer:
    def __init__(self):
        self.played, self.stopped = [], 0

    def play(self, path):
        self.played.append(Path(path))

    def stop(self):
        self.stopped += 1


@pytest.fixture()
def dialog(tk_root, drafting):
    from tts import qwen3_clone_setup_ui as ui

    made = []

    def build(**kwargs):
        kwargs.setdefault("confirm", lambda parent, title, text: True)
        kwargs.setdefault("player", FakePlayer())
        win = ui.build_dialog(tk_root, **kwargs)
        made.append(win)
        return win

    yield build
    for win in made:
        try:
            win.destroy()
        except tk.TclError:
            pass


def test_the_dialog_lists_the_six_voices_and_plays_each_original_recording(dialog, drafting):
    voices, path, jobs = drafting
    player = FakePlayer()
    win = dialog(player=player)
    assert [r["voice_id"] for r in win.rows] == CLONES
    assert [r["state_var"].get() for r in win.rows] == ["No transcript yet"] * 6
    win.rows[2]["btn_play"].invoke()
    assert player.played == [rt.reference_path(voices["qwen3-male-1"])]
    assert not enabled(win.btn_install) and enabled(win.btn_drafts)  # recognizer installed, engine ready


def test_approving_in_the_dialog_needs_the_tick_and_then_makes_the_voice_usable(dialog, drafting):
    voices, path, jobs = drafting
    qt.create_drafts(run_worker=FakeWorker(), jobs_root=jobs)
    changed = []
    win = dialog(on_change=lambda: changed.append(1))
    row = win.rows[5]
    assert "Male-4" in row["text"].get("1.0", tk.END)
    win.btn_approve.invoke()
    assert "Tick" in win.message_var.get() and not rt.load_transcript("qwen3-male-4").ok
    row["text"].delete("1.0", tk.END)
    row["text"].insert("1.0", "The corrected words.")
    row["listened"].set(True)
    win.btn_approve.invoke()
    assert rt.load_transcript("qwen3-male-4").text == "The corrected words." and changed == [1]
    assert win.rows[5]["state_var"].get() == "Approved" and "Qwen3 - Male 4" in win.message_var.get()


def test_installing_the_recognizer_asks_first_with_the_size(dialog, drafting, monkeypatch):
    spec = rt.model_spec(rt.TRANSCRIBER)
    for name in TINY:
        (spec.directory / name).unlink()
    (spec.directory / rt.MARKER_NAME).unlink()
    asked = []
    win = dialog(confirm=lambda parent, title, text: asked.append(text) or False)
    assert enabled(win.btn_install) and not enabled(win.btn_drafts)
    monkeypatch.setattr(qt, "install_recognizer", lambda **kw: pytest.fail("installed without consent"))
    win.btn_install.invoke()
    assert asked and rt.format_bytes(qt.recognizer_size()) in asked[0] and "this computer" in asked[0]
    assert not win.session.running


def test_creating_drafts_runs_in_the_background_and_fills_the_rows(dialog, drafting, monkeypatch):
    voices, path, jobs = drafting
    monkeypatch.setattr(qt, "create_drafts", lambda **kw: (qt.write_store(
        {v.reference_name: {"text": "fresh draft", "approved": False, "wav_sha256": v.reference_sha256}
         for v in voices.values()}), su.SetupResult(True, "Drafts made for 6 voice(s)."))[1])
    win = dialog()
    win.btn_drafts.invoke()
    deadline = time.monotonic() + 10
    while win.session.running and time.monotonic() < deadline:
        time.sleep(0.01)
    win.poll()
    assert all(r["text"].get("1.0", tk.END).strip() == "fresh draft" for r in win.rows)
    assert [r["state_var"].get() for r in win.rows] == ["Draft: listen, correct, approve"] * 6


def test_the_install_dialog_offers_clone_setup_once_the_base_model_is_installed(tk_root, with_recognizer, monkeypatch):
    opened = []
    win = install_ui.build_dialog(tk_root, confirm=lambda *a: True, open_clones=lambda parent: opened.append(parent))
    try:
        assert not enabled(win.btn_clones)  # nothing installed yet
        install_environment(with_recognizer)
        install_model(with_recognizer, "base")
        win.refresh()
        assert enabled(win.btn_clones)
        assert any("Cloned voices set up: 0 of 6" in line for line in install_ui.state_lines())
        win.btn_clones.invoke()
        assert opened == [win]
    finally:
        win.destroy()


def test_the_six_rows_scroll_inside_a_box_that_fits_a_768_pixel_screen(dialog, drafting, monkeypatch):
    win = dialog()
    win.update_idletasks()
    box = int(win.rows_canvas.cget("height"))
    assert 240 <= box <= 560
    assert box <= max(240, win.winfo_screenheight() - 420)  # the rest of the dialog keeps its room on a short screen
    win.rows_canvas.update_idletasks()
    assert win.rows_canvas.bbox("all")[3] > 0  # the rows live inside the scrolled area


# --------------------------------------------------------------------------- #
# A save that fails is reported, keeps the user's work and can be retried (v0.6.7, audit ACT67-AUD-007)
#
# Every store here is the synthetic one the ``drafting`` fixture points ACT_QWEN3_TRANSCRIPTS at; conftest fingerprints
# the real transcripts file around every test, so none of this can touch a real approval.
# --------------------------------------------------------------------------- #
def _store_bytes(path: Path) -> bytes:
    return path.read_bytes() if path.exists() else b""


def _fail_replace(monkeypatch):
    def locked(src, dst):
        raise PermissionError(13, "simulated: the file is locked by another program")

    monkeypatch.setattr(rt.os, "replace", locked)


def _fail_open(monkeypatch):
    real_open = open

    def refused(file, mode="r", *args, **kwargs):
        if "x" in mode:  # only the store's own exclusive-create write; reading the recordings still works
            raise PermissionError(13, "simulated: the folder is read-only")
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(rt, "open", refused, raising=False)


def _fail_write(monkeypatch):
    real_open = open

    class Full:
        def __init__(self, handle):
            self._handle = handle

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self._handle.close()

        def write(self, text):
            raise OSError(28, "simulated: no space left on the disk")

    def opener(file, mode="r", *args, **kwargs):
        handle = real_open(file, mode, *args, **kwargs)
        return Full(handle) if "x" in mode else handle

    monkeypatch.setattr(rt, "open", opener, raising=False)


def _fail_mkdir(monkeypatch):
    def refused(self, *args, **kwargs):
        raise PermissionError(13, "simulated: cannot create the folder")

    monkeypatch.setattr(qt.Path, "mkdir", refused)


FAULTS = {"replace": _fail_replace, "open": _fail_open, "write": _fail_write, "mkdir": _fail_mkdir}


@pytest.mark.parametrize("fault", sorted(FAULTS))
def test_a_store_that_cannot_be_written_raises_the_setup_error_and_keeps_the_old_file(drafting, monkeypatch, fault):
    voices, path, jobs = drafting
    qt.approve({"qwen3-female-1": ("Already approved words.", True)}, today="2026-10-20")
    before = _store_bytes(path)
    with monkeypatch.context() as m:
        FAULTS[fault](m)
        with pytest.raises(su.SetupError, match="could not be saved") as caught:
            qt.approve({"qwen3-male-2": ("New words.", True)})
    assert "simulated" in str(caught.value) and "click Approve again" in str(caught.value)
    assert _store_bytes(path) == before, "the previous approvals are byte-for-byte intact"
    assert not path.with_name(path.name + ".tmp").exists(), "no partial file is left behind"
    assert rt.load_transcript("qwen3-female-1").ok and not rt.load_transcript("qwen3-male-2").ok


def test_the_dialog_shows_a_failed_save_keeps_the_edits_and_ticks_and_a_retry_succeeds(dialog, drafting, monkeypatch):
    voices, path, jobs = drafting
    qt.create_drafts(run_worker=FakeWorker(), jobs_root=jobs)
    changed = []
    win = dialog(on_change=lambda: changed.append(1))
    row = win.rows[5]
    row["text"].delete("1.0", tk.END)
    row["text"].insert("1.0", "The corrected words.")
    row["listened"].set(True)
    before = _store_bytes(path)
    with monkeypatch.context() as m:
        _fail_replace(m)
        win.btn_approve.invoke()  # used to raise PermissionError into Tk's callback handler and show nothing
    message = win.message_var.get()
    assert "could not be saved" in message and "simulated" in message
    assert "Approved:" not in message and changed == []
    assert row["text"].get("1.0", tk.END).strip() == "The corrected words." and row["listened"].get() is True
    assert row["state_var"].get() != "Approved" and _store_bytes(path) == before
    assert not rt.load_transcript("qwen3-male-4").ok
    win.btn_approve.invoke()  # the fault is gone: the very same edits are approved on retry
    assert rt.load_transcript("qwen3-male-4").text == "The corrected words." and changed == [1]
    assert row["state_var"].get() == "Approved" and "Qwen3 - Male 4" in win.message_var.get()


def test_an_unexpected_error_during_approval_is_shown_not_lost(dialog, drafting, monkeypatch):
    """Not a storage error: reading the recording fails. The dialog must still say so and keep the user's work."""
    voices, path, jobs = drafting
    win = dialog()
    row = win.rows[0]
    row["text"].insert("1.0", "Words I typed.")
    row["listened"].set(True)

    def unreadable(voice):
        raise PermissionError(13, "simulated: the recording is locked")

    monkeypatch.setattr(rt, "reference_status", unreadable)
    win.btn_approve.invoke()
    assert "could not be saved" in win.message_var.get() and "PermissionError" in win.message_var.get()
    assert "Words I typed." in row["text"].get("1.0", tk.END) and row["listened"].get() is True
    assert not path.exists()
