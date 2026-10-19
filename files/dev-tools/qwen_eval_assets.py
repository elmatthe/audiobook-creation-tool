"""Pinned model assets for the isolated Qwen3-TTS evaluation (dev-only).

Never imported by the production application. Acquisition needs ``huggingface_hub``
(present in the evaluation venv, not guaranteed in the root venv), so that import is
lazy; the pure helpers below work anywhere and are covered by offline tests.

Models are copied into complete, pinned local snapshot directories under the ignored
``files/dev-work/qwen3-eval/models/`` and later loaded from those directories with
Hugging Face offline mode on. Revisions are immutable commit SHAs, not branch names.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WORK_DIR = REPO_ROOT / "files" / "dev-work" / "qwen3-eval"
MODELS_DIR = WORK_DIR / "models"
ACQUISITION_RECORD = WORK_DIR / "environment" / "model-acquisition.json"

# key -> repo, immutable revision, optional file allow-list (None = every file in the repo).
ASSETS: dict[str, dict] = {
    "qwen-customvoice": {
        "repo": "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",
        "revision": "0c0e3051f131929182e2c023b9537f8b1c68adfe",
        "allow": None,
        "license": "apache-2.0",
    },
    "qwen-base": {
        "repo": "Qwen/Qwen3-TTS-12Hz-1.7B-Base",
        "revision": "fd4b254389122332181a7c3db7f27e918eec64e3",
        "allow": None,
        "license": "apache-2.0",
    },
    # Safetensors plus processor/tokenizer files only; the msgpack/bin/h5 copies are skipped.
    "whisper-small-en": {
        "repo": "openai/whisper-small.en",
        "revision": "e8727524f962ee844a7319d92be39ac1bd25655a",
        "allow": [
            "added_tokens.json", "config.json", "generation_config.json", "merges.txt",
            "model.safetensors", "normalizer.json", "preprocessor_config.json",
            "special_tokens_map.json", "tokenizer.json", "tokenizer_config.json", "vocab.json",
        ],
        "license": "apache-2.0",
    },
}


def snapshot_dir(key: str) -> Path:
    """Local complete-snapshot directory for an asset key (may not exist yet)."""
    return MODELS_DIR / ASSETS[key]["repo"].split("/", 1)[1]


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while block := handle.read(chunk):
            digest.update(block)
    return digest.hexdigest()


def select_files(all_files: list[str], allow: list[str] | None) -> list[str]:
    """Files to keep: everything, or exactly the allow-list (which must all exist)."""
    if allow is None:
        return sorted(all_files)
    missing = sorted(set(allow) - set(all_files))
    if missing:
        raise ValueError(f"allow-listed files not in the pinned revision: {missing}")
    return sorted(allow)


def snapshot_problems(key: str, expected: dict[str, dict] | None = None, verify_hash: bool = True) -> list[str]:
    """Offline check of one local snapshot against an acquisition record; [] means intact.

    ``expected`` maps relative path -> {"size": int, "sha256": str}. Without it only the
    file allow-list (and presence) is checked. ``verify_hash=False`` compares sizes only, for
    the cheap pre-run check; the full hash runs at preparation and preflight.
    """
    root = snapshot_dir(key)
    if not root.is_dir():
        return [f"{key}: snapshot directory is missing"]
    problems: list[str] = []
    wanted = ASSETS[key]["allow"]
    names = sorted(expected) if expected else (wanted or [])
    for name in names:
        path = root / name
        if not path.is_file():
            problems.append(f"{key}: missing {name}")
            continue
        if expected:
            want = expected[name]
            if path.stat().st_size != want["size"]:
                problems.append(f"{key}: {name} size {path.stat().st_size} != {want['size']}")
            elif verify_hash and sha256_file(path) != want["sha256"]:
                problems.append(f"{key}: {name} sha256 mismatch")
    return problems


def acquire(key: str) -> dict:
    """Download one pinned asset into its local snapshot directory and verify it.

    Large LFS files are verified against the hash the Hub declares for them. Returns the
    per-file record that is also merged into ``model-acquisition.json``.
    """
    from huggingface_hub import HfApi, snapshot_download  # lazy: evaluation venv only

    spec = ASSETS[key]
    api = HfApi()
    info = api.model_info(spec["repo"], revision=spec["revision"], files_metadata=True)
    if info.sha != spec["revision"]:
        raise RuntimeError(f"{key}: Hub reports {info.sha}, expected pinned {spec['revision']}")
    keep = select_files([s.rfilename for s in info.siblings], spec["allow"])
    declared = {s.rfilename: s for s in info.siblings}
    target = snapshot_dir(key)
    target.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id=spec["repo"], revision=spec["revision"], local_dir=str(target), allow_patterns=keep
    )
    files: dict[str, dict] = {}
    for name in keep:
        path = target / name
        digest = sha256_file(path)
        lfs = getattr(declared[name], "lfs", None)
        lfs_sha = lfs.get("sha256") if isinstance(lfs, dict) else getattr(lfs, "sha256", None)
        if lfs_sha and lfs_sha != digest:
            raise RuntimeError(f"{key}: {name} sha256 {digest} != Hub-declared {lfs_sha}")
        files[name] = {"size": path.stat().st_size, "sha256": digest, "hub_verified": bool(lfs_sha)}
    record = {
        "repo": spec["repo"], "revision": spec["revision"], "license": spec["license"],
        "snapshot": str(target.relative_to(REPO_ROOT)).replace("\\", "/"),
        "total_bytes": sum(f["size"] for f in files.values()), "files": files,
    }
    merge_record(key, record)
    return record


def merge_record(key: str, record: dict) -> None:
    ACQUISITION_RECORD.parent.mkdir(parents=True, exist_ok=True)
    current = {}
    if ACQUISITION_RECORD.is_file():
        current = json.loads(ACQUISITION_RECORD.read_text(encoding="utf-8"))
    current[key] = record
    tmp = ACQUISITION_RECORD.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(current, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(ACQUISITION_RECORD)


def load_record() -> dict:
    if not ACQUISITION_RECORD.is_file():
        return {}
    return json.loads(ACQUISITION_RECORD.read_text(encoding="utf-8"))


if __name__ == "__main__":  # python qwen_eval_assets.py <key> [<key> ...]
    import sys

    for asset_key in sys.argv[1:]:
        rec = acquire(asset_key)
        print(f"{asset_key}: {rec['total_bytes']:,} bytes in {len(rec['files'])} files -> {rec['snapshot']}")
