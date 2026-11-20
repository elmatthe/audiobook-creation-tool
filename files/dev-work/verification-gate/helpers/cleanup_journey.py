"""What ``setup.clear-downloaded-data`` judges on macOS, as pure functions (v0.8.0 P5, macOS counterpart).

The journey (``journeys/setup.py``) drives the real application on a disposable copy; everything it decides about isolation and
about what the real cleanup helper did is decided here, from facts it gathered, so the same rules are held to negative controls in
``files/tests/test_macos_p5_clear_downloaded_data.py`` without a desktop.

  * :func:`isolation_problems` -- before anything is launched or clicked: the copy's own code says its root is the copy, every catalog
    target, the state folder and the helper script are inside it, the helper's interpreter is outside the copy and outside every
    cleanup target of the real checkout, and every link in the copy is one the journey seeded, pointing at its own sentinel.
  * :func:`outcome_problems` -- afterwards: every ticked entry is gone, every other entry that existed before is byte-identical, and
    nothing new appeared except where the application itself writes (its logs, its maintenance state, its settings).
  * :func:`tree_problems` -- a bystander installation, the links' sentinel and the real checkout's protected locations unchanged.

Nothing here deletes, starts a process other than the copy's own read-only probe, or reads outside the paths it is handed.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

#: The catalog, as the journey expects it on a Mac: (asset id, display name, folder, ticked here). Application logs is left unticked.
MAC_ASSETS = (("virtual_environment", "Private Python environment", ".venv", True),
              ("portable_binaries", "Portable binaries", "files/bin", True),
              ("downloaded_models", "Downloaded voice models", "files/runtime-data/models", True),
              ("application_logs", "Application logs", "files/runtime-data/logs", False))
SELECTED = tuple(asset for asset, _name, _folder, ticked in MAC_ASSETS if ticked)
#: Entries under these are what the three ticked items remove. ``.venv`` goes itself; the other two are kept, empty.
REMOVED_PREFIXES = (".venv/", "files/bin/", "files/runtime-data/models/")
KEPT_EMPTY = ("files/bin/", "files/runtime-data/models/")
#: Where the running application itself writes (its own logs, cleanup state, settings and FFmpeg record). A seeded file there is still
#: pinned byte for byte (``pinned``); only what the application wrote may change.
VOLATILE_PREFIXES = ("files/runtime-data/logs/", "files/runtime-data/maintenance/", "files/runtime-data/settings.json",
                     "files/runtime-data/ffmpeg-state.json")
#: The copy's engine lease (``shared.engine_lease.EnvironmentLease``: Qwen3's three locks, then OmniVoice's two). The real helper takes
#: it before it re-checks or removes ``.venv`` or the models (``cleanup_worker.hold_engine_still``, v0.7.0 P04C), so these appear in the
#: copy as new, EMPTY files. Nothing else may appear, a lock with content is not a lock, and one that existed before is compared as
#: any other entry. Pinned to the module's own names by files/tests/test_macos_p5_clear_downloaded_data.py.
LEASE_LOCKS = ("files/runtime-data/qwen3/setup.lock", "files/runtime-data/qwen3/inference.lock", "files/runtime-data/qwen3/engine.lock",
               "files/runtime-data/omnivoice/inference.lock", "files/runtime-data/omnivoice/engine.lock")
EMPTY_FILE = "sha256:" + hashlib.sha256(b"").hexdigest()
#: The links the journey seeds inside the environment folder, each pointing at the sentinel outside the copy. Removing ``.venv``
#: must remove the links as links and never touch what they point at.
LINKS = {".venv/bin/escape-file-link": "sentinel.txt", ".venv/lib/escape-dir-link": "sentinel-dir"}


# --------------------------------------------------------------------------------------------------------------------- #
#  Seeding: synthetic, disposable, small
# --------------------------------------------------------------------------------------------------------------------- #
def seed(copy: Path, outside: Path, *, links: bool = True) -> dict[str, bytes]:
    """Stand-in downloaded data in the four places the catalog names, in a Mac's layout, plus files beside them that must survive and
    two links out of the environment folder to a sentinel in ``outside``. Every byte is written here; nothing is copied from a real
    installation."""
    files = {
        ".venv/pyvenv.cfg": b"home = /nonexistent/act-synthetic\n",
        ".venv/bin/python3": b"not a real interpreter\n",
        ".venv/lib/python3.12/site-packages/sample/__init__.py": b"VALUE = 1\n",
        "files/bin/synthetic-portable/tool.bin": b"not a real portable tool",
        "files/bin/synthetic-note.txt": b"a synthetic portable-binaries note",
        "files/runtime-data/models/huggingface/hub/models--synthetic--voice/blobs/0001": b"m" * 4096,
        "files/runtime-data/logs/session_2026-01-01.log": b"an earlier session's log\n",
        # Not in the catalog: each must still be there afterwards, byte for byte.
        "files/runtime-data/nltk_data/tokenizers/sample.txt": b"sentence data stays",
        "files/runtime-data/python-packages/sample.whl": b"the package store stays",
        "files/runtime-data/omnivoice/synthetic-model.txt": b"OmniVoice's model is not part of any item",
        "files/Cloned-Voice-Uploads/Sample Voice.wav": b"RIFF a reference recording stays",
        "files/keep-me.txt": b"an unrelated file stays",
    }
    for name, data in files.items():
        target = copy / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    (outside / "sentinel-dir").mkdir(parents=True, exist_ok=True)
    (outside / "sentinel.txt").write_bytes(b"a link's target outside the copy stays")
    (outside / "sentinel-dir" / "inside.txt").write_bytes(b"a linked folder's contents stay")
    for link, target in (LINKS.items() if links else ()):
        os.symlink(outside / target, copy / link)
    return files


# --------------------------------------------------------------------------------------------------------------------- #
#  Digests
# --------------------------------------------------------------------------------------------------------------------- #
def content_digest(root: Path) -> dict[str, str]:
    """Every entry below ``root`` by relative name: ``sha256:`` of a file's bytes, ``link:`` and the link's own text for a link (never
    followed), ``dir`` for an empty folder (``name/``)."""
    root = Path(root)
    found: dict[str, str] = {}
    if not root.is_dir():
        return found
    for folder, folders, files in os.walk(root, followlinks=False):
        here = Path(folder)
        relative = here.relative_to(root)
        for name in sorted([*folders, *files]):
            path = here / name
            key = (relative / name).as_posix()
            if path.is_symlink():
                found[key] = "link:" + os.readlink(path)
            elif name in files:
                found[key] = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
        if not folders and not files and str(relative) != ".":
            found[relative.as_posix() + "/"] = "dir"
    return found


def protected_locations(real_root: Path, home: Path | None = None) -> dict[str, Path]:
    """The real checkout's own data that no step of the journey may reach: its environment, FFmpeg, models, logs, settings, code, and the
    default output folder."""
    real_root = Path(real_root)
    return {"environment": real_root / ".venv", "portable_binaries": real_root / "files" / "bin",
            "models": real_root / "files" / "runtime-data" / "models", "logs": real_root / "files" / "runtime-data" / "logs",
            "settings": real_root / "files" / "runtime-data" / "settings.json", "code": real_root / "scripts",
            "default_outputs": Path(home or Path.home()) / "Downloads" / "Audiobook-Creation-Tool-Outputs"}


def protected_state(locations: dict[str, Path], tree_digest) -> dict[str, str | None]:
    """A folder by ``tree_digest`` (names, sizes, times), a file by its bytes, a missing one as None."""
    state: dict[str, str | None] = {}
    for label, path in locations.items():
        if path.is_dir():
            state[label] = "tree:" + tree_digest(path)
        elif path.is_file():
            state[label] = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
        else:
            state[label] = None
    return state


# --------------------------------------------------------------------------------------------------------------------- #
#  The copy's own word, before anything runs
# --------------------------------------------------------------------------------------------------------------------- #
_PROBE = r"""
import json, sys
root = sys.argv[1]
sys.path.insert(0, root + "/scripts")
from shared import cleanup_state, maintenance, paths
facts = {"repo_root": str(paths.REPO_ROOT), "maintenance_module": maintenance.__file__, "targets": {}, "offered": []}
for asset_id in maintenance.ASSET_IDS:
    try:
        facts["targets"][asset_id] = str(maintenance.authorized_target(asset_id, paths.REPO_ROOT))
    except maintenance.MaintenanceError as exc:
        facts["targets"][asset_id] = {"refused": str(exc)}
facts["offered"] = [item.asset_id for item in maintenance.inventory(paths.REPO_ROOT, measure=False) if item.selectable]
facts["display_names"] = {item.asset_id: item.display_name for item in maintenance.inventory(paths.REPO_ROOT, measure=False)}
facts["state_dir"] = str(cleanup_state.state_dir(paths.REPO_ROOT))
facts["coordinator_script"] = str(cleanup_state.coordinator_script())
python = cleanup_state.find_non_venv_python(paths.REPO_ROOT)
facts["interpreter"] = None if python is None else str(python)
facts["probe_interpreter"] = sys.executable
print(json.dumps(facts))
"""


def copy_facts(copy: Path, *, python: str | None = None, env: dict | None = None) -> dict:
    """What the copy's own code says about where it would clean and with what: run as a child on the interpreter the application under
    test runs on (so ``find_non_venv_python`` answers as the application will), reading only. Raises on any failure."""
    done = subprocess.run([python or sys.executable, "-I", "-B", "-c", _PROBE, str(copy)], capture_output=True, text=True, timeout=120,
                          env=env, cwd=str(copy))
    if done.returncode != 0:
        raise RuntimeError(f"the copy's own probe failed ({done.returncode}): {done.stderr[-1500:]}")
    return json.loads(done.stdout.strip().splitlines()[-1])


def _inside(root: Path, candidate: Path) -> bool:
    """Strictly inside, compared on fully resolved paths (a link anywhere in either is followed here, on purpose)."""
    root, candidate = Path(os.path.realpath(root)), Path(os.path.realpath(candidate))
    return candidate != root and root in candidate.parents


def _reaches(root: Path, candidate: Path) -> bool:
    """For a "must never be inside" rule: inside or equal, as written OR as resolved. A link is not a way out of the rule."""
    for form in (os.path.abspath, os.path.realpath):
        a, b = Path(form(root)), Path(form(candidate))
        if a == b or a in b.parents:
            return True
    return False


def _same(first, second) -> bool:
    return os.path.realpath(first) == os.path.realpath(second)


def find_links(root: Path) -> dict[str, str]:
    """Every link below ``root`` (file or folder, never followed), by relative name, with the link's own text."""
    found: dict[str, str] = {}
    for folder, folders, files in os.walk(root, followlinks=False):
        for name in [*folders, *files]:
            path = Path(folder) / name
            if path.is_symlink():
                found[path.relative_to(root).as_posix()] = os.readlink(path)
    return found


def isolation_problems(facts: dict, *, copy: Path, scratch: Path, real_root: Path, protected: dict[str, Path],
                       outside: Path, links: dict[str, str]) -> list[str]:
    """Every reason the copy is not provably the only installation the journey can make the application delete from. Empty means the
    journey may launch it. ``links`` is :func:`find_links` of the copy."""
    problems: list[str] = []
    copy, scratch, real_root = Path(copy), Path(scratch), Path(real_root)
    if not _inside(scratch, copy):
        problems.append(f"the copy {copy} is not inside the gate's scratch {scratch}")
    if _reaches(real_root, copy) or _reaches(copy, real_root):
        problems.append(f"the copy {copy} and the real checkout {real_root} overlap")
    if os.path.realpath(copy) != str(copy):
        problems.append(f"the copy's own path goes through a link ({copy} is really {os.path.realpath(copy)})")
    if not _same(facts.get("repo_root", ""), copy):
        problems.append(f"the copy's code says its root is {facts.get('repo_root')}, not {copy}")
    real_targets = [protected[key] for key in ("environment", "portable_binaries", "models", "logs") if key in protected]
    targets = facts.get("targets", {})
    for asset_id, _name, folder, _ticked in MAC_ASSETS:
        target = targets.get(asset_id)
        if not isinstance(target, str):
            problems.append(f"{asset_id}: the copy's code gave no authorized target ({target})")
            continue
        if not _same(target, copy / folder) or not _inside(copy, Path(target)):
            problems.append(f"{asset_id}: target {target} is not the copy's own {folder}")
        if os.path.realpath(target) != os.path.join(os.path.realpath(copy), *folder.split("/")):
            problems.append(f"{asset_id}: target {target} is reached through a link")
        if _reaches(real_root, Path(target)):
            problems.append(f"{asset_id}: target {target} is inside the real checkout")
        for label, path in protected.items():
            if _reaches(Path(target), path) or _reaches(path, Path(target)):
                problems.append(f"{asset_id}: target {target} reaches the real {label} ({path})")
    if sorted(facts.get("offered", [])) != sorted(asset for asset, *_ in MAC_ASSETS):
        problems.append(f"the copy does not offer exactly the four items: {facts.get('offered')}")
    state = facts.get("state_dir", "")
    string_targets = [Path(value) for value in targets.values() if isinstance(value, str)]
    if not state or not _inside(copy, Path(state)) or _reaches(real_root, Path(state)) or any(_reaches(t, Path(state)) for t in string_targets):
        problems.append(f"the maintenance state folder {state} is not the copy's own, outside every target")
    script = facts.get("coordinator_script", "")
    if not _same(script, copy / "scripts" / "shared" / "cleanup_worker.py"):
        problems.append(f"the cleanup helper {script} is not the copy's own scripts/shared/cleanup_worker.py")
    interpreter = facts.get("interpreter")
    if not interpreter:
        problems.append("the copy's code found no Python outside the copy for its helper")
    else:
        if _reaches(copy, Path(interpreter)):
            problems.append(f"the helper's interpreter {interpreter} is inside the copy, which the cleanup may remove")
        for path in real_targets:
            if _reaches(path, Path(interpreter)):
                problems.append(f"the helper's interpreter {interpreter} is inside the real {path.name}, a cleanup target")
    for relative, text in sorted(links.items()):
        expected = LINKS.get(relative)
        if expected is None:
            problems.append(f"the copy holds a link the journey did not seed: {relative} -> {text}")
            continue
        pointed = Path(text)
        if not _same(pointed, Path(outside) / expected):
            problems.append(f"{relative} points at {pointed}, not the sentinel {Path(outside) / expected}")
        if _reaches(real_root, pointed) or not _inside(scratch, pointed) or _reaches(copy, pointed):
            problems.append(f"{relative} points at {pointed}, outside the scratch sentinel")
    missing = sorted(set(LINKS) - set(links))
    if missing:
        problems.append(f"the seeded links are missing, so link safety would go unproved: {missing}")
    return problems


# --------------------------------------------------------------------------------------------------------------------- #
#  What the helper did
# --------------------------------------------------------------------------------------------------------------------- #
def outcome_problems(before: dict[str, str], after: dict[str, str], *, pinned=(), removed=REMOVED_PREFIXES, kept_empty=KEPT_EMPTY,
                     volatile=VOLATILE_PREFIXES) -> list[str]:
    """Ticked entries gone; every other entry that was there before identical; nothing new except where the application writes (and
    the engine lease's empty locks, :data:`LEASE_LOCKS`). ``pinned`` names entries under a volatile prefix that must still be identical (a seeded log)."""
    removed, volatile, pinned = tuple(removed), tuple(volatile), set(pinned)
    problems: list[str] = []
    left = sorted(name for name in before if name.startswith(removed) and name in after and name not in kept_empty)
    if left:
        problems.append(f"incomplete cleanup: {len(left)} ticked entr{'y remains' if len(left) == 1 else 'ies remain'}: {left[:6]}")
    for name, digest in sorted(before.items()):
        if name.startswith(removed):
            continue
        if name.startswith(volatile) and name not in pinned:
            continue
        if name not in after:
            problems.append(f"an unticked or protected entry was removed: {name}")
        elif after[name] != digest:
            problems.append(f"an unticked or protected entry changed: {name}")
    for name in sorted(set(after) - set(before)):
        if name in LEASE_LOCKS:
            if after[name] != EMPTY_FILE:
                problems.append(f"an engine-lease lock appeared with content: {name}")
        elif name.startswith(removed):
            if name not in kept_empty:
                problems.append(f"something new appeared inside a cleared item: {name}")
        elif not name.startswith(volatile):
            problems.append(f"something new appeared outside where the application writes: {name}")
    return problems


def tree_problems(label: str, before: dict, after: dict) -> list[str]:
    """``before`` and ``after`` must be identical; the difference, named, when they are not."""
    if before == after:
        return []
    changed = sorted(key for key in set(before) | set(after) if before.get(key) != after.get(key))
    return [f"{label} changed: {changed[:8]}{' …' if len(changed) > 8 else ''}"]
