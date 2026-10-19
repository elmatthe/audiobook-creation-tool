"""v0.6.7 CP6 — installing, verifying and repairing the Qwen3 voices.

Everything runs offline. Downloads are served by a small local HTTP server that supports ``Range`` and can misbehave on
request (drop the connection, ignore ``Range``, send wrong bytes, redirect, refuse); pip, ``venv`` and the worker probe
are replaced by a fake command runner. The manifest is the same tiny stand-in the runtime tests use, so a "model" is a
few bytes and every branch of the real code (resume, hash check, reuse, repair, cancel) runs for real.
"""

from __future__ import annotations

import http.client
import json
import os
import sys
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from tts import qwen3_runtime as rt
from tts import qwen3_setup as su

from test_qwen3_runtime import (  # noqa: F401  (the sandbox fixture and its builders)
    BASE_ONLY,
    CUSTOM_ONLY,
    TINY_FILES,
    install_environment,
    install_model,
    sandbox,
)


# --------------------------------------------------------------------------- #
# A local stand-in for the model hub
# --------------------------------------------------------------------------- #
class Hub:
    def __init__(self, files: dict[str, bytes]):
        self.files = files  # request path -> bytes
        self.requests: list[dict] = []
        self.drop_once: dict[str, int] = {}  # path -> bytes to send before the connection is cut (first request only)
        self.status: dict[str, int] = {}
        self.ignore_range: set[str] = set()
        self.wrong_bytes: set[str] = set()  # right length, wrong content
        self.redirects: dict[str, str] = {}
        self.slow: set[str] = set()
        hub = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # silence
                pass

            def do_GET(self):  # noqa: N802
                path = self.path
                hub.requests.append({"path": path, "range": self.headers.get("Range"),
                                     "agent": self.headers.get("User-Agent"),
                                     "auth": self.headers.get("Authorization")})
                if path in hub.status:
                    self.send_error(hub.status[path])
                    return
                if path in hub.redirects:
                    self.send_response(302)
                    self.send_header("Location", hub.redirects[path])
                    self.end_headers()
                    return
                data = hub.files.get(path)
                if data is None:
                    self.send_error(404)
                    return
                if path in hub.wrong_bytes:
                    data = bytes((b ^ 0xFF) for b in data)
                start, status = 0, 200
                header = self.headers.get("Range")
                if header and path not in hub.ignore_range:
                    start = int(header.split("=")[1].split("-")[0])
                    if start >= len(data):
                        self.send_error(416)
                        return
                    status = 206
                body = data[start:]
                self.send_response(status)
                self.send_header("Content-Length", str(len(body)))
                if status == 206:
                    self.send_header("Content-Range", f"bytes {start}-{len(data) - 1}/{len(data)}")
                self.end_headers()
                if path in hub.drop_once:
                    cut = hub.drop_once.pop(path)
                    self.wfile.write(body[:cut])
                    self.wfile.flush()
                    self.connection.close()
                    return
                try:
                    self.wfile.write(body)
                except OSError:
                    pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def paths(self) -> list[str]:
        return [r["path"] for r in self.requests]


def url_path(spec: rt.ModelSpec, name: str) -> str:
    return f"/{spec.repo}/resolve/{spec.revision}/{name}"


def opener(request):
    return urllib.request.build_opener().open(request, timeout=10)


@pytest.fixture()
def hub(sandbox, monkeypatch):
    """A running hub holding the tiny stand-in files of both models, with the installer pointed at it."""
    files = {}
    for key, extra in (("customvoice", CUSTOM_ONLY), ("base", BASE_ONLY)):
        spec = rt.model_spec(key)
        for name, data in {**TINY_FILES, **extra}.items():
            files[url_path(spec, name)] = data
    server = Hub(files)
    monkeypatch.setattr(su, "HUB_URL", f"http://127.0.0.1:{server.port}/{{repo}}/resolve/{{revision}}/{{path}}")
    monkeypatch.setattr(su, "DOWNLOAD_BLOCK", 4)  # several reads per file, so a mid-stream cut really is mid-stream
    yield server
    server.close()


def no_sleep(seconds: float) -> None:
    pass


# --------------------------------------------------------------------------- #
# Fake pip / venv / probe
# --------------------------------------------------------------------------- #
class FakeRunner:
    def __init__(self, base: Path):
        self.base = base
        self.commands: list[dict] = []
        self.fail_pip = False
        self.cancel_during_pip = False
        self.fail_venv = False
        self.probe_failure: str | None = None
        self.probe_jobs: list[dict] = []

    def __call__(self, cmd, *, env, cwd, on_line, cancel_check=None):
        self.commands.append({"cmd": [str(c) for c in cmd], "env": env, "cwd": cwd})
        text = " ".join(str(c) for c in cmd)
        if " -m venv " in f" {text} ":
            if self.fail_venv:
                on_line("Error: venv exploded")
                return 1
            python = rt.venv_python()
            python.parent.mkdir(parents=True, exist_ok=True)
            python.write_bytes(b"")
            self.base.mkdir(exist_ok=True)
            (rt.venv_dir() / "pyvenv.cfg").write_text(f"home = {self.base}\nversion = 3.12.10\n", encoding="utf-8")
            return 0
        if "pip" in text:
            su.pip_cache_dir().mkdir(parents=True, exist_ok=True)
            (su.pip_cache_dir() / "wheel").write_bytes(b"cached wheel")
            on_line("Collecting torch==2.10.0+cu128")
            if self.cancel_during_pip:
                raise su.SetupCancelled()
            if self.fail_pip:
                on_line("ERROR: Could not find a version that satisfies the requirement nothing")
                return 1
            on_line("Successfully installed torch-2.10.0+cu128")
            return 0
        if str(cmd[1]).endswith("qwen3_worker.py"):
            job = json.loads(Path(cmd[2]).read_text("utf-8"))
            self.probe_jobs.append(job)
            if self.probe_failure:
                on_line("@@EVENT " + json.dumps({"event": "failed", "stage": "load", "message": self.probe_failure}))
                return 2
            report = {"event": "probe", "versions": {"torch": "2.10.0+cu128"}, "cuda_available": True,
                      "device": "cuda:0", "device_name": "Test GPU"}
            if "model_dir" in job:
                report.update(loaded_on="cuda:0", speakers=["Aiden", "Ryan"])
            on_line("some library noise")
            on_line("@@EVENT " + json.dumps(report))
            on_line("@@EVENT " + json.dumps({"event": "done"}))
            return 0
        raise AssertionError(f"unexpected command {cmd}")


@pytest.fixture()
def runner(sandbox):
    (sandbox / "scripts" / "qwen3-requirements.txt").write_bytes(b"torch==1.0\n")
    return FakeRunner(sandbox / "base-python")


# --------------------------------------------------------------------------- #
# Components and the plan
# --------------------------------------------------------------------------- #
def test_components_are_validated_and_ordered_and_both_means_both():
    assert su.normalize_components(["both"]) == ("customvoice", "base")
    assert su.normalize_components(["base", "customvoice"]) == ("customvoice", "base")
    assert su.normalize_components(["base", "base"]) == ("base",)
    with pytest.raises(su.SetupError, match="Unknown Qwen3 component"):
        su.normalize_components(["dylan"])
    with pytest.raises(su.SetupError, match="at least one"):
        su.normalize_components([])


def test_the_plan_states_sizes_before_anything_is_acquired_and_counts_shared_files_once(sandbox):
    plan = su.plan_install(["both"])
    assert plan.needs_environment and not plan.nothing_to_do
    custom, base = plan.models
    assert {f.action for f in custom.files} == {"download"}
    shared = {n for n in TINY_FILES}
    assert {f.name for f in base.files if f.action == "share"} == shared  # fetched once, copied for the second model
    assert base.download_bytes == len(BASE_ONLY["model.safetensors"])
    assert plan.download_bytes == (rt.environment_download_bytes() + custom.download_bytes + base.download_bytes)
    lines = su.describe_plan(plan)
    text = "\n".join(lines)
    assert "Qwen3 voice engine: about 3.1 GB to download (about 5.3 GB on disk)" in text
    assert "CustomVoice model" in text and "Base model" in text and "shared with the other model" in text
    assert "Total to download:" in text and "Disk space needed:" in text


def test_the_plan_for_a_single_model_does_not_pretend_to_share_with_one_that_is_not_installed(sandbox):
    plan = su.plan_install(["base"])
    assert {f.action for f in plan.models[0].files} == {"download"}
    install_model(sandbox, "customvoice")
    plan = su.plan_install(["base"])  # now the shared files exist on disk, so they are reused
    assert {f.name for f in plan.models[0].files if f.action == "share"} == set(TINY_FILES)


def test_installed_things_are_reported_as_installed_and_present_files_are_reused(sandbox):
    install_environment(sandbox)
    install_model(sandbox, "customvoice")
    plan = su.plan_install(["customvoice"])
    assert plan.nothing_to_do and su.describe_plan(plan) == ["Everything you selected is already installed."]

    (rt.model_spec("base").directory).mkdir(parents=True)
    (rt.model_spec("base").directory / "model.safetensors").write_bytes(BASE_ONLY["model.safetensors"])
    plan = su.plan_install(["both"])
    base = plan.models[1]
    assert {f.name: f.action for f in base.files}["model.safetensors"] == "have"
    assert "already on this computer" in "\n".join(su.describe_plan(plan))
    assert not plan.needs_environment


def test_both_total_counts_the_shared_files_once():
    assert su.both_total_download_bytes() == 8_377_577_824  # the real pinned models: 4.52 GB + 4.54 GB - 687 MB shared


# --------------------------------------------------------------------------- #
# Downloading one file
# --------------------------------------------------------------------------- #
DATA = b"0123456789abcdefghijklmnopqrstuvwxyz" * 3
DIGEST = rt.sha256_file.__globals__["hashlib"].sha256(DATA).hexdigest()


def serve(hub, data=DATA, path="/f.bin"):
    hub.files[path] = data
    return f"http://127.0.0.1:{hub.port}{path}"


def test_a_download_is_verified_and_leaves_no_part_file(hub, tmp_path):
    url = serve(hub)
    target = tmp_path / "out" / "f.bin"
    seen = []
    su.download_file(url, target, len(DATA), DIGEST, opener=opener, progress=seen.append, sleep=no_sleep)
    assert target.read_bytes() == DATA and sum(seen) == len(DATA) and len(seen) > 2
    assert [p.name for p in target.parent.iterdir()] == ["f.bin"]
    request = hub.requests[0]
    assert request["agent"] == "ACT-Qwen3-Setup" and request["auth"] is None  # no credentials of any kind are sent
    assert request["range"] is None


def test_a_cut_connection_resumes_from_the_part_file_with_a_range_request(hub, tmp_path):
    url = serve(hub)
    hub.drop_once["/f.bin"] = 30
    target = tmp_path / "f.bin"
    su.download_file(url, target, len(DATA), DIGEST, opener=opener, sleep=no_sleep)
    assert target.read_bytes() == DATA
    assert [r["range"] for r in hub.requests] == [None, "bytes=30-"]  # the second request asked only for the rest


def test_a_server_that_ignores_range_restarts_the_file_cleanly(hub, tmp_path):
    url = serve(hub)
    target = tmp_path / "f.bin"
    (tmp_path / "f.bin.part").write_bytes(DATA[:20])
    hub.ignore_range.add("/f.bin")
    su.download_file(url, target, len(DATA), DIGEST, opener=opener, sleep=no_sleep)
    assert target.read_bytes() == DATA  # not 20 bytes of old data followed by a whole new copy
    assert hub.requests[0]["range"] == "bytes=20-"


def test_wrong_bytes_of_the_right_length_are_rejected_and_never_installed(hub, tmp_path):
    url = serve(hub)
    hub.wrong_bytes.add("/f.bin")
    target = tmp_path / "f.bin"
    with pytest.raises(su.SetupError, match=r"after 3 attempts.*SHA-256"):
        su.download_file(url, target, len(DATA), DIGEST, opener=opener, sleep=no_sleep, attempts=3)
    assert not target.exists() and not (tmp_path / "f.bin.part").exists()
    assert len(hub.requests) == 3 and all(r["range"] is None for r in hub.requests)  # corruption is not resumed


def test_a_short_file_is_a_failure_not_an_install(hub, tmp_path):
    url = serve(hub)
    target = tmp_path / "f.bin"
    with pytest.raises(su.SetupError, match="after 2 attempts"):
        su.download_file(url, target, len(DATA) + 10, DIGEST, opener=opener, sleep=no_sleep, attempts=2)
    assert not target.exists()  # the server had fewer bytes than the manifest promises: never installed


@pytest.mark.parametrize("code", [401, 403, 404])
def test_a_refusal_is_reported_at_once_without_retrying(hub, tmp_path, code):
    url = serve(hub)
    hub.status["/f.bin"] = code
    with pytest.raises(su.SetupError, match=f"HTTP {code}"):
        su.download_file(url, tmp_path / "f.bin", len(DATA), DIGEST, opener=opener, sleep=no_sleep)
    assert len(hub.requests) == 1


def test_a_server_error_is_retried_with_backoff_then_gives_up_with_progress_kept(hub, tmp_path):
    url = serve(hub)
    hub.status["/f.bin"] = 503
    (tmp_path / "f.bin.part").write_bytes(DATA[:10])
    waits = []
    with pytest.raises(su.SetupError, match="Your progress is kept"):
        su.download_file(url, tmp_path / "f.bin", len(DATA), DIGEST, opener=opener, sleep=waits.append, attempts=3)
    assert len(hub.requests) == 3 and waits == [2.0, 5.0]
    assert (tmp_path / "f.bin.part").read_bytes() == DATA[:10]  # the partial file survives for the next attempt


def test_a_range_that_no_longer_fits_discards_the_part_and_starts_over(hub, tmp_path):
    url = serve(hub)
    (tmp_path / "f.bin.part").write_bytes(DATA[:10])
    hub.status["/f.bin"] = 416
    calls = {"n": 0}

    def flaky_opener(request):
        calls["n"] += 1
        if calls["n"] == 2:
            hub.status.pop("/f.bin")  # the server recovers once the stale part is gone
        return opener(request)

    su.download_file(url, tmp_path / "f.bin", len(DATA), DIGEST, opener=flaky_opener, sleep=no_sleep)
    assert (tmp_path / "f.bin").read_bytes() == DATA


def test_a_redirect_is_followed(hub, tmp_path):
    serve(hub, path="/cdn/blob")
    hub.redirects["/f.bin"] = f"http://127.0.0.1:{hub.port}/cdn/blob"
    su.download_file(f"http://127.0.0.1:{hub.port}/f.bin", tmp_path / "f.bin", len(DATA), DIGEST, opener=opener,
                     sleep=no_sleep)
    assert (tmp_path / "f.bin").read_bytes() == DATA


def test_cancelling_keeps_the_part_and_the_next_attempt_resumes_it(hub, tmp_path):
    url = serve(hub)
    target = tmp_path / "f.bin"
    seen = []

    def progress(n):
        seen.append(n)

    with pytest.raises(su.SetupCancelled):
        su.download_file(url, target, len(DATA), DIGEST, opener=opener, progress=progress,
                         cancel_check=lambda: sum(seen) >= 12, sleep=no_sleep)
    part = tmp_path / "f.bin.part"
    assert part.is_file() and 12 <= part.stat().st_size < len(DATA) and not target.exists()
    held = part.stat().st_size
    su.download_file(url, target, len(DATA), DIGEST, opener=opener, sleep=no_sleep)
    assert target.read_bytes() == DATA and hub.requests[-1]["range"] == f"bytes={held}-"


def test_an_oversized_part_file_is_discarded(hub, tmp_path):
    url = serve(hub)
    (tmp_path / "f.bin.part").write_bytes(DATA + b"extra")
    su.download_file(url, tmp_path / "f.bin", len(DATA), DIGEST, opener=opener, sleep=no_sleep)
    assert (tmp_path / "f.bin").read_bytes() == DATA and hub.requests[0]["range"] is None


def test_the_default_network_door_is_the_one_the_suite_closes(tmp_path):
    """A test that forgets to inject an opener must fail loudly instead of downloading gigabytes."""
    with pytest.raises(AssertionError, match="real network connection"):
        su._default_opener(urllib.request.Request("http://127.0.0.1:9/never"))


def test_the_hub_url_pins_the_immutable_revision():
    spec = rt.model_spec("customvoice")
    url = su.hub_url(spec, "speech_tokenizer/model.safetensors")
    assert url == f"https://huggingface.co/{spec.repo}/resolve/{spec.revision}/speech_tokenizer/model.safetensors"
    assert len(spec.revision) == 40  # a commit, never "main"


# --------------------------------------------------------------------------- #
# Installing a model
# --------------------------------------------------------------------------- #
def test_installing_a_model_downloads_verifies_and_writes_the_marker_last(hub, sandbox):
    events = []
    su.install_model("customvoice", progress=events.append, opener=opener, sleep=no_sleep)
    spec = rt.model_spec("customvoice")
    assert rt.model_status("customvoice") == (True, "ok")
    assert rt.model_file_problems("customvoice", full=True) == []
    assert sorted(hub.paths()) == sorted(url_path(spec, n) for n in spec.files)
    assert events[-1].message.endswith("model installed.") and events[-1].fraction == 1.0
    assert all(e.step == "model:customvoice" for e in events)


def test_a_second_install_of_an_intact_model_downloads_nothing(hub, sandbox):
    su.install_model("customvoice", opener=opener, sleep=no_sleep)
    hub.requests.clear()
    su.install_model("customvoice", opener=opener, sleep=no_sleep)
    assert hub.requests == []  # valid cached assets are reused: no duplicate download
    assert rt.model_status("customvoice") == (True, "ok")


def test_only_the_corrupt_file_is_fetched_again(hub, sandbox):
    su.install_model("customvoice", opener=opener, sleep=no_sleep)
    spec = rt.model_spec("customvoice")
    (spec.directory / "model.safetensors").write_bytes(b"x" * len(CUSTOM_ONLY["model.safetensors"]))  # same size
    (spec.directory / "config.json").write_bytes(b"short")  # wrong size
    hub.requests.clear()
    su.install_model("customvoice", opener=opener, sleep=no_sleep)
    assert sorted(hub.paths()) == sorted([url_path(spec, "model.safetensors"), url_path(spec, "config.json")])
    assert rt.model_file_problems("customvoice", full=True) == []


def test_the_second_model_reuses_the_files_the_two_share(hub, sandbox):
    su.install_model("customvoice", opener=opener, sleep=no_sleep)
    hub.requests.clear()
    events = []
    su.install_model("base", progress=events.append, opener=opener, sleep=no_sleep)
    base = rt.model_spec("base")
    assert hub.paths() == [url_path(base, "model.safetensors")]  # only the file that is genuinely different
    assert rt.model_status("base") == (True, "ok") and rt.model_status("customvoice") == (True, "ok")
    assert any("reused, not downloaded again" in e.message for e in events)
    shared = rt.model_spec("base").directory / "config.json"
    assert shared.read_bytes() == TINY_FILES["config.json"]


def test_a_model_is_not_reported_installed_while_it_is_being_rebuilt(hub, sandbox):
    su.install_model("customvoice", opener=opener, sleep=no_sleep)
    seen = []

    def watch(event):
        seen.append(rt.model_status("customvoice")[0])

    (rt.model_spec("customvoice").directory / "model.safetensors").unlink()
    su.install_model("customvoice", progress=watch, opener=opener, sleep=no_sleep)
    assert seen[:-1] and not any(seen[:-1])  # unmarked until the very last step...
    assert rt.model_status("customvoice")[0] is True  # ...and installed at the end


def test_files_from_a_seed_folder_are_used_when_their_hash_matches_and_ignored_when_it_does_not(hub, sandbox, tmp_path):
    seed = tmp_path / "seed"
    (seed / "speech_tokenizer").mkdir(parents=True)
    (seed / "config.json").write_bytes(TINY_FILES["config.json"])
    (seed / "model.safetensors").write_bytes(b"x" * len(CUSTOM_ONLY["model.safetensors"]))  # right size, wrong hash
    su.install_model("customvoice", opener=opener, sleep=no_sleep, seed_dirs=[seed])
    spec = rt.model_spec("customvoice")
    assert url_path(spec, "config.json") not in hub.paths()  # taken from the seed folder
    assert url_path(spec, "model.safetensors") in hub.paths()  # the impostor was not trusted
    assert rt.model_file_problems("customvoice", full=True) == []


def test_a_cancelled_install_keeps_what_is_done_and_the_next_one_finishes_only_the_rest(hub, sandbox):
    spec = rt.model_spec("customvoice")
    started = []

    def progress(event):
        if event.message.startswith("Downloading "):
            name = event.message.split()[1]
            if name not in started:
                started.append(name)

    with pytest.raises(su.SetupCancelled):
        su.install_model("customvoice", progress=progress, opener=opener, sleep=no_sleep,
                         cancel_check=lambda: len(started) >= 2)  # the second file never begins
    assert rt.model_status("customvoice")[0] is False  # never "installed" half-way
    done_before = [n for n in spec.files if (spec.directory / n).is_file()]
    assert done_before, "files completed before the cancel were kept"
    hub.requests.clear()
    su.install_model("customvoice", opener=opener, sleep=no_sleep)
    assert rt.model_status("customvoice") == (True, "ok")
    assert not set(hub.paths()) & {url_path(spec, n) for n in done_before}  # none of them was fetched again


def test_a_server_that_sends_the_wrong_file_never_produces_an_installed_model(hub, sandbox):
    spec = rt.model_spec("customvoice")
    hub.wrong_bytes.add(url_path(spec, "config.json"))
    with pytest.raises(su.SetupError, match="config.json"):
        su.install_model("customvoice", opener=opener, sleep=no_sleep)
    assert rt.model_status("customvoice")[0] is False and not rt.marker_path("customvoice").exists()


# --------------------------------------------------------------------------- #
# The environment
# --------------------------------------------------------------------------- #
def test_the_environment_install_runs_venv_then_pinned_pip_then_a_probe_and_records_it(sandbox, runner):
    events = []
    probe = su.install_environment(progress=events.append, runner=runner)
    venv_cmd, pip_cmd, probe_cmd = [c["cmd"] for c in runner.commands]
    assert venv_cmd[1:3] == ["-m", "venv"] and venv_cmd[3] == str(rt.venv_dir())
    assert pip_cmd[:3] == [str(rt.venv_python()), "-m", "pip"] and "--no-deps" in pip_cmd
    for flag in ("--isolated", "--require-virtualenv", "--require-hashes"):
        assert flag in pip_cmd, flag  # ignore ambient pip settings; only a venv; only the exact hashed artifacts
    assert Path(pip_cmd[pip_cmd.index("--cache-dir") + 1]).is_relative_to(sandbox)
    assert pip_cmd[pip_cmd.index("--index-url") + 1] == su.PYTORCH_INDEX
    assert pip_cmd[pip_cmd.index("--extra-index-url") + 1] == su.PYPI_INDEX
    assert pip_cmd[pip_cmd.index("-r") + 1] == str(rt.requirements_path())
    assert probe_cmd[:2] == [str(rt.venv_python()), str(rt.worker_script())]
    assert probe["cuda_available"] is True and rt.installed_probe()["device_name"] == "Test GPU"
    assert rt.environment_status() == (True, "ok")
    assert not su.pip_cache_dir().exists()  # a full success gives the download cache's space back
    assert any("Installing the Qwen3 packages" in e.message for e in events)
    pip_env = runner.commands[1]["env"]
    assert "PYTHONPATH" not in pip_env and Path(pip_env["TEMP"]).is_relative_to(sandbox)


def test_a_failed_pip_reports_its_own_words_keeps_the_download_cache_and_records_nothing(sandbox, runner):
    runner.fail_pip = True
    with pytest.raises(su.SetupError, match=r"Installing the Qwen3 packages failed.*Could not find a version"):
        su.install_environment(runner=runner)
    assert su.pip_cache_dir().exists()  # a retry continues instead of starting over
    assert rt.environment_status()[0] is False and "environment" not in rt.read_state()


def test_a_failed_venv_creation_stops_before_pip(sandbox, runner):
    runner.fail_venv = True
    with pytest.raises(su.SetupError, match=r"could not be created.*venv exploded"):
        su.install_environment(runner=runner)
    assert len(runner.commands) == 1


def test_a_failed_probe_is_an_incomplete_install_not_a_success(sandbox, runner):
    runner.probe_failure = "ImportError: DLL load failed while importing _C"
    with pytest.raises(su.SetupError, match="did not start correctly: ImportError: DLL load failed"):
        su.install_environment(runner=runner)
    assert rt.environment_status()[0] is False  # no install record was written


def test_cancelling_during_pip_leaves_the_install_incomplete_and_the_cache_in_place(sandbox, runner):
    runner.cancel_during_pip = True
    with pytest.raises(su.SetupCancelled):
        su.install_environment(runner=runner)
    assert rt.environment_status()[0] is False and su.pip_cache_dir().exists()


def test_an_unsupported_python_is_refused_before_anything_is_created(sandbox, runner, monkeypatch):
    monkeypatch.setattr(sys, "version_info", (3, 13, 1, "final", 0))
    with pytest.raises(su.SetupError, match=r"need Python 3\.12.*Python 3\.13.*Nothing was installed"):
        su.install_environment(runner=runner)
    assert runner.commands == [] and not rt.venv_dir().exists()


def test_a_missing_requirements_file_is_a_clear_error(sandbox, runner):
    (sandbox / "scripts" / "qwen3-requirements.txt").unlink()
    with pytest.raises(su.SetupError, match="requirements file is missing"):
        su.install_environment(runner=runner)


def test_pythonw_is_replaced_by_python_for_the_child_so_output_is_not_lost(tmp_path, monkeypatch):
    (tmp_path / "pythonw.exe").write_bytes(b"")
    (tmp_path / "python.exe").write_bytes(b"")
    monkeypatch.setattr(sys, "executable", str(tmp_path / "pythonw.exe"))
    assert su.console_python() == tmp_path / "python.exe"
    monkeypatch.setattr(sys, "executable", str(tmp_path / "python.exe"))
    assert su.console_python() == tmp_path / "python.exe"


def test_only_the_apps_own_environment_folder_may_be_deleted(sandbox, tmp_path):
    other = tmp_path / "somewhere-else"
    other.mkdir()
    (other / "pyvenv.cfg").write_text("home = x", encoding="utf-8")
    assert not su.safe_to_remove_environment(other)  # a venv, but not ours
    rt.venv_dir().mkdir(parents=True)
    assert not su.safe_to_remove_environment(rt.venv_dir())  # ours, but not a venv (no pyvenv.cfg)
    (rt.venv_dir() / "pyvenv.cfg").write_text("home = x", encoding="utf-8")
    assert su.safe_to_remove_environment(rt.venv_dir())


# --------------------------------------------------------------------------- #
# install(): the whole operation
# --------------------------------------------------------------------------- #
def test_a_first_time_install_of_both_builds_everything_in_order_and_checks_each_model_loads(hub, sandbox, runner):
    events = []
    result = su.install(["both"], progress=events.append, opener=opener, runner=runner, sleep=no_sleep,
                        disk_free=lambda p: 10**12)
    assert result.ok and result.steps == ["environment", "model:customvoice", "verified:customvoice",
                                          "model:base", "verified:base"]
    assert rt.environment_status() == (True, "ok")
    assert rt.model_status("customvoice")[0] and rt.model_status("base")[0]
    loads = [job for job in runner.probe_jobs if "model_dir" in job]
    assert [Path(job["model_dir"]).name for job in loads] == [rt.model_spec(k).dir_name for k in ("customvoice", "base")]
    assert lock_is_free()  # the lock is released
    # the shared files were downloaded once for the pair
    assert sum(1 for p in hub.paths() if p.endswith("/config.json")) == 1


def test_installing_only_customvoice_leaves_base_alone(hub, sandbox, runner):
    result = su.install(["customvoice"], opener=opener, runner=runner, sleep=no_sleep, disk_free=lambda p: 10**12)
    assert result.ok and result.steps == ["environment", "model:customvoice", "verified:customvoice"]
    assert rt.model_status("customvoice") == (True, "ok") and rt.voice_availability("qwen3-aiden") == (True, "ok")
    assert rt.model_status("base")[0] is False and not rt.model_spec("base").directory.exists()


def test_nothing_is_done_when_everything_is_already_installed(hub, sandbox, runner):
    install_environment(sandbox)
    install_model(sandbox, "customvoice")
    result = su.install(["customvoice"], opener=opener, runner=runner)
    assert result.ok and "already installed" in result.message
    assert runner.commands == [] and hub.requests == []


def test_too_little_disk_space_is_refused_before_anything_is_downloaded(hub, sandbox, runner):
    result = su.install(["both"], opener=opener, runner=runner, disk_free=lambda p: 5 * 10**9)
    assert not result.ok and "Not enough free disk space" in result.message and "GB" in result.message
    assert runner.commands == [] and hub.requests == [] and not rt.venv_dir().exists()


def test_a_macos_install_is_refused_with_the_same_not_yet_available_sentence(hub, sandbox, runner, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    result = su.install(["both"], opener=opener, runner=runner)
    assert not result.ok and result.message == rt.platform_reason()
    assert runner.commands == [] and hub.requests == []


def test_an_install_failure_is_a_result_with_a_sentence_never_an_exception(hub, sandbox, runner):
    runner.fail_pip = True
    result = su.install(["customvoice"], opener=opener, runner=runner, sleep=no_sleep, disk_free=lambda p: 10**12)
    assert not result.ok and "Installing the Qwen3 packages failed" in result.message and not result.cancelled
    assert hub.requests == []  # the models are not fetched on top of a broken engine
    assert lock_is_free()

    runner.fail_pip = False
    hub.status[url_path(rt.model_spec("customvoice"), "model.safetensors")] = 404
    result = su.install(["customvoice"], opener=opener, runner=runner, sleep=no_sleep, disk_free=lambda p: 10**12)
    assert not result.ok and "HTTP 404" in result.message


def test_cancelling_returns_a_cancelled_result_and_keeps_progress(hub, sandbox, runner):
    state = {"n": 0}

    def cancel():
        state["n"] += 1
        return state["n"] > 12

    result = su.install(["customvoice"], opener=opener, runner=runner, sleep=no_sleep, cancel_check=cancel,
                        disk_free=lambda p: 10**12)
    assert result.cancelled and not result.ok and "Cancelled" in result.message
    assert lock_is_free()


def test_a_disk_error_becomes_a_message(hub, sandbox, runner, monkeypatch):
    def full_disk(*args, **kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(su, "install_model", full_disk)
    result = su.install(["customvoice"], opener=opener, runner=runner, disk_free=lambda p: 10**12)
    assert not result.ok and "file or disk problem" in result.message


def test_a_load_check_failure_leaves_the_model_installed_but_reports_the_problem(hub, sandbox, runner):
    runner.probe_failure = None
    install_environment(sandbox)
    original = runner.__call__

    def probe_fails_for_models(cmd, **kwargs):
        if str(cmd[1]).endswith("qwen3_worker.py") and "model_dir" in json.loads(Path(cmd[2]).read_text("utf-8")):
            kwargs["on_line"]("@@EVENT " + json.dumps({"event": "failed", "stage": "load", "message": "model is corrupt"}))
            return 2
        return original(cmd, **kwargs)

    result = su.install(["customvoice"], opener=opener, runner=probe_fails_for_models, sleep=no_sleep,
                        disk_free=lambda p: 10**12)
    assert not result.ok and "model is corrupt" in result.message


# --------------------------------------------------------------------------- #
# Locking
# --------------------------------------------------------------------------- #
def test_two_installs_cannot_run_at_once(sandbox):
    with su.InstallLock():
        with pytest.raises(su.SetupError, match="already being installed"):
            su.InstallLock().acquire()
    again = su.InstallLock()
    again.acquire()  # released: free again
    again.release()


def test_an_install_in_another_copy_of_the_app_blocks_us_and_a_crash_never_leaves_it_stale(sandbox):
    from test_qwen3_runtime import hold_in_another_process, stop_holder

    holder = hold_in_another_process(rt.setup_lock_path())  # another copy of the app is installing
    try:
        with pytest.raises(su.SetupError, match="possibly by another copy of this app"):
            su.InstallLock().acquire()
        assert su._PROCESS_LOCK.acquire(blocking=False), "a refused attempt must give back the in-process lock"
        su._PROCESS_LOCK.release()
    finally:
        stop_holder(holder, rt.setup_lock_path())
    assert lock_is_free(), "the operating system released the dead copy's lock"


def test_an_install_cannot_start_while_a_conversion_holds_the_voices_and_a_conversion_cannot_start_during_an_install(sandbox):
    with rt.inference_lease():  # a conversion (here or in another copy) is running
        with pytest.raises(su.SetupError, match="being used by a conversion right now"):
            su.InstallLock().acquire()
        assert lock_is_free_of_setup(), "the setup lock taken on the way must have been given back"
    with su.InstallLock():  # an install is running
        with pytest.raises(rt.Qwen3Unavailable, match="being installed or repaired"):
            rt.inference_lease().__enter__()
    with rt.inference_lease():
        pass


def test_an_empty_or_garbage_lock_file_cannot_be_taken_over_by_a_second_process(sandbox):
    """Codex finding: an empty file used to look stale, so a second process could steal a lock that was just taken."""
    rt.setup_lock_path().parent.mkdir(parents=True, exist_ok=True)
    first = su.InstallLock()
    first.acquire()
    rt.setup_lock_path().write_bytes(b"")  # (the old design treated an empty file as stale)
    try:
        other = rt.FileLock(rt.setup_lock_path())
        assert other.acquire() is False, "the lock is held by the operating system, not by what the file says"
    finally:
        first.release()


# --------------------------------------------------------------------------- #
# Verify and repair
# --------------------------------------------------------------------------- #
def test_verify_reports_exactly_which_files_fail_the_full_check(sandbox):
    install_model(sandbox, "customvoice", corrupt="model.safetensors")
    install_model(sandbox, "base")
    seen = []
    result = su.verify(["both"], progress=seen.append)
    assert result == {"customvoice": ["model.safetensors does not match its expected SHA-256"], "base": []}
    assert seen and seen[-1].fraction == 1.0


def test_verify_can_be_cancelled(sandbox):
    install_model(sandbox, "customvoice")
    with pytest.raises(su.SetupCancelled):
        su.verify(["customvoice"], cancel_check=lambda: True)


def test_repairing_a_healthy_install_changes_nothing_but_does_start_the_engine_to_prove_it_works(hub, sandbox, runner):
    install_environment(sandbox)
    install_model(sandbox, "customvoice")
    before = {p: p.stat().st_mtime_ns for p in rt.model_spec("customvoice").directory.rglob("*") if p.is_file()
              and p.name != rt.MARKER_NAME}
    result = su.repair(["customvoice"], opener=opener, runner=runner, sleep=no_sleep, disk_free=lambda p: 10**12)
    assert result.ok and "Nothing needed repair" in result.message and hub.requests == []
    assert len(runner.commands) == 1 and runner.commands[0]["cmd"][1].endswith("qwen3_worker.py")  # one probe, nothing else
    assert before == {p: p.stat().st_mtime_ns for p in before}


def test_repair_refetches_a_corrupt_model_file_and_nothing_else(hub, sandbox, runner):
    install_environment(sandbox)
    su.install_model("customvoice", opener=opener, sleep=no_sleep)
    spec = rt.model_spec("customvoice")
    (spec.directory / "model.safetensors").write_bytes(b"x" * len(CUSTOM_ONLY["model.safetensors"]))
    hub.requests.clear()
    result = su.repair(["customvoice"], opener=opener, runner=runner, sleep=no_sleep, disk_free=lambda p: 10**12)
    assert result.ok and hub.paths() == [url_path(spec, "model.safetensors")]
    assert rt.model_file_problems("customvoice", full=True) == []


def test_repair_rebuilds_a_stale_environment_by_removing_only_the_apps_own_folder(hub, sandbox, runner):
    install_environment(sandbox)
    install_model(sandbox, "customvoice")
    (sandbox / "scripts" / "qwen3-requirements.txt").write_bytes(b"torch==2.0\n")  # the pins moved on
    assert rt.environment_status()[0] is False
    old_marker = rt.venv_dir() / "old-environment-marker"
    old_marker.write_text("x", encoding="utf-8")
    result = su.repair(["customvoice"], opener=opener, runner=runner, sleep=no_sleep, disk_free=lambda p: 10**12)
    assert result.ok and "environment" in result.steps
    assert not old_marker.exists()  # the old folder really was replaced
    assert rt.environment_status() == (True, "ok")


def test_repair_refuses_to_delete_a_folder_that_is_not_the_apps_environment(hub, sandbox, runner):
    rt.venv_dir().mkdir(parents=True)
    rt.venv_python().parent.mkdir(parents=True)
    rt.venv_python().write_bytes(b"")  # looks half-built, but has no pyvenv.cfg: not provably ours
    (rt.venv_dir() / "important.txt").write_text("not ours", encoding="utf-8")
    result = su.repair(["customvoice"], opener=opener, runner=runner, sleep=no_sleep, disk_free=lambda p: 10**12)
    assert not result.ok and "Refusing to delete" in result.message
    assert (rt.venv_dir() / "important.txt").read_text() == "not ours"


def test_repair_checks_disk_space_before_rebuilding(hub, sandbox, runner):
    result = su.repair(["customvoice"], opener=opener, runner=runner, disk_free=lambda p: 10**9)
    assert not result.ok and "Not enough free disk space" in result.message and runner.commands == []


# --------------------------------------------------------------------------- #
# The real command runner
# --------------------------------------------------------------------------- #
def test_the_command_runner_streams_lines_and_returns_the_exit_code(tmp_path):
    lines = []
    code = su.run_command.__wrapped__(  # the conftest guard replaces the module attribute; use the real function
        [sys.executable, "-c", "print('one'); print('two'); import sys; sys.exit(3)"], env=dict(os.environ),
        cwd=tmp_path, on_line=lines.append) if hasattr(su.run_command, "__wrapped__") else _real_run(
        [sys.executable, "-c", "print('one'); print('two'); import sys; sys.exit(3)"], tmp_path, lines.append)
    assert lines == ["one", "two"] and code == 3


def test_the_command_runner_stops_a_command_when_the_user_cancels(tmp_path):
    started = {"t": None}
    import time

    def cancel():
        if started["t"] is None:
            started["t"] = time.monotonic()
        return time.monotonic() - started["t"] > 0.5

    began = time.monotonic()
    with pytest.raises(su.SetupCancelled):
        _real_run([sys.executable, "-c", "import time; time.sleep(60)"], tmp_path, lambda line: None, cancel)
    assert time.monotonic() - began < 20


def _real_run(cmd, cwd, on_line, cancel_check=None):
    """The real ``run_command`` (conftest swaps the module attribute for a guard, so it is rebuilt from its source)."""
    import types

    source = Path(su.__file__).read_text(encoding="utf-8")
    start = source.index("def run_command(")
    end = source.index("def installer_environment(")
    namespace = dict(vars(su))
    exec(compile(source[start:end], su.__file__, "exec"), namespace)  # noqa: S102 - the module's own source
    return namespace["run_command"](cmd, env=dict(os.environ), cwd=cwd, on_line=on_line, cancel_check=cancel_check)


def test_the_installer_environment_keeps_every_cache_inside_the_repository(sandbox):
    env = su.installer_environment()
    for name in ("HF_HOME", "TORCH_HOME", "XDG_CACHE_HOME"):
        assert Path(env[name]).is_relative_to(sandbox), name
    assert env["PIP_NO_INPUT"] == "1"


def test_ambient_pip_settings_can_never_steer_the_install(sandbox, monkeypatch):
    """Codex finding: PIP_TARGET or a pip config file could send the packages outside .venv-qwen3."""
    for name, value in (("PIP_TARGET", r"C:\elsewhere"), ("PIP_INDEX_URL", "https://evil.example/simple"),
                        ("PIP_USER", "1"), ("PIP_PREFIX", "x"), ("pip_find_links", "y")):
        monkeypatch.setenv(name, value)
    env = su.installer_environment()
    assert [k for k in env if k.upper().startswith("PIP_")] == sorted(
        k for k in ("PIP_CONFIG_FILE", "PIP_DISABLE_PIP_VERSION_CHECK", "PIP_NO_INPUT") if k in env)
    assert env["PIP_CONFIG_FILE"] == os.devnull


def test_the_guard_stops_any_test_from_running_the_real_installer_commands():
    with pytest.raises(AssertionError, match="real Qwen3 install command"):
        su.run_command(["pip", "install", "torch"], env={}, cwd=Path("."), on_line=print)


def test_installer_commands_are_started_with_mandatory_containment(tmp_path, monkeypatch):
    seen = []
    real = su.qwen3_process.spawn
    monkeypatch.setattr(su.qwen3_process, "spawn", lambda cmd, **kwargs: seen.append(kwargs.get("require_job")) or real(cmd, **kwargs))
    _real_run([sys.executable, "-c", "print(1)"], tmp_path, lambda line: None)
    assert seen == [True]


def test_an_installer_command_that_cannot_be_contained_is_refused_with_a_message(tmp_path, monkeypatch):
    def refuse(cmd, **kwargs):
        raise su.qwen3_process.ContainmentUnavailable("the process could not be placed under the app's control")

    monkeypatch.setattr(su.qwen3_process, "spawn", refuse)
    with pytest.raises(su.SetupError, match="would not let this app keep control of the install"):
        _real_run([sys.executable, "-c", "print(1)"], tmp_path, lambda line: None)


# --------------------------------------------------------------------------- #
# Progress, containment of scratch space, and the cleanup tool's wording
# --------------------------------------------------------------------------- #
def test_pip_raw_progress_becomes_throttled_byte_counted_events_over_the_whole_install():
    events = []
    progress = su.PipProgress(events.append, total_bytes=100 * 2**20)
    assert progress.feed("Downloading https://x/whl/torch-2.10.0%2Bcu128-cp312-win_amd64.whl (60.0 MB)") is False
    consumed = [progress.feed(f"Progress {n} of 62914560") for n in range(0, 62914561, 1048576)] +         [progress.feed("Progress 62914560 of 62914560")]
    assert all(consumed)
    assert 5 <= len(events) <= 12, len(events)  # throttled to one event per 8 MiB, not one per block
    assert events[0].message.startswith("Downloading torch-2.10.0") and events[-1].done_bytes == 62914560
    progress.feed("Downloading numpy-2.5.4-cp312-win_amd64.whl (30.0 MB)")  # the next wheel starts
    progress.feed("Progress 15728640 of 31457280")
    assert events[-1].done_bytes == 62914560 + 15728640  # cumulative across wheels
    assert events[-1].total_bytes == 100 * 2**20 and 0 < events[-1].fraction < 1
    assert progress.feed("Collecting something") is False  # anything else is left to the caller
    assert progress.feed("Progress not-a-number of 10") is False


def test_the_environment_install_shows_pip_progress_as_progress_not_as_log_text(sandbox, runner):
    seen = []

    def noisy_runner(cmd, *, env, cwd, on_line, cancel_check=None):
        if "pip" in " ".join(str(c) for c in cmd):
            on_line("Downloading https://x/torch-2.10.0.whl (40.0 MB)")
            for n in (0, 20 * 2**20, 40 * 2**20):
                on_line(f"Progress {n} of {40 * 2**20}")
        return runner(cmd, env=env, cwd=cwd, on_line=on_line, cancel_check=cancel_check)

    su.install_environment(progress=seen.append, runner=noisy_runner)
    measured = [e for e in seen if e.total_bytes]
    assert measured and measured[-1].done_bytes == 40 * 2**20
    assert all("Progress " not in e.message for e in seen)  # the raw counter lines are not echoed as messages
    pip = next(c["cmd"] for c in runner.commands if "pip" in " ".join(c["cmd"]))
    assert pip[pip.index("--progress-bar") + 1] == "raw"


def test_scratch_space_for_the_worker_and_the_installer_is_inside_the_repository(sandbox):
    for env in (rt.worker_environment(), su.installer_environment()):
        for name in ("TEMP", "TMP", "TMPDIR"):
            assert Path(env[name]) == rt.tmp_root() and Path(env[name]).is_relative_to(sandbox)
    assert rt.tmp_root().is_dir()  # created, so the child can use it
    (rt.tmp_root() / "partial-wheel").write_bytes(b"x")
    su.clear_scratch()
    assert not rt.tmp_root().exists()


def test_a_successful_environment_install_clears_the_scratch_folder(sandbox, runner):
    rt.tmp_root().mkdir(parents=True)
    (rt.tmp_root() / "leftover").write_bytes(b"x")
    su.install_environment(runner=runner)
    assert not rt.tmp_root().exists()


def test_the_data_cleanup_tool_tells_the_user_the_qwen3_models_do_not_come_back_by_themselves():
    from shared import maintenance

    models = maintenance.asset("downloaded_models")
    assert models.relative_target == "files/runtime-data/models"  # still covers the Qwen3 model folders
    for text in (models.consequence, models.effect_line):
        assert "Qwen3" in text and "Install / repair Qwen3 voices" in text and "Kokoro" in text
    assert len(maintenance.CATALOG) == 4  # a fifth asset was not added


def lock_is_free() -> bool:
    lock = su.InstallLock()
    try:
        lock.acquire()
    except su.SetupError:
        return False
    lock.release()
    return True


def lock_is_free_of_setup() -> bool:
    probe = rt.FileLock(rt.setup_lock_path())
    free = probe.acquire()
    probe.release()
    return free


# --------------------------------------------------------------------------- #
# Codex S3: containment, bounds, analysis-before-repair
# --------------------------------------------------------------------------- #
def test_a_hostile_manifest_name_stops_an_install_before_any_file_is_touched(hub, sandbox, monkeypatch, tmp_path):
    victim = tmp_path / "victim.txt"
    victim.write_text("precious", encoding="utf-8")
    manifest = json.loads(json.dumps(rt.load_manifest()))
    manifest["models"]["customvoice"]["files"][f"../../../{victim.name}"] = {"size": 8, "sha256": "0" * 64}
    monkeypatch.setattr(rt, "load_manifest", lambda: manifest)
    result = su.install(["customvoice"], opener=opener, sleep=no_sleep, runner=FakeRunner(sandbox / "b"),
                        disk_free=lambda p: 10**12)
    assert not result.ok and "model list is invalid" in result.message
    assert victim.read_text() == "precious" and hub.requests == []


def make_junction(link, target):
    from test_qwen3_runtime import make_junction as real

    real(link, target)


@pytest.mark.skipif(sys.platform != "win32", reason="junctions are a Windows mechanism")
def test_an_install_refuses_to_write_through_a_junction_inside_a_model_folder(hub, sandbox, tmp_path):
    spec = rt.model_spec("customvoice")
    outside = tmp_path / "outside"
    outside.mkdir()
    spec.directory.mkdir(parents=True)
    make_junction(spec.directory / "speech_tokenizer", outside)
    result = su.install(["customvoice"], opener=opener, sleep=no_sleep, runner=FakeRunner(sandbox / "b"),
                        disk_free=lambda p: 10**12)
    assert not result.ok and "contains a link" in result.message
    assert list(outside.iterdir()) == []


@pytest.mark.skipif(sys.platform != "win32", reason="junctions are a Windows mechanism")
def test_an_environment_junction_stops_pip_before_it_runs_and_is_never_deleted_through(sandbox, runner, tmp_path):
    other = tmp_path / "somebody-elses-venv"
    (other / "Scripts").mkdir(parents=True)
    (other / "Scripts" / "python.exe").write_bytes(b"")
    (other / "pyvenv.cfg").write_text("home = x", encoding="utf-8")
    (other / "precious.txt").write_text("keep", encoding="utf-8")
    make_junction(rt.venv_dir(), other)
    with pytest.raises(su.SetupError, match="is a link to another folder"):
        su.install_environment(runner=runner)
    with pytest.raises(su.SetupError, match="is a link to another folder"):
        su.install_environment(runner=runner, rebuild=True)
    assert runner.commands == [] and (other / "precious.txt").read_text() == "keep"
    assert su.safe_to_remove_environment(rt.venv_dir()) is False


class FakeResponse:
    """A response whose bytes and headers the test controls; only ``read1`` exists, like a streaming socket."""

    def __init__(self, status=200, headers=None, chunks=()):
        self.status, self.headers, self.chunks, self.reads = status, headers or {}, list(chunks), 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def getcode(self):
        return self.status

    def read1(self, n=-1):
        self.reads += 1
        return self.chunks.pop(0)[:n] if self.chunks else b""


def fake_opener(response):
    return lambda request: response


def test_a_body_longer_than_the_manifest_size_is_cut_off_and_rejected(tmp_path):
    big = FakeResponse(chunks=[b"x" * 10] * 50)  # no Content-Length, endless supply
    target = tmp_path / "f.bin"
    with pytest.raises(su.SetupError, match="more data than the 25 bytes expected"):
        su.download_file("http://x/f.bin", target, 25, "0" * 64, opener=fake_opener(big), sleep=no_sleep, attempts=1)
    part = tmp_path / "f.bin.part"
    assert part.stat().st_size <= 25 and big.reads < 10  # it stopped reading; it did not write the 500 offered bytes


@pytest.mark.parametrize("response, message", [
    (FakeResponse(200, {"Content-Length": "999"}, [b"x"]), "the server's file is 999 bytes but 25 were expected"),
    (FakeResponse(200, {"Content-Encoding": "gzip"}, [b"x"]), "gzip-encoded data"),
    (FakeResponse(206, {"Content-Range": "bytes 0-9/25"}, [b"x"]), "different part of the file"),
    (FakeResponse(206, {}, [b"x"]), "different part of the file"),
    (FakeResponse(204, {}, []), "unexpected HTTP status 204"),
])
def test_a_response_that_cannot_be_the_expected_file_is_refused_before_any_byte_is_written(tmp_path, response, message):
    target = tmp_path / "f.bin"
    (tmp_path / "f.bin.part").write_bytes(b"0123456789")  # forces a Range request, so a 206 is the right answer
    with pytest.raises(su.SetupError, match=message):
        su.download_file("http://x/f.bin", target, 25, "0" * 64, opener=fake_opener(response), sleep=no_sleep, attempts=1)
    assert (tmp_path / "f.bin.part").read_bytes() == b"0123456789" and not target.exists()


def test_reads_return_what_has_arrived_so_a_cancel_is_not_stuck_behind_a_stalled_block(tmp_path):
    response = FakeResponse(chunks=[b"abc", b"def", b"ghi"])
    seen = []
    with pytest.raises(su.SetupCancelled):
        su.download_file("http://x/f.bin", tmp_path / "f.bin", 9, "0" * 64, opener=fake_opener(response),
                         progress=seen.append, cancel_check=lambda: len(seen) >= 2, sleep=no_sleep)
    assert response.reads >= 2 and (tmp_path / "f.bin.part").is_file()


def test_the_default_read_timeout_is_short_enough_to_bound_a_cancel():
    assert su.READ_TIMEOUT_S <= 30


def corrupt_one_file(sandbox):
    spec = rt.model_spec("customvoice")
    (spec.directory / "model.safetensors").write_bytes(b"x" * len(CUSTOM_ONLY["model.safetensors"]))
    return spec


def test_the_analysis_is_read_only_probes_the_engine_and_lists_exactly_what_is_wrong(hub, sandbox, runner):
    install_environment(sandbox)
    su.install_model("customvoice", opener=opener, sleep=no_sleep)
    spec = corrupt_one_file(sandbox)
    hub.requests.clear()
    before = {p: p.read_bytes() for p in spec.directory.rglob("*") if p.is_file()}
    plan = su.analyze_repair(["customvoice"], runner=runner)
    assert plan.bad_files == {"customvoice": [("model.safetensors", rt.BAD_HASH)]} and not plan.rebuild_environment
    assert plan.model_download_bytes == len(CUSTOM_ONLY["model.safetensors"]) and plan.download_bytes == plan.model_download_bytes
    assert set(plan.verified["customvoice"]) == set(spec.files) - {"model.safetensors"}
    assert len(runner.commands) == 1 and hub.requests == []
    assert before == {p: p.read_bytes() for p in spec.directory.rglob("*") if p.is_file()}  # nothing was changed
    text = "\\n".join(su.describe_repair(plan))
    assert "CustomVoice model: 1 of 3 files are missing or damaged (model.safetensors)" in text and "Total to download:" in text


def test_a_clean_analysis_says_so_and_a_repair_of_it_does_nothing(hub, sandbox, runner):
    install_environment(sandbox)
    install_model(sandbox, "customvoice")
    plan = su.analyze_repair(["customvoice"], runner=runner)
    assert plan.nothing_to_do and su.describe_repair(plan) == ["Everything checks out. Nothing needs repair."]


def test_repair_acts_on_the_confirmed_plan_and_hashes_only_the_file_that_was_bad(hub, sandbox, runner, monkeypatch):
    install_environment(sandbox)
    su.install_model("customvoice", opener=opener, sleep=no_sleep)
    spec = corrupt_one_file(sandbox)
    plan = su.analyze_repair(["customvoice"], runner=runner)
    hub.requests.clear()
    hashed = []
    real = rt.sha256_file
    monkeypatch.setattr(rt, "sha256_file", lambda path, progress=None: hashed.append(Path(path).name) or real(path, progress))
    result = su.repair(["customvoice"], plan=plan, opener=opener, runner=runner, sleep=no_sleep, disk_free=lambda p: 10**12)
    assert result.ok and hub.paths() == [url_path(spec, "model.safetensors")]
    # only the bad file is hashed (found wrong in place, then the replacement as it arrives): none of the files the
    # analysis had already proved good is hashed a second time
    assert sorted(hashed) == ["model.safetensors", "model.safetensors.part"]
    assert result.steps == ["model:customvoice", "verified:customvoice"]
    assert rt.model_file_problems("customvoice", full=True) == []


def test_a_good_file_changed_after_the_analysis_is_not_trusted(hub, sandbox, runner):
    install_environment(sandbox)
    su.install_model("customvoice", opener=opener, sleep=no_sleep)
    corrupt_one_file(sandbox)
    plan = su.analyze_repair(["customvoice"], runner=runner)
    spec = rt.model_spec("customvoice")
    (spec.directory / "config.json").write_bytes(b"{}" + b"x" * (len(TINY_FILES["config.json"]) - 2))  # changed since
    result = su.repair(["customvoice"], plan=plan, opener=opener, runner=runner, sleep=no_sleep, disk_free=lambda p: 10**12)
    assert result.ok and rt.model_file_problems("customvoice", full=True) == []


def test_an_engine_that_will_not_start_is_rebuilt_even_though_every_record_looks_intact(hub, sandbox, runner):
    """Codex finding: an antivirus can remove one DLL and leave python.exe, pyvenv.cfg and state.json valid."""
    install_environment(sandbox)
    install_model(sandbox, "customvoice")
    assert rt.environment_status() == (True, "ok")
    runner.probe_failure = "ImportError: DLL load failed while importing _C"
    plan = su.analyze_repair(["customvoice"], runner=runner)
    assert plan.rebuild_environment and "DLL load failed" in plan.environment_reason
    assert "Qwen3 voice engine: needs to be rebuilt" in "\\n".join(su.describe_repair(plan))
    runner.probe_failure = None
    (rt.venv_dir() / "stale-marker").write_text("old", encoding="utf-8")
    result = su.repair(["customvoice"], plan=plan, opener=opener, runner=runner, sleep=no_sleep, disk_free=lambda p: 10**12)
    assert result.ok and "environment" in result.steps
    assert not (rt.venv_dir() / "stale-marker").exists() and rt.environment_status() == (True, "ok")


def test_an_engine_with_no_models_yet_can_be_repaired(hub, sandbox, runner):
    install_environment(sandbox)
    runner.probe_failure = "ImportError: boom"
    plan = su.analyze_repair([], runner=runner)
    assert plan.rebuild_environment and plan.bad_files == {} and plan.components == ()


def test_models_without_an_engine_need_the_engine_installed_in_the_plan(hub, sandbox, runner):
    install_model(sandbox, "customvoice")
    plan = su.analyze_repair(["customvoice"], runner=runner)
    assert plan.rebuild_environment and rt.environment_download_bytes() == plan.download_bytes
    assert runner.commands == []  # no environment to probe: its status already says so


def test_cancelling_an_analysis_changes_nothing_and_a_repair_reports_it(hub, sandbox, runner):
    install_environment(sandbox)
    install_model(sandbox, "customvoice")
    with pytest.raises(su.SetupCancelled):
        su.analyze_repair(["customvoice"], runner=runner, cancel_check=lambda: True)
    result = su.repair(["customvoice"], runner=runner, cancel_check=lambda: True, disk_free=lambda p: 10**12)
    assert result.cancelled


def test_repair_refuses_without_disk_space_for_what_the_plan_needs(hub, sandbox, runner):
    install_environment(sandbox)
    su.install_model("customvoice", opener=opener, sleep=no_sleep)
    corrupt_one_file(sandbox)
    plan = su.analyze_repair(["customvoice"], runner=runner)
    hub.requests.clear()
    result = su.repair(["customvoice"], plan=plan, opener=opener, runner=runner, disk_free=lambda p: 10)
    assert not result.ok and "Not enough free disk space to repair" in result.message and hub.requests == []


def test_repair_cannot_run_while_a_conversion_is_using_the_voices(hub, sandbox, runner):
    install_environment(sandbox)
    su.install_model("customvoice", opener=opener, sleep=no_sleep)
    corrupt_one_file(sandbox)
    plan = su.analyze_repair(["customvoice"], runner=runner)
    hub.requests.clear()
    with rt.inference_lease():
        result = su.repair(["customvoice"], plan=plan, opener=opener, runner=runner, sleep=no_sleep,
                           disk_free=lambda p: 10**12)
    assert not result.ok and "being used by a conversion right now" in result.message and hub.requests == []


def test_pip_progress_understands_the_indented_download_line_and_ignores_metadata_fetches():
    """pip indents its download line under --require-hashes; a real run showed a nameless message before this."""
    events = []
    progress = su.PipProgress(events.append, total_bytes=200 * 2**20)
    assert progress.feed("  Downloading torch-2.10.0%2Bcu128-cp312-cp312-win_amd64.whl.metadata (29 kB)") is False
    assert progress.feed("  Downloading https://x/whl/cu128/torch-2.10.0%2Bcu128-cp312-cp312-win_amd64.whl (50.0 MB)") is False
    assert progress.feed("Progress 52428800 of 52428800") is True
    assert events[-1].message == "Downloading torch-2.10.0: 52 MB of 52 MB"  # the wheel's name is there
    assert events[-1].done_bytes == 52428800  # and the earlier metadata fetch was not counted as a finished wheel
    progress.feed("  Downloading numpy-2.5.4-cp312-win_amd64.whl (10.0 MB)")
    progress.feed("Progress 5242880 of 10485760")
    assert events[-1].done_bytes == 52428800 + 5242880 and "numpy-2.5.4" in events[-1].message


# --------------------------------------------------------------------------- #
# Codex S4 review: scratch files, markers, analysis locks, cancellable back-off
# --------------------------------------------------------------------------- #
def link_or_skip(make):
    try:
        make()
    except (OSError, NotImplementedError):
        pytest.skip("this account may not create that kind of link")


def test_a_part_file_that_shares_its_bytes_with_another_file_is_never_appended_to(hub, tmp_path):
    outside = tmp_path / "outside.bin"
    outside.write_bytes(DATA[:10])
    part = tmp_path / "f.bin.part"
    os.link(outside, part)  # a second name for a file elsewhere: appending here would grow that file too
    assert rt.scratch_is_unsafe(part)
    url = serve(hub)
    su.download_file(url, tmp_path / "f.bin", len(DATA), DIGEST, opener=opener, sleep=no_sleep)
    assert (tmp_path / "f.bin").read_bytes() == DATA and outside.read_bytes() == DATA[:10]
    assert hub.requests[0]["range"] is None  # nothing was resumed from it


def test_a_part_file_that_is_a_symbolic_link_is_removed_not_followed(hub, tmp_path):
    outside = tmp_path / "outside.bin"
    outside.write_bytes(DATA[:10])
    part = tmp_path / "f.bin.part"
    link_or_skip(lambda: os.symlink(outside, part))
    url = serve(hub)
    su.download_file(url, tmp_path / "f.bin", len(DATA), DIGEST, opener=opener, sleep=no_sleep)
    assert (tmp_path / "f.bin").read_bytes() == DATA and outside.read_bytes() == DATA[:10]
    assert not part.exists() and not part.is_symlink()


def test_an_ordinary_leftover_part_file_is_still_resumed(hub, tmp_path):
    (tmp_path / "f.bin.part").write_bytes(DATA[:10])
    assert not rt.scratch_is_unsafe(tmp_path / "f.bin.part")
    url = serve(hub)
    su.download_file(url, tmp_path / "f.bin", len(DATA), DIGEST, opener=opener, sleep=no_sleep)
    assert hub.requests[0]["range"] == "bytes=10-" and (tmp_path / "f.bin").read_bytes() == DATA


def test_a_record_is_never_written_through_a_leftover_temporary_link(tmp_path):
    victim = tmp_path / "victim.txt"
    victim.write_text("precious", encoding="utf-8")
    target = tmp_path / "state.json"
    os.link(victim, tmp_path / "state.json.tmp")  # a hard link: writing through it would change the victim
    rt.atomic_write_json(target, {"a": 1})
    assert victim.read_text(encoding="utf-8") == "precious" and json.loads(target.read_text("utf-8")) == {"a": 1}
    assert not (tmp_path / "state.json.tmp").exists()
    symlink = tmp_path / "other.json.tmp"
    link_or_skip(lambda: os.symlink(victim, symlink))
    rt.atomic_write_json(tmp_path / "other.json", {"b": 2})
    assert victim.read_text(encoding="utf-8") == "precious" and not symlink.is_symlink()


def test_a_copied_twin_is_never_written_through_a_leftover_link(hub, sandbox, tmp_path):
    victim = tmp_path / "victim.bin"
    victim.write_bytes(b"precious")
    su.install_model("customvoice", opener=opener, sleep=no_sleep)
    spec = rt.model_spec("base")
    spec.directory.mkdir(parents=True, exist_ok=True)
    shared = next(n for n in spec.files if n in rt.model_spec("customvoice").files and
                  spec.files[n] == rt.model_spec("customvoice").files[n])
    planted = spec.directory / (shared + ".part")
    planted.parent.mkdir(parents=True, exist_ok=True)
    os.link(victim, planted)
    su.install_model("base", opener=opener, sleep=no_sleep)
    assert victim.read_bytes() == b"precious"


@pytest.mark.parametrize("damage", ["missing", "garbage", "another_version"])
def test_intact_files_with_a_missing_or_wrong_verified_record_are_found_and_re_marked_without_downloading(
        hub, sandbox, runner, monkeypatch, damage):
    install_environment(sandbox)
    su.install_model("customvoice", opener=opener, sleep=no_sleep)
    marker = rt.marker_path("customvoice")
    if damage == "missing":
        marker.unlink()  # what a cancel between the marker's removal and its rewrite leaves behind
    elif damage == "garbage":
        marker.write_text("{not json", encoding="utf-8")
    else:
        recorded = json.loads(marker.read_text("utf-8"))
        recorded["manifest_sha256"] = "0" * 64
        marker.write_text(json.dumps(recorded), encoding="utf-8")
    assert not rt.model_status("customvoice")[0] and rt.model_bad_files("customvoice", full=True) == []
    plan = su.analyze_repair(["customvoice"], runner=runner)
    assert plan.unmarked == ["customvoice"] and plan.bad_files == {"customvoice": []} and not plan.nothing_to_do
    assert plan.download_bytes == 0 and "not recorded as verified" in " ".join(su.describe_repair(plan))
    hub.requests.clear()
    hashed = []
    real = rt.sha256_file
    monkeypatch.setattr(rt, "sha256_file", lambda path, progress=None: hashed.append(Path(path).name) or real(path, progress))
    result = su.repair(["customvoice"], plan=plan, opener=opener, runner=runner, sleep=no_sleep, disk_free=lambda p: 10**12)
    assert result.ok and "model:customvoice" in result.steps and hub.requests == []
    assert hashed == []  # the analysis had proved every file; none is hashed again
    assert rt.model_status("customvoice") == (True, "ok")


def test_a_healthy_marker_is_not_reported_as_unmarked(hub, sandbox, runner):
    install_environment(sandbox)
    install_model(sandbox, "customvoice")
    assert su.analyze_repair(["customvoice"], runner=runner).unmarked == []


def test_the_analysis_holds_both_install_locks_while_it_probes_and_releases_them_after(hub, sandbox, runner):
    install_environment(sandbox)
    install_model(sandbox, "customvoice")
    seen = []
    real = runner.__call__

    def watching(cmd, **kwargs):
        seen.append((lock_is_free_of_setup(), rt.FileLock(rt.inference_lock_path()).acquire()))
        return real(cmd, **kwargs)

    plan = su.analyze_repair(["customvoice"], runner=watching)
    assert plan.nothing_to_do and seen == [(False, False)]  # neither lock could be taken while the probe ran
    assert lock_is_free()


def test_an_analysis_cannot_start_during_a_conversion_or_an_install_and_never_starts_the_engine(hub, sandbox, runner):
    install_environment(sandbox)
    install_model(sandbox, "customvoice")
    with rt.inference_lease():
        with pytest.raises(su.SetupError, match="being used by a conversion"):
            su.analyze_repair(["customvoice"], runner=runner)
    with su.InstallLock():
        with pytest.raises(su.SetupError, match="already being installed or repaired"):
            su.analyze_repair(["customvoice"], runner=runner)
    assert runner.commands == [] and lock_is_free()


def test_every_probe_gets_its_own_job_file_and_leaves_none_behind(sandbox, runner):
    install_environment(sandbox)
    su.probe_environment(runner=runner)
    su.probe_environment(runner=runner)
    paths = [Path(c["cmd"][2]) for c in runner.commands if str(c["cmd"][1]).endswith("qwen3_worker.py")]
    assert len(paths) == 2 and paths[0] != paths[1] and all(p.name.startswith("probe-job-") for p in paths)
    assert not any(p.exists() for p in paths) and list((rt.runtime_dir() / "probe").glob("*.json")) == []


def test_a_cancel_during_a_retry_wait_is_honoured_within_a_slice_not_after_the_whole_delay(hub, tmp_path):
    url = serve(hub)
    hub.status["/f.bin"] = 503
    waits = []

    def sleeping(seconds):
        waits.append(seconds)

    with pytest.raises(su.SetupCancelled):
        su.download_file(url, tmp_path / "f.bin", len(DATA), DIGEST, opener=opener, sleep=sleeping, attempts=3,
                         cancel_check=lambda: len(waits) >= 2)
    assert waits == [su.BACKOFF_SLICE_S, su.BACKOFF_SLICE_S] and len(hub.requests) == 1  # no third request either


def test_a_retry_wait_without_a_cancel_still_adds_up_to_the_full_delay_in_short_slices(hub, tmp_path):
    url = serve(hub)
    hub.status["/f.bin"] = 503
    waits = []
    with pytest.raises(su.SetupError, match="Your progress is kept"):
        su.download_file(url, tmp_path / "f.bin", len(DATA), DIGEST, opener=opener, sleep=waits.append, attempts=3,
                         cancel_check=lambda: False)
    assert abs(sum(waits) - (2.0 + 5.0)) < 1e-9 and max(waits) <= su.BACKOFF_SLICE_S


def test_a_link_is_judged_unsafe_whatever_it_points_at_and_is_removed_by_name(tmp_path, monkeypatch):
    plain = tmp_path / "x.part"
    plain.write_bytes(b"abc")
    assert not rt.scratch_is_unsafe(plain)
    monkeypatch.setattr(rt, "is_link", lambda p: Path(p) == plain)  # stands in for a symlink/junction (no privilege needed)
    assert rt.scratch_is_unsafe(plain)
    rt.remove_entry(plain)
    assert not plain.exists()


@pytest.mark.skipif(sys.platform != "win32", reason="junctions are a Windows mechanism")
def test_a_part_path_that_is_a_junction_is_removed_and_its_target_is_left_alone(hub, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("precious", encoding="utf-8")
    part = tmp_path / "f.bin.part"
    make_junction(part, outside)
    assert rt.scratch_is_unsafe(part)
    url = serve(hub)
    su.download_file(url, tmp_path / "f.bin", len(DATA), DIGEST, opener=opener, sleep=no_sleep)
    assert (tmp_path / "f.bin").read_bytes() == DATA and (outside / "keep.txt").read_text("utf-8") == "precious"
    assert not part.exists() and list(outside.iterdir()) == [outside / "keep.txt"]


def test_a_model_folder_that_became_a_link_after_the_analysis_loses_nothing_outside_it(hub, sandbox, tmp_path, monkeypatch):
    su.install_model("customvoice", opener=opener, sleep=no_sleep)
    outside = tmp_path / "outside"
    outside.mkdir()
    marker_elsewhere = outside / rt.MARKER_NAME
    marker_elsewhere.write_text("{}", encoding="utf-8")
    spec = rt.model_spec("customvoice")
    monkeypatch.setattr(rt, "is_link", lambda p: Path(p) == spec.directory)  # the folder is now a link
    real_unlink = Path.unlink
    deleted = []
    monkeypatch.setattr(Path, "unlink", lambda self, *a, **k: deleted.append(self.name) or real_unlink(self, *a, **k))
    with pytest.raises(rt.Qwen3Unavailable, match="contains a link"):
        su.install_model("customvoice", opener=opener, sleep=no_sleep)
    assert rt.MARKER_NAME not in deleted and marker_elsewhere.read_text("utf-8") == "{}"
    with pytest.raises(rt.Qwen3Unavailable):
        rt.write_model_marker("customvoice")


@pytest.mark.parametrize("content", ["null", "[]", '"text"', "7"])
def test_a_verified_record_of_the_wrong_json_type_is_an_invalid_record_not_a_crash(hub, sandbox, runner, content):
    install_environment(sandbox)
    su.install_model("customvoice", opener=opener, sleep=no_sleep)
    rt.marker_path("customvoice").write_text(content, encoding="utf-8")
    ok, reason = rt.model_status("customvoice")
    assert not ok and "unreadable" in reason
    plan = su.analyze_repair(["customvoice"], runner=runner)
    assert plan.unmarked == ["customvoice"]


def test_a_runtime_folder_that_is_a_link_is_refused_before_anything_is_written(sandbox, monkeypatch, tmp_path):
    probe = rt.runtime_dir() / "probe"
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    monkeypatch.setattr(rt, "is_link", lambda p: Path(p) == probe)
    with pytest.raises(rt.Qwen3Unavailable, match="is a link"):
        su.probe_environment(runner=lambda *a, **k: pytest.fail("a probe ran through a linked folder"))
    assert list(outside.iterdir()) == []


@pytest.mark.parametrize("linked, action", [
    ("runtime", "worker_environment"), ("tmp", "worker_environment"), ("cache", "worker_environment"),
    ("runtime", "new_job_dir"), ("jobs", "new_job_dir"),
    ("runtime", "write_state"), ("runtime", "take_lock"),
])
def test_every_runtime_folder_the_app_creates_is_checked_for_links(sandbox, monkeypatch, linked, action):
    from tts import qwen3_synth

    folders = {"runtime": rt.runtime_dir(), "jobs": rt.jobs_root(), "tmp": rt.tmp_root(), "cache": rt.cache_root()}
    actions = {
        "worker_environment": lambda: rt.worker_environment(),
        "new_job_dir": lambda: qwen3_synth.new_job_dir(),
        "write_state": lambda: rt.atomic_write_json(rt.state_path(), {"a": 1}),
        "take_lock": lambda: rt.FileLock(rt.setup_lock_path()).acquire(),
    }
    monkeypatch.setattr(rt, "is_link", lambda p: Path(p) == folders[linked])
    with pytest.raises(rt.Qwen3Unavailable, match="is a link"):
        actions[action]()


def test_the_stale_job_cleanup_never_walks_into_a_linked_jobs_folder(sandbox, monkeypatch, tmp_path):
    from tts import qwen3_synth

    elsewhere = tmp_path / "elsewhere"
    (elsewhere / "old-job").mkdir(parents=True)
    (elsewhere / "old-job" / "keep.txt").write_text("precious", encoding="utf-8")
    old = 1_000_000_000
    os.utime(elsewhere / "old-job", (old, old))
    jobs = rt.jobs_root()
    jobs.mkdir(parents=True)
    monkeypatch.setattr(rt, "is_link", lambda p: Path(p) == jobs)
    monkeypatch.setattr(Path, "iterdir", lambda self: pytest.fail("the cleanup listed a linked folder"))
    with pytest.raises(rt.Qwen3Unavailable, match="is a link"):
        qwen3_synth.cleanup_stale_jobs()
    monkeypatch.undo()
    assert (elsewhere / "old-job" / "keep.txt").read_text("utf-8") == "precious"


@pytest.mark.parametrize("name", ["hf", "torch", "numba", "xdg", "pip"])
def test_every_cache_destination_handed_to_a_subprocess_is_proved_local(sandbox, monkeypatch, name):
    target = rt.cache_root() / name
    monkeypatch.setattr(rt, "is_link", lambda p: Path(p) == target)
    with pytest.raises(rt.Qwen3Unavailable, match="is a link"):
        rt.worker_environment()


def test_nothing_is_created_behind_a_link_that_is_already_there(sandbox, monkeypatch):
    monkeypatch.setattr(rt, "is_link", lambda p: Path(p) == rt.runtime_dir())
    rt.runtime_dir().mkdir(parents=True, exist_ok=True)
    with pytest.raises(rt.Qwen3Unavailable, match="is a link"):
        rt.ensure_runtime_dir(rt.cache_root() / "hf")
    assert not rt.cache_root().exists()  # the check ran before any folder was created


def test_an_in_between_folder_that_is_a_link_is_caught(sandbox, monkeypatch):
    monkeypatch.setattr(rt, "is_link", lambda p: Path(p) == rt.cache_root())
    with pytest.raises(rt.Qwen3Unavailable, match="'cache' is a link"):
        rt.ensure_runtime_dir(rt.cache_root() / "hf")


def test_the_failure_record_replaces_a_planted_link_instead_of_writing_through_it(sandbox, tmp_path):
    from tts import qwen3_synth

    victim = tmp_path / "victim.txt"
    victim.write_text("precious", encoding="utf-8")
    record = rt.runtime_dir() / "last-failure.txt"
    record.parent.mkdir(parents=True, exist_ok=True)
    os.link(victim, record)  # the record is a second name for another file
    job = tmp_path / "job"
    job.mkdir()
    qwen3_synth.record_failure(job, "the voice engine failed while generating speech")
    assert victim.read_text(encoding="utf-8") == "precious"
    assert "failed while generating speech" in record.read_text(encoding="utf-8")


def test_atomic_text_publication_leaves_no_temporary_file_and_replaces_the_old_text(tmp_path):
    target = tmp_path / "a.txt"
    rt.atomic_write_text(target, "one")
    rt.atomic_write_text(target, "two")
    assert target.read_text(encoding="utf-8") == "two" and not list(tmp_path.glob("*.tmp"))
