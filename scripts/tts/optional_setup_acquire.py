"""optional_setup_acquire.py — the consented acquirer: fetches exactly the units of a checked and spent consent.

Stage 4B-3A status: this is the historical v2 adapter, retained only for explicit
injected compatibility tests behind the disabled production worker. Its legacy
Qwen repair and post-lock local acquisition are NOT v3 scope/budget authority.
The independently planned, all-group locked v3 seam is optional_setup_authority;
no production worker or legacy manual installer is switched to it here.

v0.7.0 P05B Stage 2 (plan Revision 2 §5.4). ``tts.optional_setup_lifecycle.Operation`` calls :class:`RealAcquirer` only
after the fresh plan was made, the consent was proved to cover it (``consent_covers``) and the consent was spent. The
acquirer still trusts nothing it is handed:

* every unit to acquire must be in the consent, and its plan source must equal the pinned source this build knows for
  it (a Hugging Face repository at one commit, the approved spaCy wheel, the Qwen3 manifest, the Qwen3 hash lock);
* the network is reached only through an opener that refuses any URL outside the confirmed files -- never a moving
  ``main``; every Hugging Face URL names the pinned commit;
* free space for the plan's new disk and temporary figures is checked first;
* Kokoro, Chatterbox and spaCy work runs under the Qwen3 ``InstallLock`` (``setup.lock`` then ``inference.lock``, and a
  running engine refused): the order every install, Qwen3 repair and repair of the app's own environment uses. The
  Qwen3 part goes through ``qwen3_setup.install`` / ``repair`` -- the existing installer, its own lock, disk check,
  manifest, hash lock and load proof -- never a second installer;
* each destination is proved, at the moment of writing, to lie inside its own folder with no link on the way;
* every downloaded file must be the approved bytes (size and SHA-256: ``qwen3_setup.download_file``, which resumes a
  ``.part`` and hashes the whole file before it is accepted); afterwards each unit is hashed again from disk, by
  ``tts.model_assets``, independently of the downloader, and that proof is recorded;
* the spaCy English model is the approved wheel, size- and hash-checked before pip ever sees it, installed from that
  local file with ``--no-index --no-deps --require-hashes`` into the app's own environment, only when its spaCy is
  ``>=3.8.0,<3.9.0`` (never changed to fit), and its installed version read back afterwards.

Already-verified files are kept, never fetched again. A failure in one component does not stop the others; a cancel
stops everything (each child process is ended with its whole tree). A local engine whose packages were proved not to
load (plan ``engine: broken``) gets nothing downloaded: model files cannot repair packages -- the app's own repair at
launch does. The report names exactly what was completed; the
lifecycle then decides, by a fresh plan and health proof, what actually works.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Callable, Iterable, Optional

from shared import optional_setup_protocol as proto
from shared import venv_layout
from tts import model_assets as assets
from tts import optional_setup
from tts import qwen3_runtime as rt
from tts import qwen3_setup
from tts.optional_setup_lifecycle import AcquisitionReport

#: Free space kept in reserve beyond a Kokoro/Chatterbox/spaCy acquisition's own figures (the Qwen3 installer keeps
#: its own, larger margin, already in the plan's temporary figure).
LOCAL_DISK_MARGIN_BYTES = 256 * 10**6
#: A download reports progress at most every 8 MiB (and when each file ends).
PROGRESS_STEP_BYTES = 8 * 1024 * 1024
PIP_TAIL = 6


class AcquisitionRefused(Exception):
    """Something the consent does not cover was about to happen. Deliberately not an ``OSError``/``ValueError``: the
    downloader retries those, and a refusal must stop at once."""


class AcquisitionError(Exception):
    """One component's acquisition failed; the others may still go ahead."""


# --------------------------------------------------------------------------- #
# What each unit is, and where it may come from
# --------------------------------------------------------------------------- #
def unit_files(unit_id: str) -> Optional[tuple[assets.AssetSet, tuple[str, ...]]]:
    """The pinned files of a Kokoro or Chatterbox unit, or ``None``."""
    if unit_id == "kokoro-model":
        return assets.kokoro_set(), assets.KOKORO_MODEL_NAMES
    if unit_id.startswith("kokoro-voice:"):
        name = assets.kokoro_voice_name(unit_id.split(":", 1)[1])
        return (assets.kokoro_set(), (name,)) if name in assets.KOKORO_FILES else None
    if unit_id == "chatterbox-model":
        return assets.chatterbox_set(), tuple(assets.CHATTERBOX_FILES)
    return None


def expected_source(unit_id: str) -> Optional[str]:
    """The only source this build will acquire *unit_id* from, or ``None`` (not acquirable)."""
    if unit_files(unit_id) is not None:
        files = unit_files(unit_id)[0]
        return optional_setup.hf_source(files.repo, files.revision)
    if unit_id == "spacy-english":
        return assets.spacy_source()
    if unit_id == "qwen3-engine":
        return optional_setup.qwen_engine_source()
    if unit_id.startswith("qwen3-model:"):
        key = unit_id.split(":", 1)[1]
        return optional_setup.qwen_model_source(rt.model_spec(key)) if key in rt.MODEL_KEYS else None
    return None


def hub_file_url(files: assets.AssetSet, name: str) -> str:
    return qwen3_setup.HUB_URL.format(repo=files.repo, revision=files.revision, path=name)


class ScopedOpener:
    """The only door to the network: a request for any URL outside *allowed* is refused before it is sent."""

    def __init__(self, allowed: Iterable[str], base: Optional[Callable] = None):
        self.allowed = frozenset(allowed)
        self._base = base
        self.requested: list[str] = []

    def __call__(self, request):
        url = request.full_url
        if url not in self.allowed:
            raise AcquisitionRefused(f"refused to fetch {url}: it is not one of the confirmed files")
        self.requested.append(url)
        return (self._base or qwen3_setup._default_opener)(request)


def _require_inside(root: Path, folder: Path, path: Path) -> None:
    """The write boundary: *path* lies lexically inside *folder*, and nothing from the repository root down to it is a
    link or junction. Checked immediately before (and after) each write, not once at the start."""
    if not venv_layout.is_within(folder, path):
        raise AcquisitionRefused(f"refused to write {path}: it is outside {folder}")
    unsafe = venv_layout.unsafe_component(root, path)
    if unsafe is not None:
        raise AcquisitionRefused(f"refused to write {path}: {unsafe} is a link or lies outside the app's folder")


def _pip_environment() -> dict:
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith(("PIP_", "PYTHON"))}
    env.update({"PIP_CONFIG_FILE": os.devnull, "PIP_DISABLE_PIP_VERSION_CHECK": "1", "PIP_NO_INPUT": "1"})
    return env


def _known(figure: dict) -> int:
    return figure["bytes"] or 0


class _Meter:
    """Byte progress for one unit, reported at most every :data:`PROGRESS_STEP_BYTES`."""

    def __init__(self, emit: Callable[[dict], None], unit: str, total: int):
        self.emit, self.unit, self.total, self.done, self.shown = emit, unit, total, 0, -PROGRESS_STEP_BYTES

    def add(self, count: int, message: str = "") -> None:
        self.done += count
        if self.done - self.shown >= PROGRESS_STEP_BYTES or self.done >= self.total:
            self.shown = self.done
            self.emit({"unit": self.unit, "step": "download", "done": self.done, "total": self.total,
                       "message": message})


# --------------------------------------------------------------------------- #
# The acquirer
# --------------------------------------------------------------------------- #
class RealAcquirer:
    """Fetches the units of a consented plan. Every seam is a parameter, so tests reach no network and no real pip."""

    available = True

    def __init__(self, *, opener: Optional[Callable] = None, runner: Optional[Callable] = None,
                 disk_free: Callable[[Path], int] = qwen3_setup.free_bytes, sleep: Callable[[float], None] = time.sleep,
                 version_of: Callable[[str], Optional[str]] = assets.installed_version,
                 qwen_install: Optional[Callable] = None, qwen_repair: Optional[Callable] = None,
                 python: Optional[Path] = None):
        self.opener, self.runner, self.disk_free, self.sleep = opener, runner, disk_free, sleep
        self.version_of, self.python = version_of, python
        self.qwen_install = qwen_install or qwen3_setup.install
        self.qwen_repair = qwen_repair or qwen3_setup.repair
        self.openers: list[ScopedOpener] = []  # every network door opened, with what it fetched (for the record)

    def _opener(self, allowed: Iterable[str]) -> ScopedOpener:
        opener = ScopedOpener(allowed, self.opener)
        self.openers.append(opener)
        return opener

    def _run(self, cmd, **kwargs) -> int:
        return (self.runner or qwen3_setup.run_command)(cmd, **kwargs)  # looked up at call time

    # -- the whole plan -------------------------------------------------------------------------------------------
    def acquire(self, plan: dict, consent: proto.Consent, *, progress: Callable[[dict], None],
                cancel_check: Callable[[], bool]) -> AcquisitionReport:
        root = rt.repo_root()
        wanted = list(plan["acquire_units"])
        units = {u["id"]: u for u in plan["units"]}
        if not set(wanted) <= set(consent.units):
            raise AcquisitionRefused("the plan would acquire something the confirmation does not cover")
        for unit_id in wanted:
            source = expected_source(unit_id)
            if source is None or units[unit_id]["source"] != source:
                raise AcquisitionRefused(f"{units[unit_id]['label']} would come from a source this build does not "
                                         "approve for it")

        qwen = [u for u in wanted if u.startswith("qwen3-")]
        needed = _known(plan["totals"]["disk"]) + _known(plan["totals"]["temp"]) + (
            0 if qwen else LOCAL_DISK_MARGIN_BYTES)
        free = self.disk_free(root)
        if free < needed:
            return AcquisitionReport(False, (), f"there is not enough free disk space (about {rt.format_bytes(needed)} "
                                                f"is needed and {rt.format_bytes(free)} is free); nothing was downloaded")

        done: list[str] = []
        failures: list[str] = []
        groups = []
        for name, members in ((proto.KOKORO, [u for u in wanted if u.startswith("kokoro-") or u == "spacy-english"]),
                              (proto.CHATTERBOX, [u for u in wanted if u == "chatterbox-model"])):
            entry = next((c for c in plan["components"] if c["id"] == name), {})
            if members and entry.get("engine") == "broken":
                failures.append(f"{proto.LABELS[name]}: its packages were proved not to load in the app's environment, "
                                "so nothing was downloaded for it (the app's own repair at launch fixes packages)")
                continue
            groups.append(members)
        try:
            if any(groups):
                self._acquire_local(root, groups, units, done, failures, progress, cancel_check)
            if qwen:
                self._acquire_qwen(plan, qwen, units, done, failures, progress, cancel_check)
        except qwen3_setup.SetupCancelled:
            return AcquisitionReport(False, tuple(done), "cancelled")
        complete = not failures and set(done) == set(wanted)
        return AcquisitionReport(complete, tuple(done), "; ".join(failures))

    # -- Kokoro, Chatterbox, spaCy --------------------------------------------------------------------------------
    def _acquire_local(self, root, groups, units, done, failures, progress, cancel_check) -> None:
        try:
            lock = qwen3_setup.InstallLock()
            lock.acquire()
        except (qwen3_setup.SetupError, rt.Qwen3Unavailable, OSError) as exc:
            failures.append(str(exc))
            return
        try:
            for group in groups:
                for unit_id in group:
                    qwen3_setup._check_cancel(cancel_check)
                    try:
                        if unit_id == "spacy-english":
                            self._acquire_spacy(root, progress, cancel_check)
                        else:
                            self._acquire_files(root, unit_id, progress, cancel_check)
                    except qwen3_setup.SetupCancelled:
                        raise
                    except (AcquisitionError, AcquisitionRefused, qwen3_setup.SetupError, OSError) as exc:
                        failures.append(f"{units[unit_id]['label']}: {exc}")
                        break  # this component stops here; the next one still goes ahead
                    done.append(unit_id)
        finally:
            lock.release()

    def _acquire_files(self, root: Path, unit_id: str, progress, cancel_check) -> None:
        files, names = unit_files(unit_id)
        hub = assets.hf_hub_root()
        folder = assets.snapshot_dir(files)
        states = assets.assess(files, names)
        fetch = [name for name in names if states[name][0] != assets.READY]
        for name in fetch:
            if states[name][0] == assets.UNVERIFIED:  # reached through a link, or unreadable: never written through
                raise AcquisitionError(states[name][1])
        meter = _Meter(progress, unit_id, files.size(fetch))
        opener = self._opener(hub_file_url(files, name) for name in fetch)
        for name in fetch:
            size, sha256 = files.files[name]
            target = folder.joinpath(*name.split("/"))
            _require_inside(root, hub, target)
            qwen3_setup.download_file(hub_file_url(files, name), target, size, sha256, opener=opener,
                                      progress=lambda count, name=name: meter.add(count, f"Downloading {name}"),
                                      cancel_check=cancel_check, sleep=self.sleep)
            _require_inside(root, hub, target)
        progress({"unit": unit_id, "step": "verify", "done": 0, "total": 0, "message": "Checking the files"})
        _require_inside(root, assets.record_dir(), assets.record_path(files))
        assets.record_verified(files, names)  # every file of the unit hashed again from disk, kept files included
        wrong = [detail for state, detail in assets.assess(files, names).values() if state != assets.READY]
        if wrong:
            raise AcquisitionError(f"not the approved files after downloading ({wrong[0]})")

    def _acquire_spacy(self, root: Path, progress, cancel_check) -> None:
        problem = assets.spacy_problem(self.version_of)
        if problem:
            raise AcquisitionError(problem)
        installed = self.version_of(assets.SPACY_ENGLISH)
        if installed == assets.SPACY_ENGLISH_VERSION:
            return  # already there (installed meanwhile): nothing to do
        if installed is not None:
            raise AcquisitionError(f"spaCy English model {installed} is installed; it is not replaced automatically")
        python = Path(self.python) if self.python is not None else proto.main_console_python(root)
        if venv_layout.unsafe_component(root, python) is not None or not python.is_file():
            raise AcquisitionError("the app's own Python environment could not be found where it belongs")
        exchange = proto.exchange_root(root)
        staging = exchange / "downloads"
        wheel = staging / assets.SPACY_WHEEL_NAME
        _require_inside(root, exchange, wheel)
        meter = _Meter(progress, "spacy-english", assets.SPACY_WHEEL_SIZE)
        qwen3_setup.download_file(assets.SPACY_WHEEL_URL, wheel, assets.SPACY_WHEEL_SIZE, assets.SPACY_WHEEL_SHA256,
                                  opener=self._opener([assets.SPACY_WHEEL_URL]),
                                  progress=lambda count: meter.add(count, "Downloading the spaCy English model"),
                                  cancel_check=cancel_check, sleep=self.sleep)
        _require_inside(root, exchange, wheel)
        requirement = staging / "spacy-english-requirement.txt"
        _require_inside(root, exchange, requirement)
        rt.remove_entry(requirement)
        # pip reads only this verified local file: no index, no dependencies, its hash enforced a second time.
        requirement.write_text(f"{assets.SPACY_ENGLISH} @ {wheel.resolve().as_uri()} "
                               f"--hash=sha256:{assets.SPACY_WHEEL_SHA256}\n", encoding="utf-8")
        tail: list[str] = []

        def keep(line: str) -> None:
            tail.append(line)
            del tail[:-40]

        progress({"unit": "spacy-english", "step": "install", "done": 0, "total": 0,
                  "message": "Installing the spaCy English model"})
        code = self._run([str(python), "-m", "pip", "install", "--isolated", "--require-virtualenv", "--no-deps",
                          "--no-index", "--require-hashes", "--no-input", "--disable-pip-version-check",
                          "--no-cache-dir", "--no-warn-script-location", "--progress-bar", "off",
                          "-r", str(requirement)],
                         env=_pip_environment(), cwd=staging, on_line=keep, cancel_check=cancel_check)
        if code != 0:
            raise AcquisitionError("pip could not install the approved spaCy English model ("
                                   + " ".join(line.strip() for line in tail[-PIP_TAIL:] if line.strip()) + ")")
        after = self.version_of(assets.SPACY_ENGLISH)
        if after != assets.SPACY_ENGLISH_VERSION:
            raise AcquisitionError(f"after installing, the spaCy English model reports version {after}, not "
                                   f"{assets.SPACY_ENGLISH_VERSION}")
        problem = assets.spacy_problem(self.version_of)
        if problem:
            raise AcquisitionError(problem)
        for leftover in (wheel, requirement):  # the wheel is installed; its space is given back
            try:
                rt.remove_entry(leftover)
            except OSError:
                pass

    # -- Qwen3, through its own installer -------------------------------------------------------------------------
    def _acquire_qwen(self, plan, qwen, units, done, failures, progress, cancel_check) -> None:
        scopes = {c["id"]: c["consent_scope"] for c in plan["components"] if c["selected"]}
        served = {c for unit_id in qwen for c in units[unit_id]["components"]}
        keys = {scope: [proto.QWEN3_MODEL_KEYS[c] for c in (proto.QWEN3_CUSTOMVOICE, proto.QWEN3_BASE)
                        if c in served and scopes.get(c) == scope]
                for scope in (proto.SCOPE_REPAIR, proto.SCOPE_INSTALL)}
        allowed = [qwen3_setup.hub_url(rt.model_spec(key), name) for key in rt.MODEL_KEYS
                   for name in rt.model_spec(key).files if key in keys[proto.SCOPE_REPAIR] + keys[proto.SCOPE_INSTALL]]
        opener = self._opener(allowed)
        last = {"message": None, "done": -PROGRESS_STEP_BYTES}

        def report(update: qwen3_setup.Progress) -> None:
            if update.message != last["message"] or update.done_bytes - last["done"] >= PROGRESS_STEP_BYTES:
                last.update(message=update.message, done=update.done_bytes)
                progress({"unit": "qwen3", "step": update.step, "done": update.done_bytes,
                          "total": update.total_bytes, "message": update.message[:200]})

        ok_keys: list[str] = []
        for scope, run in ((proto.SCOPE_REPAIR, self.qwen_repair), (proto.SCOPE_INSTALL, self.qwen_install)):
            if not keys[scope]:
                continue
            qwen3_setup._check_cancel(cancel_check)
            result = run(keys[scope], progress=report, cancel_check=cancel_check, opener=opener, runner=self.runner,
                         disk_free=self.disk_free, sleep=self.sleep)
            if result.cancelled:
                raise qwen3_setup.SetupCancelled()
            if not result.ok:
                failures.append(f"Qwen3 voices: {result.message}")
                continue
            ok_keys.extend(keys[scope])
        for unit_id in qwen:
            if unit_id == "qwen3-engine":
                if ok_keys:
                    done.append(unit_id)
            elif unit_id.split(":", 1)[1] in ok_keys:
                done.append(unit_id)
