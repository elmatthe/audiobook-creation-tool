"""v0.7.0 release installer: exact Qwen3 wheels, the consent byte budget, engine scope, the client, the review panel
and Install & Continue.

Nothing here reaches the network, a real pip or a real engine: downloads come from in-memory responses or the local
test hub, pip and the Tk dialogs are seams, and every write is inside ``tmp_path``.
"""
from __future__ import annotations

import hashlib
import io
from pathlib import Path

import pytest

from shared import optional_setup_client as client
from shared import optional_setup_protocol as proto
from tts import model_assets as assets
from tts import optional_setup as osu
from tts import optional_setup_acquire as osa
from tts import qwen3_package_manifest as qm
from tts import qwen3_runtime as rt
from tts import qwen3_setup as su
from tts import qwen3_wheels as qw
from tts import voice_install

from test_optional_setup_acquisition import (FakePip, acquirer, hub_path, install, no_sleep, server)  # noqa: F401
from test_optional_tts_setup import (C, K, SESSION, facts, run_main, sandbox, tiny_assets, world)  # noqa: F401

pytestmark = pytest.mark.usefixtures('production_writes_refused')


# --------------------------------------------------------------------------- #
# In-memory HTTP responses
# --------------------------------------------------------------------------- #
class Response(io.BytesIO):
    def __init__(self, data: bytes, *, status: int = 200, length: int | None = None):
        super().__init__(data)
        self.status = status
        self.headers = {"Content-Length": str(len(data) if length is None else length)}
        self.closed_by_caller = False

    def getcode(self):
        return self.status

    def close(self):
        self.closed_by_caller = True
        super().close()


class Served:
    """An opener serving fixed bytes per URL, recording every request."""

    def __init__(self, files: dict[str, bytes]):
        self.files, self.requests, self.responses = files, [], []

    def __call__(self, request):
        self.requests.append(request.full_url)
        response = Response(self.files[request.full_url])
        self.responses.append(response)
        return response


# --------------------------------------------------------------------------- #
# The real wheel list
# --------------------------------------------------------------------------- #
def test_the_engine_is_the_reviewed_manifests_89_wheels_with_sox_from_its_pinned_supply_commit():
    wheels = qw.wheels()
    assert len(wheels) == 89 and len({w.filename for w in wheels}) == 89
    assert all(w.filename.endswith(".whl") for w in wheels)  # never a source archive: nothing is built
    sox = next(w for w in wheels if w.name == "sox")
    assert (sox.url, sox.size, sox.sha256) == (qm.SOX_SUPPLY_URL, 40164, qm.SOX_WHEEL_SHA256)
    assert qm.SOX_SUPPLY_COMMIT in sox.url and "/main/" not in sox.url
    hosts = {w.url.split("/")[2] for w in wheels if w.name != "sox"}
    assert hosts <= {"files.pythonhosted.org", "download-r2.pytorch.org"}
    assert qw.total_bytes() == sum(w.size for w in wheels)


@pytest.fixture
def tiny_wheels(tmp_path, monkeypatch):
    data = {"a-1.0-py3-none-any.whl": b"alpha" * 10, "b-2.0-py3-none-any.whl": b"beta" * 7}
    wheels = tuple(qw.Wheel(name.split("-")[0], name, f"https://example.invalid/{name}", len(body),
                            hashlib.sha256(body).hexdigest()) for name, body in data.items())
    monkeypatch.setattr(qw, "wheels", lambda: wheels)
    monkeypatch.setattr(qw, "wheel_dir", lambda: tmp_path / "wheels")
    return wheels, Served({w.url: data[w.filename] for w in wheels})


def test_wheels_are_fetched_verified_recorded_and_never_fetched_twice(tiny_wheels):
    wheels, served = tiny_wheels
    assert qw.missing_bytes() == sum(w.size for w in wheels)
    seen = []
    expected = qw.missing_bytes()
    assert qw.fetch(opener=served, progress=lambda d, t, m: seen.append((d, t)), sleep=no_sleep) == expected
    assert sorted(served.requests) == sorted(w.url for w in wheels)
    assert qw.missing() == [] and qw.missing_bytes() == 0
    assert seen[-1] == (sum(w.size for w in wheels),) * 2
    qw.fetch(opener=lambda r: pytest.fail("a verified wheel was fetched again"))


def test_a_same_size_corrupted_wheel_is_found_and_replaced(tiny_wheels):
    wheels, served = tiny_wheels
    qw.fetch(opener=served, sleep=no_sleep)
    target = qw.wheel_dir() / wheels[0].filename
    target.write_bytes(b"x" * wheels[0].size)  # same size, new mtime: the record no longer vouches for it
    assert [w.filename for w in qw.missing()] == [wheels[0].filename]
    qw.fetch(opener=served, sleep=no_sleep)
    assert hashlib.sha256(target.read_bytes()).hexdigest() == wheels[0].sha256


def test_the_install_command_is_offline_hash_checked_and_reads_only_the_verified_wheels(tiny_wheels, tmp_path):
    wheels, served = tiny_wheels
    with pytest.raises(su.SetupError):
        qw.install_command(tmp_path / "python.exe")  # nothing downloaded yet: never a pip run
    qw.fetch(opener=served, sleep=no_sleep)
    command, cwd = qw.install_command(tmp_path / "python.exe")
    assert cwd == qw.wheel_dir()
    for flag in ("--no-index", "--require-hashes", "--no-deps", "--only-binary=:all:", "--isolated",
                 "--require-virtualenv", "--no-cache-dir"):
        assert flag in command
    assert "--index-url" not in command and "--extra-index-url" not in command
    from tts import qwen3_packages
    assert command[1:5] == ["-I", "-B", "-c", qwen3_packages.OFFLINE_BOOTSTRAP]  # network/process refused inside pip
    for w in wheels:
        assert f"file:./{w.filename}#sha256={w.sha256}" in command
    assert (qw.wheel_dir() / qw.LOCK_NAME).read_bytes() == qm.effective_lock(qw.reviewed())


# --------------------------------------------------------------------------- #
# The byte budget at the network door
# --------------------------------------------------------------------------- #
def test_a_response_longer_than_the_budget_is_refused_before_its_body_is_read():
    budget = osa.Budget(10)
    served = Served({"u://big": b"x" * 11})
    opener = osa.ScopedOpener(["u://big"], served, budget)
    with pytest.raises(osa.AcquisitionRefused, match="more than"):
        opener(type("R", (), {"full_url": "u://big"})())
    assert budget.used == 0 and served.responses[0].closed_by_caller


def test_bodies_are_charged_as_they_are_read_and_an_exhausted_budget_sends_no_request():
    budget = osa.Budget(8)
    served = Served({"u://a": b"12345", "u://b": b"123"})
    opener = osa.ScopedOpener(["u://a", "u://b"], served, budget)
    for url in ("u://a", "u://b"):
        with opener(type("R", (), {"full_url": url})()) as response:
            assert response.read1(100)
    assert budget.used == 8
    with pytest.raises(osa.AcquisitionRefused):
        opener(type("R", (), {"full_url": "u://a"})())
    assert served.requests == ["u://a", "u://b"]  # the third request was never sent


def test_a_chatterbox_file_lost_after_the_plan_cannot_expand_the_confirmed_download(world, server):
    """P05B Stage 3 reproduction 3: 7 confirmed bytes, a 300-byte file disappears at the lock."""
    install(world, [C], FakePip(installed="3.8.0"), health={C: True})
    folder = assets.snapshot_dir(assets.chatterbox_set())
    (folder / "vocab.json").unlink()
    pip = FakePip(installed="3.8.0")
    plan = osu.plan_to_json(osu.plan([C], facts=osu.Facts(health={C: True}, python=(3, 12), is_64bit=True,
                                                          package_version=pip.version_of)))
    assert plan["totals"]["download"]["bytes"] == 7

    class Racing(osa.RealAcquirer):
        def acquire(self, plan, consent, **kwargs):
            (folder / "t3_turbo_v1.safetensors").unlink()  # gone between the worker's plan and the lock
            return super().acquire(plan, consent, **kwargs)

    acq = acquirer(pip)
    racing = Racing(opener=acq.opener, runner=pip, disk_free=lambda p: 10**12, sleep=no_sleep,
                    version_of=pip.version_of)
    _code, result, used = install(world, [C], pip, health={C: True}, acq=racing)
    assert result["state"] == proto.FAILED and "more than" in result["error"]["message"]
    assert used.budget.used <= 7 and not (folder / "t3_turbo_v1.safetensors").exists()


# --------------------------------------------------------------------------- #
# Engine scope
# --------------------------------------------------------------------------- #
def test_a_model_only_consent_never_builds_the_engine(sandbox, monkeypatch):  # noqa: F811
    def forbidden(*args, **kwargs):
        pytest.fail("the engine was installed without its consent")
    monkeypatch.setattr(su, "install_environment", forbidden)
    result = su.install(["customvoice"], disk_free=lambda p: 10**13, allow_environment=False,
                        opener=lambda r: pytest.fail("nothing may be downloaded"))
    assert not result.ok and result.message == su.ENGINE_NOT_CONFIRMED


def test_the_acquirer_lets_the_installer_touch_the_engine_only_with_the_engine_unit(world):
    calls = []

    def fake_install(keys, **kwargs):
        calls.append((tuple(keys), kwargs["allow_environment"]))
        return su.SetupResult(True, "ok")

    acq = osa.RealAcquirer(qwen_install=fake_install, qwen_repair=fake_install, disk_free=lambda p: 10**13)
    plan = {"components": [{"id": proto.QWEN3_CUSTOMVOICE, "selected": True, "consent_scope": proto.SCOPE_INSTALL}],
            "units": [{"id": "qwen3-model:customvoice", "components": [proto.QWEN3_CUSTOMVOICE], "label": "m"}]}
    acq.budget = osa.Budget(0)
    acq._acquire_qwen(plan, ["qwen3-model:customvoice"], {u["id"]: u for u in plan["units"]}, [], [],
                      lambda p: None, lambda: False)
    plan["units"].append({"id": "qwen3-engine", "components": [proto.QWEN3_CUSTOMVOICE], "label": "e"})
    acq._acquire_qwen(plan, ["qwen3-engine", "qwen3-model:customvoice"], {u["id"]: u for u in plan["units"]}, [], [],
                      lambda p: None, lambda: False)
    assert calls == [(("customvoice",), False), (("customvoice",), True)]


def test_unknown_size_units_have_an_explicit_ceiling():
    spec = rt.model_spec("base")
    assert osa.unit_ceiling("qwen3-model:base") == spec.total_bytes
    assert osa.unit_ceiling("qwen3-engine") == qw.total_bytes()
    assert osa.unit_ceiling("kokoro-model") == 0


# --------------------------------------------------------------------------- #
# The client
# --------------------------------------------------------------------------- #
def test_the_clients_consent_has_exactly_the_terms_the_worker_derives(world):
    shown = osu.plan_to_json(osu.plan([K], facts=facts(health={K: True})))
    mine, theirs = client.consent_for(shown), osu.consent_for(shown)
    assert mine.terms_json() == theirs.terms_json() and mine.consent_id != theirs.consent_id
    assert client.acquirable(shown) == (K,) and client.needs_install(shown)
    text = client.disclosure(shown)
    assert "Kokoro: Install" in text and "Total download" in text and "SHA-256" in text


def test_the_disclosure_names_what_cannot_be_installed_and_a_ready_component(world):
    shown = osu.plan_to_json(osu.plan([K, C], facts=facts(health={K: True}, busy=[C])))
    assert client.blocked(shown) and C not in client.acquirable(shown)
    assert "cannot be installed now" in client.disclosure(shown)


def test_voice_components_map_by_stable_identity():
    assert voice_install.component_for("kokoro", "af_heart") == proto.KOKORO
    assert voice_install.component_for("chatterbox", "anything") == proto.CHATTERBOX
    assert voice_install.component_for("qwen3", "qwen3-aiden") == proto.QWEN3_CUSTOMVOICE
    assert voice_install.component_for("qwen3", "qwen3-male-4") == proto.QWEN3_BASE
    assert voice_install.component_for("edge", "en-US-SteffanNeural") is None
    assert voice_install.installable("kokoro", "af_heart", "a reference recording is missing") is None
    assert voice_install.installable("kokoro", "af_heart", "The Kokoro voices are not installed") == proto.KOKORO


# --------------------------------------------------------------------------- #
# The review panel (Tk)
# --------------------------------------------------------------------------- #
tk = pytest.importorskip("tkinter")
from test_tts_importing import make_panel, output_base, tk_root  # noqa: E402,F401
from test_tts_jobs import accept, direct_panel  # noqa: E402,F401


def _pump(widget, until, limit=400):
    import time
    for _ in range(limit):
        widget.update()
        if until():
            return
        time.sleep(0.01)
    pytest.fail("the panel never reached the expected state")


def _needs_install_plan(world):
    return osu.plan_to_json(osu.plan([K], facts=facts(health={K: True})))


def test_the_panel_installs_once_after_one_click_and_never_on_skip(world, tk_root):  # noqa: F811
    from shared.optional_setup_panel import OptionalSetupPanel
    plan = _needs_install_plan(world)
    installs, outcomes = [], []

    def run_plan(root, components, **kwargs):
        return {"state": proto.SUCCEEDED, "plan": plan, "error": None}

    def run_install(root, shown, consent, **kwargs):
        installs.append(consent.consent_id)
        return {"state": proto.SUCCEEDED, "plan": None, "error": None, "verified": [K]}

    view = OptionalSetupPanel(tk_root, world, [K], on_done=outcomes.append, run_plan=run_plan,
                              run_install=run_install)
    view.start()
    _pump(view, lambda: view.state == "review")
    assert installs == []  # reviewing is not installing
    view._confirm()
    view._confirm()  # a double click mints nothing more
    _pump(view, lambda: view.state == "done")
    assert len(installs) == 1
    view._finish({"state": "installed", "verified": [K]})
    assert outcomes == [{"state": "installed", "verified": [K]}]
    view.destroy()

    skipped = []
    view = OptionalSetupPanel(tk_root, world, [K], on_done=skipped.append, run_plan=run_plan,
                              run_install=lambda *a, **k: pytest.fail("Skip installed something"))
    view.start()
    _pump(view, lambda: view.state == "review")
    view._finish({"state": "skipped"})
    assert skipped == [{"state": "skipped"}]
    view.destroy()


# --------------------------------------------------------------------------- #
# Install & Continue in the TTS panel
# --------------------------------------------------------------------------- #
def _kokoro_label():
    from tts import voice_registry as vr
    return next(v.display_label for v in vr.VOICES if v.backend == "kokoro")


def test_install_and_continue_resumes_the_frozen_run_exactly_once(make_panel, output_base, tmp_path,  # noqa: F811
                                                                  monkeypatch):
    from tts import epub2tts_gui as panel_module
    installed = {"done": False}
    dialogs = []

    def status(backend, voice_id):
        return (True, "") if installed["done"] else (False, "The Kokoro voices are not installed on this computer.")

    def dialog(panel, component, reason):
        dialogs.append(component)
        assert not output_base.exists() or not any(output_base.iterdir())  # nothing reserved before installing
        from tts import voice_registry as vr
        panel.selected_voice_label.set(vr.DEFAULT_VOICE_LABEL)  # a later change is never read again
        installed["done"] = True
        return {"state": "installed", "verified": [component]}

    monkeypatch.setattr(panel_module.messagebox, "showinfo", lambda *a, **k: pytest.fail("unexpected message"))
    monkeypatch.setattr(panel_module.messagebox, "showwarning", lambda *a, **k: pytest.fail("unexpected warning"))
    panel, _chosen = direct_panel(make_panel, tmp_path, "book.txt", local_assets=status,
                                  installable=lambda b, v, r: proto.KOKORO if b == "kokoro" else None,
                                  install_dialog=dialog)
    panel.selected_voice_label.set(_kokoro_label())
    captured = accept(panel)
    assert dialogs == [proto.KOKORO]
    assert captured and captured["params"]["backend"] == "kokoro"


def test_a_skipped_install_abandons_the_run_and_creates_nothing(make_panel, output_base, tmp_path,  # noqa: F811
                                                               monkeypatch):
    from tts import epub2tts_gui as panel_module
    told = []
    monkeypatch.setattr(panel_module.messagebox, "showinfo", lambda *a, **k: told.append(a))
    panel, _chosen = direct_panel(make_panel, tmp_path, "book.txt",
                                  local_assets=lambda b, v: (False, "Kokoro voices are not installed"),
                                  installable=lambda b, v, r: proto.KOKORO,
                                  install_dialog=lambda panel, c, r: {"state": "skipped"})
    panel.selected_voice_label.set(_kokoro_label())
    captured = accept(panel)
    assert captured == {} and told
    assert not output_base.exists() or not any(output_base.iterdir())


# --------------------------------------------------------------------------- #
# The one approved directory layout (owner clarification 2026-10-30)
# --------------------------------------------------------------------------- #
def test_every_installer_location_is_inside_dot_venv_or_files_never_a_new_top_level_folder():
    root = rt.repo_root()
    assert rt.nested_venv_dir() == root / ".venv" / "engines" / "qwen3"  # never qwen3/, engines/ or .venv-qwen3/
    assert rt.parent_venv_dir() == root / ".venv"
    for folder in (qw.wheel_dir(), assets.hf_hub_root(), assets.record_dir(), rt.models_root(), rt.runtime_dir(),
                   rt.cache_root(), rt.tmp_root(), proto.exchange_root(root)):
        assert folder.is_relative_to(root / "files"), folder


def test_a_source_changed_during_the_install_is_never_narrated_silently(make_panel, output_base, tmp_path,  # noqa: F811
                                                                         monkeypatch):
    from tts import epub2tts_gui as panel_module
    told = []
    monkeypatch.setattr(panel_module.messagebox, "showinfo", lambda *a, **k: told.append(a))
    state = {"installed": False}

    def dialog(panel, component, reason):
        chosen[0].write_text("Chapter One\n\nA different text.\n", encoding="utf-8")  # edited meanwhile
        state["installed"] = True
        return {"state": "installed", "verified": [component]}

    panel, chosen = direct_panel(make_panel, tmp_path, "book.txt",
                                 local_assets=lambda b, v: (True, "") if state["installed"] else
                                 (False, "Kokoro voices are not installed"),
                                 installable=lambda b, v, r: proto.KOKORO, install_dialog=dialog)
    panel.selected_voice_label.set(_kokoro_label())
    captured = accept(panel)
    assert captured == {} and told and "changed" in told[0][1]
    assert not output_base.exists() or not any(output_base.iterdir())
