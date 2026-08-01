"""v0.6.0 Drop 1 Phase 4 — regression hardening for the Windows prototype.

Phases 1-3 already prove the theme contract, the launcher lifecycle, the
editor's public surface and the style isolation. This file adds only what those
did not cover, and deliberately favours *behaviour* contracts over appearance:

- the copy-only output contract and the read-only-original safeguard, exercised
  through the real workers on real files;
- the cooperative-cancellation contract, including what happens to the file
  that was already in flight;
- both build forks producing the same surface every shared method depends on;
- the generic ttk styles surviving a *whole launcher build*, not just theme
  application and one panel;
- the negative half of the drop's scope: no Plan 3 / 6 / 8 behaviour and no new
  persisted settings arrived with the new presentation.

Nothing here re-tests metadata rules or shared-value semantics — this drop adds
no metadata behaviour, and those live in test_m4b_metadata_editor_shared.py.
"""

from __future__ import annotations

import queue
import re
import sys
import threading
from pathlib import Path

import pytest

from mp3_tools import m4b_metadata_editor as editor
from shared import paths
from shared.cancellation import ConversionCancelled

windows_only = pytest.mark.skipif(
    sys.platform != "win32", reason="the ACT design system only applies on win32"
)


# ---------------------------------------------------------------------------
# Copy-only output and the read-only-original safeguard (no Tk, no ffmpeg)
# ---------------------------------------------------------------------------
#
# The workers only touch self._cancel_event and self._log_q, so a bare stub
# calling the unbound method runs the real copy/collision/cancel logic without
# a display. The metadata calls are recorded rather than executed: this drop
# changes no tag semantics, and the point here is *which file* is opened for
# writing, not what is written into it.

class _WorkerStub:
    def __init__(self):
        self._cancel_event = threading.Event()
        self._log_q: queue.Queue = queue.Queue()

    def drain(self):
        out = []
        while True:
            try:
                out.append(self._log_q.get_nowait())
            except queue.Empty:
                return out


@pytest.fixture
def recorded_metadata(monkeypatch):
    """Record every metadata write instead of performing it."""
    calls: list[tuple] = []

    def rec(name):
        def _call(path, *args, **kwargs):
            calls.append((name, Path(path)))
        return _call

    for name in ("write_m4b_tags", "clear_metadata_keep_chapters",
                 "apply_chapter_titles", "clear_series_numbering"):
        monkeypatch.setattr(editor.metadata, name, rec(name))
    return calls


def _sources(tmp_path: Path, n: int = 3) -> list[Path]:
    src = tmp_path / "src"
    src.mkdir()
    made = []
    for i in range(n):
        p = src / f"Book {i + 1}.m4b"
        p.write_bytes(b"ORIGINAL-%d" % i + b"\0" * 64)
        made.append(p)
    return made


def _digest(files: list[Path]) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in files}


def test_save_worker_writes_only_copies_and_never_the_originals(
    tmp_path, recorded_metadata
):
    files = _sources(tmp_path)
    before = _digest(files)
    outdir = tmp_path / "out"
    stub = _WorkerStub()

    editor.M4BMetadataEditorUI._save_worker(
        stub, files, {"artist": "X"}, outdir,
        False, {}, False, 1,
    )

    # Every original is byte-identical, and every write landed on a copy.
    assert _digest(files) == before
    written = {p for _name, p in recorded_metadata}
    assert written, "no metadata write happened at all"
    assert all(p.parent == outdir for p in written), written
    assert not (written & set(files))

    outputs = sorted(p.name for p in outdir.iterdir())
    assert outputs == [p.name for p in files]
    # The copies really are copies of the originals, not new empty files.
    for src in files:
        assert (outdir / src.name).read_bytes() == src.read_bytes()

    kinds = [name for name, _p in recorded_metadata]
    assert kinds.count("write_m4b_tags") == len(files)
    assert "clear_metadata_keep_chapters" not in kinds  # clear_first was False
    assert stub.drain()[-1] == ("done", (len(files), 0, False))


def test_save_worker_never_overwrites_an_input_when_output_is_the_input_folder(
    tmp_path, recorded_metadata
):
    """The collision guard is what makes 'output folder = input folder' safe."""
    files = _sources(tmp_path, 2)
    before = _digest(files)
    outdir = files[0].parent  # the inputs' own folder
    stub = _WorkerStub()

    editor.M4BMetadataEditorUI._save_worker(
        stub, files, {"album": "Y"}, outdir, False, {}, False, 1)

    assert _digest(files) == before, "an original was overwritten"
    written = {p for _n, p in recorded_metadata}
    assert not (written & set(files))
    assert all(p.name.endswith(" (1).m4b") for p in written), written


def test_remove_numbering_worker_is_copy_only_too(tmp_path, recorded_metadata):
    files = _sources(tmp_path, 2)
    before = _digest(files)
    outdir = tmp_path / "out-numbering"
    stub = _WorkerStub()

    editor.M4BMetadataEditorUI._remove_numbering_worker(stub, files, outdir)

    assert _digest(files) == before
    kinds = [name for name, _p in recorded_metadata]
    assert kinds == ["clear_series_numbering"] * len(files)
    assert all(p.parent == outdir for _n, p in recorded_metadata)
    assert stub.drain()[-1] == ("done", (len(files), 0, False))


# ---------------------------------------------------------------------------
# Cooperative cancellation
# ---------------------------------------------------------------------------

def test_cancel_before_the_first_file_writes_nothing(tmp_path, recorded_metadata):
    files = _sources(tmp_path)
    before = _digest(files)
    outdir = tmp_path / "out"
    stub = _WorkerStub()
    stub._cancel_event.set()

    editor.M4BMetadataEditorUI._save_worker(
        stub, files, {"artist": "X"}, outdir, False, {}, False, 1)

    assert recorded_metadata == []
    assert _digest(files) == before
    assert not outdir.exists() or list(outdir.iterdir()) == []
    assert stub.drain()[-1] == ("done", (0, 0, True))


def test_cancel_mid_run_finishes_the_current_file_and_stops_the_rest(
    tmp_path, monkeypatch
):
    """The documented semantics: the in-flight file completes, later files stop."""
    files = _sources(tmp_path, 5)
    before = _digest(files)
    outdir = tmp_path / "out"
    stub = _WorkerStub()
    done: list[Path] = []

    def write(path, *a, **kw):
        done.append(Path(path))
        if len(done) == 2:          # the user presses Cancel during file 2
            stub._cancel_event.set()

    monkeypatch.setattr(editor.metadata, "write_m4b_tags", write)

    editor.M4BMetadataEditorUI._save_worker(
        stub, files, {"artist": "X"}, outdir, False, {}, False, 1)

    assert len(done) == 2, "the in-flight file must still finish"
    assert _digest(files) == before
    ok, fail, cancelled = stub.drain()[-1][1]
    assert (ok, fail, cancelled) == (2, 0, True)
    # Only the finished files reached the output folder, and each is whole.
    outputs = sorted(p.name for p in outdir.iterdir())
    assert outputs == [files[0].name, files[1].name]
    for name in outputs:
        assert (outdir / name).read_bytes() == (files[0].parent / name).read_bytes()


def test_cancellation_uses_the_shared_primitive(tmp_path, monkeypatch):
    """Cancellation still travels through shared.cancellation, not a local flag."""
    files = _sources(tmp_path, 2)
    stub = _WorkerStub()
    stub._cancel_event.set()
    seen: list = []

    def raiser(check):
        seen.append(check())
        if check():
            raise ConversionCancelled()

    monkeypatch.setattr(editor, "raise_if_cancelled", raiser)
    editor.M4BMetadataEditorUI._save_worker(
        stub, files, {}, tmp_path / "o", False, {}, False, 1)
    assert seen == [True]


# ---------------------------------------------------------------------------
# The two build forks, and the Tk-side contracts
# ---------------------------------------------------------------------------

tk = pytest.importorskip("tkinter")
from tkinter import ttk  # noqa: E402

from shared import ui_theme  # noqa: E402


@pytest.fixture(scope="module")
def tk_root():
    try:
        root = tk.Tk()
    except tk.TclError as exc:  # headless box with no display
        pytest.skip(f"Tk cannot open a display here: {exc}")
    root.withdraw()
    yield root
    root.destroy()


@pytest.fixture
def fresh_root(tk_root):
    for child in tk_root.winfo_children():
        child.destroy()
    yield tk_root
    for child in tk_root.winfo_children():
        child.destroy()


def _walk(widget):
    yield widget
    for child in widget.winfo_children():
        yield from _walk(child)


def _style_of(widget) -> str:
    try:
        return str(widget.cget("style"))
    except tk.TclError:
        return ""


#: Everything ``disable_inputs`` reaches for. Both forks must supply all of it,
#: or the busy state would silently miss a control on one platform.
GUARDED = (
    "btn_add", "btn_add_folder", "btn_remove", "btn_clear", "btn_save",
    "btn_clear_tags", "btn_remove_numbering", "btn_cover", "btn_cover_clear",
    "entry_cover", "entry_outdir", "btn_browse_out", "chap_text",
    "btn_chap_prev", "btn_chap_next", "chk_autonumber",
)


def _classic_bundle(base: dict) -> dict:
    """A non-Windows bundle, without lying to sys.platform for a whole build."""
    out = dict(base)
    out["mode"] = "classic"
    out["colors"] = None
    out["metrics"] = None
    return out


@windows_only
def test_both_build_forks_expose_the_same_surface(fresh_root):
    """Every shared method below the builders must work on either fork."""
    style = ttk.Style(fresh_root)
    win_theme = ui_theme.apply_theme(fresh_root, style)

    win = editor.M4BMetadataEditorUI(ttk.Frame(fresh_root), theme=win_theme)
    classic = editor.M4BMetadataEditorUI(ttk.Frame(fresh_root),
                                         theme=_classic_bundle(win_theme))
    fresh_root.update_idletasks()

    assert win._windows is True and classic._windows is False

    for name in GUARDED:
        a, b = getattr(win, name, None), getattr(classic, name, None)
        assert a is not None and b is not None, name
        assert type(a) is type(b), f"{name}: {type(a)} vs {type(b)}"

    assert len(win._field_widgets) == len(classic._field_widgets) \
        == len(editor._FIELDS)

    # The busy transition reaches the same controls and returns identically.
    for ui in (win, classic):
        ui.disable_inputs(True)
        assert all(str(getattr(ui, n).cget("state")) == "disabled"
                   for n in GUARDED), ui._windows
        ui._finish_idle()
        # The pager arrows stay disabled with no files loaded — same on both.
        restored = {n for n in GUARDED
                    if str(getattr(ui, n).cget("state")) != "disabled"}
        assert restored == set(GUARDED) - {"btn_chap_prev", "btn_chap_next"}
        assert ui._busy.is_set() is False


def test_an_aqua_bundle_builds_the_historical_layout(fresh_root):
    """macOS must take the unconverted fork — the check is on mode, not platform."""
    style = ttk.Style(fresh_root)
    base = ui_theme.apply_theme(fresh_root, style)
    aqua = dict(base)
    aqua["mode"] = "aqua"

    ui = editor.M4BMetadataEditorUI(ttk.Frame(fresh_root), theme=aqua)
    assert ui._windows is False
    assert [str(w) for w in _walk(ui) if _style_of(w).startswith("ACT.")] == []
    assert str(ui.cget("style")) == ""


# ---------------------------------------------------------------------------
# Isolation across a whole launcher build
# ---------------------------------------------------------------------------

@windows_only
def test_building_the_whole_app_leaves_the_generic_styles_untouched(
    fresh_root, monkeypatch
):
    """The strongest form of the isolation claim: theme + shell + all six panels.

    Phase 1 snapshotted across theme application and Phase 3 across one panel.
    This snapshots across the entire application coming up, which is what a
    user actually does.
    """
    import launcher

    generic = ("TFrame", "TLabel", "TButton", "TEntry", "TCombobox",
               "TCheckbutton", "TRadiobutton", "TLabelframe",
               "TLabelframe.Label", "TNotebook", "TNotebook.Tab", "Treeview",
               "Treeview.Heading", "Horizontal.TProgressbar",
               "Vertical.TScrollbar", "TSeparator")

    style = ttk.Style(fresh_root)
    if "vista" in style.theme_names():
        style.theme_use("vista")

    def snapshot():
        return {n: (style.layout(n), style.configure(n),
                    style.lookup(n, "background"),
                    style.lookup(n, "foreground"),
                    style.lookup(n, "fieldbackground"),
                    style.map(n)) for n in generic}

    before = snapshot()

    store: dict = {}

    class _Settings:
        @staticmethod
        def get(key, default=None):
            return store.get(key, default)

        @staticmethod
        def set(key, value, **_kw):
            store[key] = value

    monkeypatch.setattr(launcher, "app_settings", _Settings)

    app = launcher.LauncherApp(fresh_root)
    for spec in app._available_tools():
        app.select_tool(spec.key)
    fresh_root.update_idletasks()

    after = snapshot()
    changed = [n for n in generic if before[n] != after[n]]
    assert not changed, f"building the app leaked into generic styles: {changed}"
    assert style.theme_use() == "vista"

    # Only the one converted panel opted in.
    per_panel = {
        key: sorted({_style_of(w) for w in _walk(cont)
                     if _style_of(w).startswith("ACT.")})
        for key, cont in app.containers.items()
    }
    assert per_panel.pop("m4b_metadata"), "the converted panel uses no ACT style"
    assert all(v == [] for v in per_panel.values()), per_panel


# ---------------------------------------------------------------------------
# The negative half of the scope
# ---------------------------------------------------------------------------

#: Words that would betray Plan 3 (Summary/Details log behaviour, ETA, retry,
#: pause/resume, filtering) or Plan 6/8 (per-book workspace) leaking into the
#: shipped panel. The visual specimen lives in the developer-only fixture and
#: is deliberately not reachable from here.
#: Matched on word boundaries — "eta" as a substring lives inside "metadata".
FORBIDDEN_TEXT = ("summary", "details", "eta", "retry", "pause", "resume",
                  "filter", "add book", "duplicate book", "remove book")


@windows_only
def test_the_runtime_editor_contains_no_plan_3_6_or_8_controls(fresh_root):
    style = ttk.Style(fresh_root)
    theme = ui_theme.apply_theme(fresh_root, style)
    ui = editor.M4BMetadataEditorUI(ttk.Frame(fresh_root), theme=theme)
    fresh_root.update_idletasks()

    assert [w for w in _walk(ui) if isinstance(w, ttk.Notebook)] == [], \
        "a Summary/Details notebook must not be in the shipped panel"

    offenders = []
    for widget in _walk(ui):
        try:
            text = str(widget.cget("text")).lower()
        except tk.TclError:
            continue
        for word in FORBIDDEN_TEXT:
            if re.search(rf"\b{re.escape(word)}\b", text):
                offenders.append((str(widget), text, word))
    assert offenders == [], offenders

    # Exactly the two historical text areas: chapter titles and the log.
    texts = [w for w in _walk(ui) if isinstance(w, tk.Text)]
    assert set(texts) == {ui.chap_text, ui.log}

    # Every control is wired to something real — no placeholder actions.
    dead = [str(b.cget("text")) for b in _walk(ui)
            if isinstance(b, ttk.Button) and not str(b.cget("command"))]
    assert dead == [], dead


@windows_only
def test_shared_metadata_grouping_adds_no_precedence_or_disabling(fresh_root):
    """The card is a visual statement of existing batch behaviour, nothing more."""
    style = ttk.Style(fresh_root)
    theme = ui_theme.apply_theme(fresh_root, style)
    ui = editor.M4BMetadataEditorUI(ttk.Frame(fresh_root), theme=theme)

    a, b = Path("a.m4b"), Path("b.m4b")
    ui.files = [a, b]
    ui._tag_cache = {
        a: {"artist": "Shared", "album": "Same", "title": "One"},
        b: {"artist": "Shared", "album": "Same", "title": "Two"},
    }
    ui._chap_counts = {a: 0, b: 0}
    ui._refresh_mode()
    fresh_root.update_idletasks()

    # A populated shared field disables nothing and overrides nothing.
    assert ui.var_artist.get() == "Shared"
    for widget in (*ui._field_widgets, ui.entry_cover, ui.chk_autonumber):
        assert "disabled" not in widget.state(), str(widget)
    # And collection is still driven purely by what is non-blank.
    assert ui._collect_tags() == {"artist": "Shared", "album": "Same"}


def test_no_new_persisted_settings_arrived_with_the_new_presentation():
    """The panel still writes only its two historical dialog-location keys."""
    source = Path(editor.__file__).read_text(encoding="utf-8")
    assert editor.KEY_INPUT_DIR == "m4b_metadata.input_dir"
    assert editor.KEY_COVER_DIR == "m4b_metadata.cover_dir"

    written = {line.split("settings.set(")[1].split(",")[0].strip()
               for line in source.splitlines() if "settings.set(" in line}
    assert written == {"KEY_INPUT_DIR", "KEY_COVER_DIR"}, written
    # The output folder is still deliberately not persisted.
    assert "settings.set(\"m4b_metadata.output" not in source
    assert paths.TOOL_SLUGS["m4b_metadata"] == "M4B-Metadata"
