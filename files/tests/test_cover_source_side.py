"""v0.6.0 Drop 2 Phase 5 — Cover Image source-side modes.

Decision 10A allows Cover Image to write beside its sources, but only behind
three independent gates: the deliberate toggle, the explicit Replace radio, and
a per-run confirmation. This file exists to prove that a source is never
modified unless all three are open, and that a failure before the atomic
replacement boundary leaves the original byte-for-byte intact.

Every image here is generated into ``tmp_path``. No repository media, no user
media, and no real settings or Downloads folder is touched.
"""

from __future__ import annotations

import hashlib
import queue
import threading
from pathlib import Path

import pytest

Image = pytest.importorskip("PIL.Image")
tk = pytest.importorskip("tkinter")
from tkinter import ttk  # noqa: E402

from mp3_tools import cover_resizer as cr  # noqa: E402
from shared import config, output_paths as op  # noqa: E402
from shared import settings as app_settings  # noqa: E402
import tk_gate  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def tk_root():
    yield from tk_gate.tk_root_session(tk)


@pytest.fixture
def fresh_root(tk_root):
    for child in tk_root.winfo_children():
        child.destroy()
    yield tk_root
    for child in tk_root.winfo_children():
        child.destroy()


@pytest.fixture
def output_base(tmp_path, monkeypatch):
    app_settings.use_path(tmp_path / "runtime-data" / "settings.json")
    base = tmp_path / "OutputBase"
    root = tmp_path / "fakerepo"
    (root / "scripts" / "Universal").mkdir(parents=True, exist_ok=True)
    (root / "scripts" / "Universal" / "launcher.py").write_text("#\n", encoding="utf-8")
    (root / "config.toml").write_text(
        "[project]\n"
        f'version = "{config.DEFAULTS["project.version"]}"\n'
        "[output]\n"
        f'base_directory = "{base.as_posix()}"\n',
        encoding="utf-8",
    )
    snapshot = config.load(config_path=root / "config.toml", settings_data={}, repo_root=root)
    monkeypatch.setattr(config, "get_effective", lambda: snapshot)
    config.invalidate()
    try:
        yield base
    finally:
        app_settings.use_path(None)
        config.invalidate()


class _Host:
    """A worker host with only what resize_worker touches."""

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


def make_image(path: Path, size=(200, 400), colour=(200, 30, 30)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, colour).save(path)
    return path


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_worker(host, files, *, mode, size=64, letterbox=True, planner=None,
               source_planner=None, run_dir=None):
    cr.CoverResizerUI.resize_worker(host, {
        "size": size, "letterbox": letterbox, "mode": mode, "files": list(files),
        "run_dir": run_dir, "planner": planner,
        "source_planner": source_planner if source_planner is not None
        else (op.SourceSidePlanner() if mode != cr.MODE_STANDARD else None),
    })


# --------------------------------------------------------------------------- #
# Numbered copies beside the source
# --------------------------------------------------------------------------- #


def test_one_source_produces_a_numbered_sibling(tmp_path):
    src = make_image(tmp_path / "art" / "cover.jpg")
    before = sha(src)
    host = _Host()

    run_worker(host, [src], mode=cr.ACTION_NUMBERED)

    assert sorted(p.name for p in src.parent.iterdir()) == ["cover-1.jpg", "cover.jpg"]
    assert sha(src) == before, "the source must never be the destination"
    with Image.open(src.parent / "cover-1.jpg") as img:
        assert img.size == (64, 64)


def test_the_unnumbered_name_is_never_offered(tmp_path):
    """Beside a source, the plain name *is* the source."""
    src = make_image(tmp_path / "art" / "cover.jpg")
    planner = op.SourceSidePlanner()
    planned = planner.plan_beside(src)
    assert planned.name == "cover-1.jpg"
    assert planned != src


def test_existing_numbered_copies_advance(tmp_path):
    src = make_image(tmp_path / "art" / "cover.jpg")
    make_image(tmp_path / "art" / "cover-1.jpg")
    make_image(tmp_path / "art" / "cover-2.jpg")
    host = _Host()

    run_worker(host, [src], mode=cr.ACTION_NUMBERED)

    assert (src.parent / "cover-3.jpg").exists()


def test_several_sources_in_one_directory_do_not_collide(tmp_path):
    a = make_image(tmp_path / "art" / "cover.jpg")
    b = make_image(tmp_path / "art" / "other.jpg")
    host = _Host()

    run_worker(host, [a, b], mode=cr.ACTION_NUMBERED)

    names = sorted(p.name for p in (tmp_path / "art").iterdir())
    assert names == ["cover-1.jpg", "cover.jpg", "other-1.jpg", "other.jpg"]


def test_same_named_sources_in_different_directories_track_independently(tmp_path):
    a = make_image(tmp_path / "one" / "cover.jpg")
    b = make_image(tmp_path / "two" / "cover.jpg")
    host = _Host()

    run_worker(host, [a, b], mode=cr.ACTION_NUMBERED)

    assert (tmp_path / "one" / "cover-1.jpg").exists()
    assert (tmp_path / "two" / "cover-1.jpg").exists()
    assert sha(a) != sha(tmp_path / "one" / "cover-1.jpg")


def test_two_imports_of_the_same_file_never_overwrite(tmp_path):
    src = make_image(tmp_path / "art" / "cover.jpg")
    before = sha(src)
    host = _Host()

    run_worker(host, [src, src], mode=cr.ACTION_NUMBERED)

    assert sha(src) == before
    assert sorted(p.name for p in src.parent.iterdir()) == [
        "cover-1.jpg", "cover-2.jpg", "cover.jpg",
    ]


def test_numbered_mode_writes_nothing_to_the_output_base(tmp_path, output_base):
    src = make_image(tmp_path / "art" / "cover.jpg")
    host = _Host()

    run_worker(host, [src], mode=cr.ACTION_NUMBERED)

    assert not output_base.exists(), "an exception mode must not reserve a standard run"


def test_a_planning_failure_leaves_the_source_untouched(tmp_path, monkeypatch):
    src = make_image(tmp_path / "art" / "cover.jpg")
    before = sha(src)
    host = _Host()

    def refuse(*_a, **_k):
        raise op.UnsafePathError("planned destination refused", "test")

    monkeypatch.setattr(op.SourceSidePlanner, "plan_beside", refuse)
    run_worker(host, [src], mode=cr.ACTION_NUMBERED)

    assert sha(src) == before
    assert sorted(p.name for p in src.parent.iterdir()) == ["cover.jpg"]


# --------------------------------------------------------------------------- #
# Replacement — the atomic boundary
# --------------------------------------------------------------------------- #


def test_confirmed_replacement_changes_only_that_file(tmp_path):
    src = make_image(tmp_path / "art" / "cover.jpg", size=(200, 400))
    neighbour = make_image(tmp_path / "art" / "unrelated.png", size=(10, 10))
    neighbour_before = sha(neighbour)
    before = sha(src)
    host = _Host()

    run_worker(host, [src], mode=cr.ACTION_REPLACE)

    assert sha(src) != before, "the confirmed replacement should have happened"
    with Image.open(src) as img:
        assert img.size == (64, 64)
    assert sha(neighbour) == neighbour_before, "an unrelated sibling was touched"
    assert sorted(p.name for p in src.parent.iterdir()) == ["cover.jpg", "unrelated.png"]


def test_replacement_leaves_no_temporary_file_behind(tmp_path):
    src = make_image(tmp_path / "art" / "cover.jpg")
    host = _Host()

    run_worker(host, [src], mode=cr.ACTION_REPLACE)

    strays = [p.name for p in src.parent.iterdir()
              if p.name.startswith(op.TEMP_SIBLING_PREFIX)]
    assert strays == []


def test_a_write_failure_before_replacement_preserves_the_original(tmp_path, monkeypatch):
    src = make_image(tmp_path / "art" / "cover.jpg")
    before = sha(src)
    host = _Host()

    def boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(cr, "resize_for_audiobook", boom)
    run_worker(host, [src], mode=cr.ACTION_REPLACE)

    assert sha(src) == before, "the original must survive a failed write"
    strays = [p.name for p in src.parent.iterdir()
              if p.name.startswith(op.TEMP_SIBLING_PREFIX)]
    assert strays == [], "the operation's own temporary file must be cleaned"
    assert any("Error" in str(payload) for _k, payload in host.drain())


def test_a_validation_failure_preserves_the_original(tmp_path, monkeypatch):
    """A resize that produces the wrong size must never be installed."""
    src = make_image(tmp_path / "art" / "cover.jpg")
    before = sha(src)
    host = _Host()

    real = cr.resize_for_audiobook

    def wrong_size(in_path, out_path, size, letterbox):
        return real(in_path, out_path, size=size + 1, letterbox=letterbox)

    monkeypatch.setattr(cr, "resize_for_audiobook", wrong_size)
    run_worker(host, [src], mode=cr.ACTION_REPLACE)

    assert sha(src) == before
    strays = [p.name for p in src.parent.iterdir()
              if p.name.startswith(op.TEMP_SIBLING_PREFIX)]
    assert strays == []


def test_a_replacement_failure_preserves_the_original(tmp_path, monkeypatch):
    src = make_image(tmp_path / "art" / "cover.jpg")
    before = sha(src)
    host = _Host()

    def refuse(_temp, _target):
        raise op.OutputPathError("replace refused", "test")

    monkeypatch.setattr(op, "atomic_replace", refuse)
    run_worker(host, [src], mode=cr.ACTION_REPLACE)

    assert sha(src) == before
    with Image.open(src) as img:
        assert img.size == (200, 400), "the original is still the original"


def test_cancellation_before_replacement_leaves_the_source_unchanged(tmp_path):
    src = make_image(tmp_path / "art" / "cover.jpg")
    before = sha(src)
    host = _Host()
    host._cancel_event.set()

    run_worker(host, [src], mode=cr.ACTION_REPLACE)

    assert sha(src) == before
    assert sorted(p.name for p in src.parent.iterdir()) == ["cover.jpg"]


def test_a_partial_batch_reports_truthfully(tmp_path, monkeypatch):
    """Files already replaced stay replaced; the log must say so."""
    first = make_image(tmp_path / "art" / "a.jpg")
    second = make_image(tmp_path / "art" / "b.jpg")
    second_before = sha(second)
    host = _Host()

    real = cr.resize_for_audiobook
    calls = {"n": 0}

    def fail_on_second(in_path, out_path, size, letterbox):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("device lost")
        return real(in_path, out_path, size=size, letterbox=letterbox)

    monkeypatch.setattr(cr, "resize_for_audiobook", fail_on_second)
    run_worker(host, [first, second], mode=cr.ACTION_REPLACE)

    with Image.open(first) as img:
        assert img.size == (64, 64), "the first file was replaced and stays replaced"
    assert sha(second) == second_before, "the failed file is untouched"
    done = [payload for kind, payload in host.drain() if kind == "done"]
    assert done and "1 of 2 original(s) replaced" in done[0]


def test_the_worker_never_opens_a_source_for_writing(tmp_path, monkeypatch):
    """Before the atomic boundary, the only writable handle is the temporary."""
    src = make_image(tmp_path / "art" / "cover.jpg")
    opened_for_write = []
    real_open = Path.open

    def watched(self, mode="r", *a, **k):
        if any(flag in mode for flag in ("w", "a", "+", "x")):
            opened_for_write.append(Path(self))
        return real_open(self, mode, *a, **k)

    monkeypatch.setattr(Path, "open", watched)
    run_worker(_Host(), [src], mode=cr.ACTION_REPLACE)

    assert src not in opened_for_write


def test_replacement_refuses_a_linked_source(tmp_path):
    src = make_image(tmp_path / "art" / "real.jpg")
    link = tmp_path / "art" / "link.jpg"
    try:
        link.symlink_to(src)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"this environment cannot create a file symlink: {exc}")
    with pytest.raises(op.UnsafePathError):
        op.validate_source_for_replacement(link)


def test_replacement_refuses_a_missing_or_directory_source(tmp_path):
    with pytest.raises(op.UnsafePathError):
        op.validate_source_for_replacement(tmp_path / "gone.jpg")
    folder = tmp_path / "folder.jpg"
    folder.mkdir()
    with pytest.raises(op.UnsafePathError):
        op.validate_source_for_replacement(folder)


def test_an_unsupported_format_is_refused_before_confirmation(fresh_root, tmp_path):
    """A .webp is written as .jpg, so it cannot be replaced under its own name."""
    src = tmp_path / "art" / "cover.webp"
    src.parent.mkdir(parents=True)
    Image.new("RGB", (40, 40), (1, 2, 3)).save(src)

    ui = cr.build_ui(ttk.Frame(fresh_root))
    with pytest.raises(op.UnsafePathError) as excinfo:
        ui._validated_replacement_sources([src])
    assert "numbered copies" in excinfo.value.message


def test_atomic_replace_refuses_a_non_temporary_source(tmp_path):
    a = make_image(tmp_path / "a.jpg")
    b = make_image(tmp_path / "b.jpg")
    with pytest.raises(op.UnsafePathError):
        op.atomic_replace(a, b)


def test_discard_temporary_refuses_a_real_file(tmp_path):
    real = make_image(tmp_path / "keep.jpg")
    with pytest.raises(op.UnsafePathError):
        op.discard_temporary(real)
    assert real.exists()


def test_a_temporary_sibling_lives_next_to_its_source(tmp_path):
    src = make_image(tmp_path / "art" / "cover.jpg")
    temp = op.temporary_sibling(src)
    try:
        assert temp.parent == src.parent, "must share a filesystem for atomic replace"
        assert temp.name.startswith(op.TEMP_SIBLING_PREFIX)
        assert temp.suffix == ".jpg"
        assert temp != src and temp.exists()
    finally:
        op.discard_temporary(temp)


def test_temporary_siblings_are_unique(tmp_path):
    src = make_image(tmp_path / "art" / "cover.jpg")
    temps = [op.temporary_sibling(src) for _ in range(5)]
    try:
        assert len(set(temps)) == 5
    finally:
        for t in temps:
            op.discard_temporary(t)


# --------------------------------------------------------------------------- #
# The confirmation dialog
# --------------------------------------------------------------------------- #


def open_dialog(root, count):
    """Build the real confirmation window without entering its modal loop.

    Wording comes from the production helpers, so this can never assert against
    a stale copy of the text.
    """
    win = cr.build_replacement_dialog(
        root,
        cr.REPLACEMENT_TITLE,
        cr.replacement_message(count),
        cr.replacement_button_label(count),
    )
    root.update_idletasks()
    return win


def test_the_confirmation_shows_the_exact_count_and_plural(fresh_root):
    win = open_dialog(fresh_root, 3)
    assert win.title() == "Confirm replacement of original images"
    assert "for 3 images" in str(win.label_message.cget("text"))
    assert str(win.btn_confirm.cget("text")) == "Replace 3 Original Files"
    win.cancel()


def test_the_confirmation_uses_the_singular_label_for_one_file(fresh_root):
    win = open_dialog(fresh_root, 1)
    assert "for 1 image." in str(win.label_message.cget("text"))
    assert str(win.btn_confirm.cget("text")) == "Replace 1 Original File"
    win.cancel()


def test_cancel_is_the_declared_default_and_the_safe_answer(fresh_root):
    win = open_dialog(fresh_root, 2)
    assert win.default_widget is win.btn_cancel, "Cancel must be the default"
    assert win.default_widget is not win.btn_confirm
    win.btn_cancel.invoke()
    assert win.result["ok"] is False


def test_focus_is_set_on_cancel_and_never_on_the_destructive_button():
    """Asserted in the source: real focus cannot be observed on a withdrawn root.

    Tk defers focus for an unmapped window, so a runtime check here would test
    the test environment rather than the dialog. What matters is that
    ``focus_set`` targets Cancel and nothing targets Replace.
    """
    import ast

    source = Path(cr.__file__).read_text(encoding="utf-8")
    focused = set()
    for node in ast.walk(ast.parse(source)):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "focus_set"
                and isinstance(node.func.value, ast.Name)):
            focused.add(node.func.value.id)
    assert focused == {"btn_cancel"}, focused


def test_enter_on_the_focused_default_cannot_start_a_replacement(fresh_root):
    """Return activates whatever holds focus, and that is Cancel — not Replace."""
    win = open_dialog(fresh_root, 2)
    win.default_widget.invoke()           # what Return would do
    assert win.result["ok"] is False


def test_the_message_states_the_irreversible_and_partial_batch_facts(fresh_root):
    win = open_dialog(fresh_root, 2)
    message = str(win.label_message.cget("text"))
    assert "permanently replace" in message
    assert "cannot undo" in message
    assert "temporary file first" in message
    assert "remain replaced" in message
    assert message.rstrip().endswith("Continue?")
    win.cancel()


def test_escape_cancels(fresh_root):
    win = open_dialog(fresh_root, 2)
    # The window must be mapped for a synthetic key event to be delivered.
    win.deiconify()
    win.update()
    win.event_generate("<Escape>")
    win.update()
    assert win.result["ok"] is False


def test_closing_the_window_cancels(fresh_root):
    """WM_DELETE_WINDOW routes to the same cancel path as the button."""
    win = open_dialog(fresh_root, 2)
    handler = win.protocol("WM_DELETE_WINDOW")
    win.tk.call(handler)
    assert win.result["ok"] is False


def test_confirming_returns_true(fresh_root):
    win = open_dialog(fresh_root, 2)
    win.btn_confirm.invoke()
    assert win.result["ok"] is True


def test_each_run_gets_a_brand_new_dialog(fresh_root):
    """A previous yes cannot carry over: the window is rebuilt every time."""
    first = open_dialog(fresh_root, 1)
    first.btn_confirm.invoke()
    assert first.result["ok"] is True

    second = open_dialog(fresh_root, 1)
    assert second.result["ok"] is False, "a fresh dialog starts unanswered"
    second.btn_cancel.invoke()
    assert second.result["ok"] is False


def test_no_suppression_path_exists_around_the_confirmation():
    """There is no flag, setting or cached answer that can skip the dialog.

    Scoped to identifiers rather than prose: the module legitimately documents
    a *remembered input folder*, which has nothing to do with confirmation.
    """
    import ast

    source = Path(cr.__file__).read_text(encoding="utf-8")
    names = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Name):
            names.add(node.id.lower())
        elif isinstance(node, ast.Attribute):
            names.add(node.attr.lower())
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            names.add(node.value.lower())
    for forbidden in ("dont_ask", "do_not_ask", "suppress_confirm", "skip_confirm",
                      "remember_choice", "confirmed_once"):
        assert not any(forbidden in name for name in names), forbidden
    # The confirmation is reached from exactly one place, unconditionally.
    assert source.count("self.confirm_replacement(") == 1
