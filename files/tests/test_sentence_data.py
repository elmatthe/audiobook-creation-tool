"""v0.7.0 portability remediation: the Edge voices' English sentence data (NLTK ``punkt_tab``), contained and consented.

Before: ``ensure_punkt`` ran at the start of *every* narration and, on a profile without the data, called
``nltk.download`` -- about 18 MB from a moving GitHub branch, no hash, no question, into ``%APPDATA%\\nltk_data``. HOME-PC
had a copy from April, so no qualification run ever reached that path.

Now (``shared.nltk_store``): one verified copy in ``files/runtime-data/nltk_data``, the only folder NLTK searches; a
pinned archive (commit, size, SHA-256) and pinned English files, re-checked before use; fetched only by first-run setup
(disclosed in the wizard) or after a Yes at Create; missing or damaged, an actionable refusal -- never a silent download.
Every test here is offline: archives are generated, openers are fakes, and the suite's own copy is the verified session
copy from conftest.
"""

from __future__ import annotations

import ast
import hashlib
import io
import os
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from shared import bootstrap, nltk_store
from tts import epub2tts_gui as panel_module
from tts.epub2tts_edge import epub2tts_edge as engine

from test_tts_importing import (  # noqa: F401  (fixtures)
    make_panel,
    output_base,
    stubs,
    tk_root,
)
from test_tts_jobs import accept, direct_panel, folder_panel  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"


# --------------------------------------------------------------------------- #
# The pins
# --------------------------------------------------------------------------- #
def test_the_source_is_one_fixed_commit_and_every_file_is_pinned():
    assert nltk_store.SOURCE_COMMIT in nltk_store.SOURCE_URL and "/gh-pages/" not in nltk_store.SOURCE_URL
    assert nltk_store.SOURCE_URL.startswith("https://raw.githubusercontent.com/nltk/nltk_data/")
    assert len(nltk_store.ARCHIVE_SHA256) == 64 and nltk_store.ARCHIVE_SIZE == 4_319_076
    assert set(nltk_store.FILES) == {"abbrev_types.txt", "collocations.tab", "ortho_context.tab", "sent_starters.txt"}
    assert all(len(sha) == 64 and size > 0 for size, sha in nltk_store.FILES.values())
    assert nltk_store.DOWNLOAD_SIZE_TEXT == "about 4.3 MB"


def test_the_suites_verified_copy_is_the_one_nltk_reads_and_it_splits_sentences(_sentence_data_for_tests):
    import nltk

    assert nltk_store.problem() == "", "the pins match the real upstream English files"
    engine.ensure_punkt()
    assert nltk.data.path == [str(nltk_store.data_dir(_sentence_data_for_tests))], "only the app's folder is searched"
    assert engine.sent_tokenize("Dr. Smith went home, i.e. to bed. He slept.") == [
        "Dr. Smith went home, i.e. to bed.", "He slept."]


# --------------------------------------------------------------------------- #
# Missing or damaged: an actionable refusal, never a download
# --------------------------------------------------------------------------- #
def _session_files(root: Path) -> Path:
    return nltk_store.english_dir(root)


def test_missing_data_is_refused_with_what_to_do_and_nothing_is_downloaded(tmp_path, monkeypatch):
    import nltk

    downloads = []
    monkeypatch.setattr(nltk, "download", lambda *a, **k: downloads.append(a))
    monkeypatch.setattr(nltk_store, "_default_root", lambda: tmp_path)
    monkeypatch.setattr(engine, "_SENTENCE_TOKENIZER", None)
    saved = list(nltk.data.path)
    try:
        with pytest.raises(nltk_store.SentenceDataMissing) as refused:
            engine.ensure_punkt()
        assert nltk.data.path == [str(nltk_store.data_dir(tmp_path))], "the profile's copy is never consulted"
        with pytest.raises(nltk_store.SentenceDataMissing):
            engine.sent_tokenize("Any text. Here.")
    finally:
        nltk.data.path[:] = saved
    message = str(refused.value)
    assert "not installed" in message and "Press Create again" in message
    assert "files\\runtime-data\\nltk_data" in message and nltk_store.DOWNLOAD_SIZE_TEXT in message
    assert downloads == []


@pytest.mark.parametrize("damage, expected", [
    (lambda folder: (folder / "ortho_context.tab").write_bytes(b"x" * 236_303), "does not match its SHA-256"),
    (lambda folder: (folder / "sent_starters.txt").write_bytes(b"short"), "not the expected file"),
    (lambda folder: (folder / "collocations.tab").unlink(), "incomplete"),
])
def test_a_damaged_copy_is_reported_not_used(tmp_path, _sentence_data_for_tests, damage, expected):
    import shutil

    shutil.copytree(_session_files(_sentence_data_for_tests), _session_files(tmp_path))
    assert nltk_store.problem(tmp_path) == ""
    damage(_session_files(tmp_path))
    assert expected in nltk_store.problem(tmp_path)


@pytest.mark.skipif(os.name != "nt", reason="NTFS junctions")
def test_a_junction_below_the_app_folder_is_refused(tmp_path, _sentence_data_for_tests):
    import _winapi
    import shutil

    elsewhere = tmp_path / "elsewhere"
    shutil.copytree(_session_files(_sentence_data_for_tests), elsewhere / "tokenizers" / "punkt_tab" / "english")
    app = tmp_path / "app"
    (app / "files" / "runtime-data").mkdir(parents=True)
    _winapi.CreateJunction(str(elsewhere), str(app / "files" / "runtime-data" / "nltk_data"))
    assert "link or junction" in nltk_store.problem(app)
    with pytest.raises(nltk_store.SentenceDataError, match="link or junction"):
        nltk_store.download(app, opener=lambda *a, **k: pytest.fail("no fetch through a junction"))


def test_no_shipped_module_downloads_nltk_data():
    for path in SCRIPTS.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in ("download", "downloader") and \
                    isinstance(node.value, ast.Name) and node.value.id == "nltk":
                pytest.fail(f"{path.relative_to(SCRIPTS)} calls nltk.{node.attr}")


# --------------------------------------------------------------------------- #
# Installing: verified, atomic, contained
# --------------------------------------------------------------------------- #
FAKE_FILES = {"abbrev_types.txt": b"dr\nmr\n", "collocations.tab": b"a\tb\n", "ortho_context.tab": b"the\t3\n",
              "sent_starters.txt": b"he\nshe\n"}


def _fake_archive(path: Path, files=None, extra: dict | None = None) -> tuple[int, str, dict]:
    files = FAKE_FILES if files is None else files
    with zipfile.ZipFile(path, "w") as bundle:
        bundle.writestr("punkt_tab/README", "fixture")
        for name, data in files.items():
            bundle.writestr(nltk_store.MEMBER_PREFIX + name, data)
        for name, data in (extra or {}).items():
            bundle.writestr(name, data)
    pins = {name: (len(data), hashlib.sha256(data).hexdigest()) for name, data in FAKE_FILES.items()}
    return path.stat().st_size, hashlib.sha256(path.read_bytes()).hexdigest(), pins


def _pins(size, sha, files):
    return {"archive_size": size, "archive_sha256": sha, "file_pins": files}


def test_a_matching_archive_installs_the_four_files_with_one_rename_and_leaves_nothing_else(tmp_path):
    archive = tmp_path / "punkt_tab.zip"
    size, sha, files = _fake_archive(archive)
    root = tmp_path / "app"
    nltk_store.install_from_archive(archive, root, **_pins(size, sha, files))
    folder = nltk_store.english_dir(root)
    assert {p.name for p in folder.iterdir()} == set(FAKE_FILES)
    assert sorted(p.name for p in nltk_store.data_dir(root).iterdir()) == ["tokenizers"], "no staging left"
    assert nltk_store.problem(root, file_pins=files) == ""


@pytest.mark.parametrize("case", ["archive-hash", "member-hash", "unsafe-member", "not-a-zip"])
def test_anything_that_does_not_match_installs_nothing(tmp_path, case):
    archive = tmp_path / "punkt_tab.zip"
    if case == "unsafe-member":
        size, sha, files = _fake_archive(archive, extra={"../escape.txt": b"x"})
    elif case == "member-hash":
        size, sha, files = _fake_archive(archive, files={**FAKE_FILES, "sent_starters.txt": b"changed\n"})
    elif case == "not-a-zip":
        archive.write_bytes(b"not a zip")
        size, sha, files = archive.stat().st_size, hashlib.sha256(b"not a zip").hexdigest(), {
            name: (len(data), hashlib.sha256(data).hexdigest()) for name, data in FAKE_FILES.items()}
    else:
        size, sha, files = _fake_archive(archive)
        sha = "0" * 64
    root = tmp_path / "app"
    with pytest.raises(nltk_store.SentenceDataError, match="nothing was installed"):
        nltk_store.install_from_archive(archive, root, **_pins(size, sha, files))
    assert not nltk_store.english_dir(root).exists()


def test_a_damaged_copy_is_replaced_whole(tmp_path):
    archive = tmp_path / "punkt_tab.zip"
    size, sha, files = _fake_archive(archive)
    root = tmp_path / "app"
    damaged = nltk_store.english_dir(root)
    damaged.mkdir(parents=True)
    (damaged / "sent_starters.txt").write_bytes(b"damaged")
    (damaged / "leftover.txt").write_bytes(b"stale")
    nltk_store.install_from_archive(archive, root, **_pins(size, sha, files))
    assert {p.name for p in damaged.iterdir()} == set(FAKE_FILES)
    assert sorted(p.name for p in nltk_store.data_dir(root).iterdir()) == ["tokenizers"]


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def _opener(data: bytes, seen: list):
    def open_(request, timeout):
        seen.append((request.full_url, timeout))
        return _Response(data)
    return open_


def test_a_download_is_checked_then_installed_and_leaves_no_part_file(tmp_path):
    archive = tmp_path / "source.zip"
    size, sha, files = _fake_archive(archive)
    root, seen, progress = tmp_path / "app", [], []
    nltk_store.download(root, opener=_opener(archive.read_bytes(), seen), progress=lambda done, total:
                        progress.append((done, total)), **_pins(size, sha, files))
    assert seen == [(nltk_store.SOURCE_URL, nltk_store.DOWNLOAD_TIMEOUT_S)]
    assert progress[-1] == (size, size)
    assert nltk_store.problem(root, file_pins=files) == ""
    assert sorted(p.name for p in nltk_store.data_dir(root).iterdir()) == ["tokenizers"]


@pytest.mark.parametrize("case", ["wrong-bytes", "too-large", "network", "cancelled"])
def test_a_failed_download_changes_nothing_and_says_why(tmp_path, case, _sentence_data_for_tests):
    import shutil

    archive = tmp_path / "source.zip"
    size, sha, files = _fake_archive(archive)
    root = tmp_path / "app"
    shutil.copytree(_session_files(_sentence_data_for_tests), _session_files(root))  # an earlier, real copy
    before = {p.name: p.read_bytes() for p in _session_files(root).iterdir()}
    data = archive.read_bytes()
    opener, cancel = _opener(data, []), None
    if case == "wrong-bytes":
        opener = _opener(data[:-1] + bytes([data[-1] ^ 0xFF]), [])
    elif case == "too-large":
        opener = _opener(data + b"extra", [])
    elif case == "network":
        def opener(request, timeout):
            raise OSError("getaddrinfo failed")
    else:
        cancel = lambda: True  # noqa: E731
    with pytest.raises(nltk_store.SentenceDataError) as failed:
        nltk_store.download(root, opener=opener, cancel=cancel, **_pins(size, sha, files))
    assert ("cancelled" in str(failed.value)) == (case == "cancelled")
    assert "nothing" in str(failed.value)
    assert {p.name: p.read_bytes() for p in _session_files(root).iterdir()} == before
    assert sorted(p.name for p in nltk_store.data_dir(root).iterdir()) == ["tokenizers"], "no part file left"


def test_without_an_opener_the_real_network_door_is_the_one_the_suite_closes(tmp_path):
    """The default opener is looked up at call time, so the suite's refusal of real downloads applies to it."""
    with pytest.raises(nltk_store.SentenceDataError, match="could not be downloaded"):
        nltk_store.download(tmp_path / "app")


# --------------------------------------------------------------------------- #
# Consent at Create (Edge direct files only)
# --------------------------------------------------------------------------- #
@pytest.fixture
def no_sentence_data(tmp_path, monkeypatch):
    empty = tmp_path / "empty-app"
    empty.mkdir()
    monkeypatch.setattr(nltk_store, "_default_root", lambda: empty)
    return empty


@pytest.fixture
def dialogs(monkeypatch):
    from tkinter import messagebox

    record = SimpleNamespace(asked=[], answer=False, info=[], warnings=[])
    monkeypatch.setattr(messagebox, "askyesno", lambda title, text, **k: record.asked.append(text) or record.answer)
    monkeypatch.setattr(messagebox, "showinfo", lambda title, text, **k: record.info.append(text))
    monkeypatch.setattr(messagebox, "showwarning", lambda title, text, **k: record.warnings.append(text))
    return record


def test_no_at_create_starts_nothing_downloads_nothing_and_says_so(make_panel, output_base, tmp_path, stubs,
                                                                   no_sentence_data, dialogs, monkeypatch):
    fetched = []
    monkeypatch.setattr(panel_module.TtsPanel, "_fetch_sentence_data", lambda self: fetched.append(1) or "")
    panel, _chosen = direct_panel(make_panel, tmp_path, "one.txt")
    assert accept(panel) == {}, "declined: no run, no reservation"
    assert len(dialogs.asked) == 1 and nltk_store.DOWNLOAD_SIZE_TEXT in dialogs.asked[0]
    assert "files\\runtime-data\\nltk_data" in dialogs.asked[0] and "not installed" in dialogs.asked[0]
    assert fetched == [] and "not started" in dialogs.info[0]
    assert not any(output_base.rglob("*.mp3"))


def test_yes_at_create_installs_then_starts_that_same_run(make_panel, output_base, tmp_path, stubs,
                                                         no_sentence_data, dialogs, monkeypatch,
                                                         _sentence_data_for_tests):
    import shutil

    dialogs.answer = True

    def install(self):  # stands in for the modal download: the verified files arrive in the app's store
        shutil.copytree(_session_files(_sentence_data_for_tests), _session_files(no_sentence_data))
        return ""

    monkeypatch.setattr(panel_module.TtsPanel, "_fetch_sentence_data", install)
    panel, _chosen = direct_panel(make_panel, tmp_path, "one.txt")
    captured = accept(panel)
    assert captured and captured["params"]["backend"] == "edge", "the run starts once the data is in place"
    assert nltk_store.problem() == "" and len(dialogs.asked) == 1 and dialogs.warnings == []


def test_a_failed_download_at_create_starts_nothing_and_says_what_to_do(make_panel, output_base, tmp_path, stubs,
                                                                        no_sentence_data, dialogs, monkeypatch):
    dialogs.answer = True
    monkeypatch.setattr(panel_module.TtsPanel, "_fetch_sentence_data", lambda self: (
        "the sentence data could not be downloaded (OSError: offline); nothing was changed"))
    panel, _chosen = direct_panel(make_panel, tmp_path, "one.txt")
    assert accept(panel) == {}
    assert "offline" in dialogs.warnings[0] and "Create again" in dialogs.warnings[0]


@pytest.mark.parametrize("outcome", ["installed", "failed"])
def test_the_download_window_runs_the_fetch_off_the_tk_thread_and_reports_back(make_panel, tmp_path, stubs,
                                                                              monkeypatch, outcome):
    import threading

    threads = []

    def download(self, cancel):
        threads.append(threading.current_thread() is not threading.main_thread())
        assert cancel() is False
        if outcome == "failed":
            raise nltk_store.SentenceDataError("offline; nothing was changed")

    monkeypatch.setattr(panel_module.TtsPanel, "_download_sentence_data", download)
    panel, _chosen = direct_panel(make_panel, tmp_path, "one.txt")
    error = panel._fetch_sentence_data()
    assert threads == [True], "the network work never runs on the Tk thread"
    assert error == ("" if outcome == "installed" else "offline; nothing was changed")


def test_a_folder_only_edge_run_never_asks(make_panel, output_base, tmp_path, stubs, no_sentence_data, dialogs):
    panel, _roots = folder_panel(make_panel, tmp_path)
    assert accept(panel), "the batch route does not split sentences with NLTK"
    assert dialogs.asked == []


def test_needs_sentence_data_follows_the_route():
    direct = SimpleNamespace(mirroring_root=None)
    folder = SimpleNamespace(mirroring_root=Path("Library"))
    assert panel_module.needs_sentence_data(SimpleNamespace(files=(folder, direct))) is True
    assert panel_module.needs_sentence_data(SimpleNamespace(files=(folder,))) is False
    source = Path(panel_module.__file__).read_text(encoding="utf-8")
    assert 'backend == "edge" and needs_sentence_data(snapshot)' in source


@pytest.mark.parametrize("backend, direct, required", [
    ("edge", True, True), ("edge", False, False), ("kokoro", True, False), ("chatterbox", True, False),
    ("qwen3", True, False),
])
def test_the_worker_requires_the_data_only_where_nltk_is_used(monkeypatch, backend, direct, required):
    """Kokoro, Chatterbox and Qwen3 never depend on the sentence data, so its absence cannot stop them."""
    asked = []
    monkeypatch.setattr(panel_module, "ensure_punkt", lambda: asked.append(1))
    context = object.__new__(panel_module._RunContext)
    context.params = {"backend": backend}
    context.items = [{"direct": direct}]
    context.filter_resumable = lambda: None
    context.run_all_items = lambda: None
    context.finish = lambda settler: None
    context.execute()
    assert bool(asked) is required


# --------------------------------------------------------------------------- #
# First-run setup: disclosed, fetched once, never fatal
# --------------------------------------------------------------------------- #
class _Log:
    def __init__(self):
        self.lines = []

    def line(self, text):
        self.lines.append(text)


def test_setup_fetches_missing_data_and_a_failure_is_not_fatal(tmp_path, monkeypatch):
    monkeypatch.setattr(bootstrap, "REPO_ROOT", tmp_path)
    calls = []
    monkeypatch.setattr(bootstrap.nltk_store, "download", lambda root: calls.append(root))
    log = _Log()
    assert bootstrap.fetch_sentence_data(log) is True and calls == [tmp_path]

    def fail(root):
        raise nltk_store.SentenceDataError("the sentence data could not be downloaded (offline); nothing was changed")

    monkeypatch.setattr(bootstrap.nltk_store, "download", fail)
    log = _Log()
    assert bootstrap.fetch_sentence_data(log) is False
    assert any("ask again" in line for line in log.lines)


def test_setup_does_not_fetch_data_that_is_already_intact(tmp_path, monkeypatch, _sentence_data_for_tests):
    import shutil

    shutil.copytree(_session_files(_sentence_data_for_tests), _session_files(tmp_path))
    monkeypatch.setattr(bootstrap, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(bootstrap.nltk_store, "download", lambda root: pytest.fail("already intact"))
    assert bootstrap.fetch_sentence_data(_Log()) is True


def test_the_wizard_discloses_the_sentence_data_before_begin_setup():
    source = Path(bootstrap.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    wizard = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "run_with_gui")
    text = ast.get_source_segment(source, wizard)
    assert "English " in text and "sentence data the Edge voices use" in text and "DOWNLOAD_SIZE_TEXT" in text
    assert "NLTK's data repository" in text and "Everything is kept inside this folder" in text
    assert bootstrap.BASE_SETUP_STEPS == 5
    run_setup = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "run_setup")
    assert "fetch_sentence_data(log)" in ast.get_source_segment(source, run_setup)
