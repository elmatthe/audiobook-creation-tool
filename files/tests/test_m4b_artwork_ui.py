"""The M4B artwork Tk control — v0.6.4 Phase 6 (the Phase 1 seam, now due).

``mp3_tools/m4b_artwork_ui.py`` is the one artwork chooser/preview control the
M4B Maker uses now and the Metadata Editor will reuse. It carries no policy:
the chooser filter, decoding and the preview are ``m4b_artwork``'s over the
shared capability probe; whether the Book copy is enabled is the model's answer
handed in. Two disabling reasons — Shared override and the run lock — are kept
apart and combined.
"""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path

import pytest
from PIL import Image

tk = pytest.importorskip("tkinter")
from tkinter import ttk  # noqa: E402

import tk_gate  # noqa: E402

from shared import image_capabilities, ui_theme  # noqa: E402
from shared.job_control import ControlKind  # noqa: E402
from shared.job_ui import LockGroup, MainThreadError  # noqa: E402

from mp3_tools import m4b_artwork  # noqa: E402
from mp3_tools import m4b_artwork_ui as art_ui  # noqa: E402
from mp3_tools.m4b_artwork_ui import ArtworkControl  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
UNIVERSAL = REPO_ROOT / "scripts" / "Universal"
MODULE = UNIVERSAL / "mp3_tools" / "m4b_artwork_ui.py"


@pytest.fixture(scope="module")
def tk_root():
    yield from tk_gate.tk_root_session(tk)


@pytest.fixture
def parent(tk_root):
    frame = ttk.Frame(tk_root)
    yield frame
    try:
        frame.destroy()
    except tk.TclError:
        pass


@pytest.fixture
def windows_theme(tk_root):
    style = ttk.Style(tk_root)
    theme = ui_theme.apply_theme(tk_root, style, platform="win32")
    yield theme
    restore = ttk.Style(tk_root)
    if "vista" in restore.theme_names():
        restore.theme_use("vista")


def png(path: Path, size=(120, 90)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (200, 30, 30)).save(path, format="PNG")
    return path


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def listing(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in root.rglob("*")}


class Calls:
    def __init__(self) -> None:
        self.seen: list[str] = []

    def make(self, name):
        return lambda: self.seen.append(name)


def make(parent, calls: Calls, theme=None, shared=False, **kwargs) -> ArtworkControl:
    return ArtworkControl(parent, caption="Book Artwork", theme=theme, shared=shared,
                          on_choose=calls.make("choose"), on_clear=calls.make("clear"), **kwargs)


# --------------------------------------------------------------------------- #
# Preview and source safety
# --------------------------------------------------------------------------- #


def test_a_chosen_image_is_previewed_in_memory_and_never_touched(parent, tmp_path):
    source = png(tmp_path / "art" / "cover.png")
    before, snapshot = sha(source), listing(tmp_path)
    control = make(parent, Calls())
    control.set_path(str(source))
    assert control.path == str(source)
    assert control.has_preview is True
    assert control.preview.cget("text") == ""
    assert sha(source) == before and listing(tmp_path) == snapshot
    control.close()


def test_blank_shows_the_placeholder_and_an_undecodable_path_is_kept_but_unpreviewed(
        parent, tmp_path):
    bad = tmp_path / "bad.jpg"
    bad.write_bytes(b"not an image")
    control = make(parent, Calls())
    control.set_path("")
    assert control.path == "" and not control.has_preview
    assert control.preview.cget("text") == art_ui.NO_ARTWORK
    control.set_path(str(bad))
    assert control.path == str(bad), "the selection is the user's until they change it"
    assert not control.has_preview
    assert control.preview.cget("text") == art_ui.NO_PREVIEW
    control.close()


def test_preview_size_is_bounded_and_not_the_embedded_bytes(parent, tmp_path):
    source = png(tmp_path / "big.png", size=(400, 300))
    control = make(parent, Calls())
    control.set_path(str(source))
    assert control._image is not None
    assert max(control._image.width(), control._image.height()) <= max(art_ui.PREVIEW_MAX)
    assert m4b_artwork.load_cover(source).data == source.read_bytes()
    control.close()


# --------------------------------------------------------------------------- #
# Two disabling reasons, kept apart
# --------------------------------------------------------------------------- #


def test_override_and_run_lock_are_separate_reasons(parent):
    calls = Calls()
    control = make(parent, calls)
    assert control.enabled
    control.set_enabled(False)
    assert not control.enabled and "disabled" in control.btn_choose.state()
    control.set_locked(True)
    control.set_enabled(True)
    assert not control.enabled, "the run still holds it"
    control.set_locked(False)
    assert control.enabled and "disabled" not in control.btn_choose.state()
    control.close()


def test_presses_are_refused_while_disabled_and_routed_while_enabled(parent):
    calls = Calls()
    control = make(parent, calls)
    control.btn_choose.invoke()
    control.btn_clear.invoke()
    assert calls.seen == ["choose", "clear"]
    control.set_enabled(False)
    control.btn_choose.invoke()
    control.btn_clear.invoke()
    assert calls.seen == ["choose", "clear"]
    control.close()


def test_the_control_registers_with_the_shared_lock_group_as_a_processing_option(parent):
    control = make(parent, Calls())
    locks = LockGroup()
    assert art_ui.LOCK_KIND is ControlKind.PROCESSING_OPTION
    locks.register(art_ui.LOCK_KIND, control)
    assert control in locks.registered(ControlKind.PROCESSING_OPTION)
    control.close()


def test_close_is_idempotent_and_disables_everything(parent):
    calls = Calls()
    control = make(parent, calls)
    control.close()
    control.close()
    assert control.closed and "disabled" in control.btn_choose.state()
    control.btn_choose.invoke()
    assert calls.seen == []


def test_tk_reaching_methods_refuse_a_foreign_thread(parent):
    import threading

    control = make(parent, Calls())
    raised: list[BaseException] = []

    def body():
        try:
            control.set_path("")
        except BaseException as exc:  # noqa: BLE001
            raised.append(exc)

    worker = threading.Thread(target=body)
    worker.start()
    worker.join()
    assert raised and isinstance(raised[0], MainThreadError)
    control.close()


# --------------------------------------------------------------------------- #
# Dialog and validation helpers are the service's
# --------------------------------------------------------------------------- #


def test_the_chooser_filter_is_the_shared_probes(monkeypatch, parent):
    seen = {}

    def fake_dialog(**kwargs):
        seen.update(kwargs)
        return ""

    monkeypatch.setattr(art_ui.filedialog, "askopenfilename", fake_dialog)
    assert art_ui.ask_artwork(parent, initialdir=Path.home()) == ""
    assert seen["filetypes"] == m4b_artwork.artwork_filetypes()
    patterns = seen["filetypes"][0][1].split()
    assert patterns == [f"*{s}" for s in image_capabilities.decodable_suffixes()]


def test_validation_accepts_a_decodable_file_and_reports_a_refusal(tmp_path):
    good = png(tmp_path / "ok.png")
    bad = tmp_path / "bad.jpg"
    bad.write_bytes(b"nope")
    errors: list[str] = []
    assert art_ui.validated_artwork(str(good), errors.append) == str(good)
    assert art_ui.validated_artwork("", errors.append) is None
    assert errors == []
    assert art_ui.validated_artwork(str(bad), errors.append) is None
    assert errors and "bad.jpg" in errors[0]


# --------------------------------------------------------------------------- #
# Presentation and structure
# --------------------------------------------------------------------------- #


def test_windows_asks_for_act_styles_and_native_asks_for_none(parent, windows_theme):
    themed = make(parent, Calls(), theme=windows_theme, shared=True)
    assert str(themed.frame.cget("style")).startswith("ACT.")
    assert str(themed.btn_choose.cget("style")).startswith("ACT.")
    themed.close()
    native = make(parent, Calls(), theme={"mode": "aqua", "metrics": {}}, natural_buttons=True)
    assert str(native.frame.cget("style")) == ""
    assert str(native.btn_choose.cget("width")) in ("", "0")
    native.close()


def test_the_adapter_carries_no_policy_no_decoder_and_no_maker_vocabulary():
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            modules.add(node.module or "")
            modules |= {f"{node.module}.{alias.name}" for alias in node.names}
    for banned in ("pillow_heif", "shared.image_capabilities", "shared.book_workspace",
                   "mp3_tools.m4b_maker", "mp3_tools.m4b_maker_workflow",
                   "mp3_tools.m4b_maker_plan", "mp3_tools.m4b_metadata_editor",
                   "mp3_tools.mp3_artwork", "mp3_tools.mp3_tool", "threading", "subprocess"):
        assert banned not in modules, banned
    assert "mp3_tools.m4b_artwork" in modules
    literals = {node.value for node in ast.walk(tree)
                if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    for suffix in (".heic", ".heif", ".jpg", ".jpeg", ".png"):
        assert suffix not in literals, suffix
    for hexish in literals:
        assert not (hexish.startswith("#") and len(hexish) in (4, 7)), f"local colour {hexish}"
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    names |= {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    for policy in ("disabled_fields", "effective_value", "Book", "series", "silence",
                   "chapter_titles"):
        assert policy not in names, policy


def test_the_adapter_is_registered_as_a_plan3_adopter():
    from test_plan3_boundaries import ADOPTED

    assert "mp3_tools/m4b_artwork_ui.py" in ADOPTED
