"""macos_p4a_omnivoice.py -- ACT v0.8.x macOS P4A: the bounded OmniVoice feasibility campaign's acquisition side.

Developer only: never shipped, never imported by the application, no product code. It prepares, on an Apple Silicon Mac,
exactly what the P4A experiment would use, and nothing is acquired without the owner's consent:

* ``derive``          upstream OmniVoice 0.2.1's own ``uv.lock`` (hash-checked against ACT's recorded lock identity)
                      resolved for THIS interpreter (darwin arm64, CPython 3.12, no extras) as uv would select it, each
                      package's best wheel by this interpreter's own tags, into ``macos_p4a_omnivoice_manifest.json``.
                      The model section is ACT's own pinned snapshot, copied unchanged. Reads a local lock; no network.
* ``check-upstream``  read-only metadata cross-check: PyPI still lists every wheel with the same SHA-256 and size (not
                      yanked); Hugging Face lists every model file at the pinned revision with the same size and LFS
                      SHA-256. Downloads no package or model file.
* ``op-probe``        whether the PyTorch ops OmniVoice's sampling loop uses (guided log_softmax, argmax, max, topk,
                      SDPA) give the CPU's answer on this Mac's MPS device, at OmniVoice's own shapes. INDICATIVE: it
                      runs on whatever torch this interpreter has, not OmniVoice's pinned 2.8.0.
* ``plan``            what ``fetch`` would transfer, from which hosts, to which ignored folders, the disk it needs, and the
                      consent token (the manifest's SHA-256). No network.
* ``fetch``           ONLY with ``--consent <the plan's token>``: every pinned wheel and model file, each accepted only at
                      its exact size and SHA-256 (``tts.qwen3_setup.download_file``: resumable, bounded, verified), into
                      ``files/dev-work/omnivoice-feasibility/``. Nothing goes to a pip or Hugging Face cache.

Everything it writes stays under ``files/dev-work/omnivoice-feasibility/`` (ignored, disposable) except ``derive``'s
manifest, which is reviewable data beside this tool. Run it with the app's interpreter:
``.venv/bin/python -I files/dev-tools/macos_p4a_omnivoice.py <command>``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from shared import venv_layout  # noqa: E402
from tts import qwen3_runtime as rt  # noqa: E402

MANIFEST = HERE / "macos_p4a_omnivoice_manifest.json"
ACT_MANIFEST = REPO / "scripts" / "tts" / "omnivoice_manifest.json"
AREA = REPO / "files" / "dev-work" / "omnivoice-feasibility"
SCHEMA = "act-macos-p4a-omnivoice"
UPSTREAM_COMMIT = "5ba967c4d5b0f08244ae856b033eea583d1e4517"
LOCK_URL = f"https://raw.githubusercontent.com/k2-fsa/OmniVoice/{UPSTREAM_COMMIT}/uv.lock"
PYPI_FILES = "https://files.pythonhosted.org/packages/"
#: Installed size of the darwin environment, ESTIMATED from the same packages already in ACT's .venv on this Mac
#: (torch 2.6.0 342 MiB, llvmlite 125 MiB, scipy 97 MiB, transformers 95 MiB ...); measured after ``create-env``.
ENV_ESTIMATE_BYTES = 1_300_000_000
#: Outputs, logs and clone prompts of the bounded campaign (24-bit/float WAVs of a few minutes per configuration).
OUTPUT_ESTIMATE_BYTES = 400_000_000


def area() -> dict[str, Path]:
    return {"wheels": AREA / "wheels", "model": AREA / "model", "venv": AREA / "venv", "runs": AREA / "runs",
            "hf_home": AREA / "hf-home", "receipts": AREA / "receipts", "upstream": AREA / "upstream"}


def model_dir(manifest: dict) -> Path:
    model = manifest["model"]
    return area()["model"] / model["repo"].replace("/", "--") / model["revision"]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def load_manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def consent_token() -> str:
    """The manifest's SHA-256: consent names exactly these files, these sizes and these hashes, nothing else."""
    return rt.sha256_file(MANIFEST)


# --------------------------------------------------------------------------- #
# derive
# --------------------------------------------------------------------------- #
def resolve(lock_text: str, act_manifest: dict) -> tuple[list[dict], list[str]]:
    """The darwin wheel set of upstream's lock for this interpreter: (rows, problems)."""
    import tomllib

    from packaging.markers import Marker
    from packaging.tags import sys_tags
    from packaging.utils import canonicalize_name, parse_wheel_filename

    env = {"sys_platform": sys.platform, "platform_machine": platform.machine(), "platform_system": platform.system(),
           "os_name": os.name, "implementation_name": sys.implementation.name,
           "platform_python_implementation": platform.python_implementation(),
           "python_version": f"{sys.version_info.major}.{sys.version_info.minor}",
           "python_full_version": platform.python_version(), "extra": ""}
    packages = tomllib.loads(lock_text)["package"]
    by_name: dict[str, list[dict]] = {}
    for pkg in packages:
        by_name.setdefault(canonicalize_name(pkg["name"]), []).append(pkg)

    def ok(marker) -> bool:
        return True if not marker else Marker(marker).evaluate(env)

    def target(dep: dict) -> dict:
        pkgs = by_name[canonicalize_name(dep["name"])]
        if "version" in dep:
            pkgs = [p for p in pkgs if p["version"] == dep["version"]]
        if "source" in dep:
            pkgs = [p for p in pkgs if p.get("source") == dep["source"]]
        if len(pkgs) > 1:
            pkgs = [p for p in pkgs if any(ok(m) for m in p.get("resolution-markers", [""]))]
        if len(pkgs) != 1:
            raise SystemExit(f"the lock does not resolve {dep['name']} to one package on this platform")
        return pkgs[0]

    roots = [p for p in packages if canonicalize_name(p["name"]) == "omnivoice"]
    resolved: dict[str, dict] = {}
    queue = list(roots)
    while queue:
        pkg = queue.pop()
        key = canonicalize_name(pkg["name"])
        if key in resolved:
            if resolved[key]["version"] != pkg["version"]:
                raise SystemExit(f"{key} resolves to two versions")
            continue
        resolved[key] = pkg
        queue.extend(target(d) for d in pkg.get("dependencies", []) if ok(d.get("marker")))  # no extras

    rank = {tag: i for i, tag in enumerate(sys_tags())}
    rows, problems = [], []
    for key, pkg in sorted(resolved.items()):
        if key == "omnivoice":
            continue  # the lock's root is upstream's checkout; ACT installs the released pure wheel (below)
        best = None
        for wheel in pkg.get("wheels", []):
            filename = wheel["url"].rsplit("/", 1)[1]
            score = min((rank[t] for t in parse_wheel_filename(filename)[3] if t in rank), default=None)
            if score is not None and (best is None or score < best[0]):
                best = (score, filename, wheel)
        if best is None:
            problems.append(f"{key} {pkg['version']}: no wheel for this interpreter")
            continue
        _, filename, wheel = best
        rows.append({"name": key, "version": pkg["version"], "filename": filename, "url": wheel["url"],
                     "size": wheel["size"], "sha256": wheel["hash"].removeprefix("sha256:")})
    own = [w for w in act_manifest["wheels"] if w["name"] == "omnivoice"]
    if len(own) != 1 or not own[0]["filename"].endswith("-py3-none-any.whl"):
        problems.append("ACT's manifest does not pin one pure omnivoice wheel")
    else:
        rows.append({k: own[0][k] for k in ("name", "version", "filename", "url", "size", "sha256")})
    rows.sort(key=lambda r: r["name"])
    problems += [f"{r['filename']}: not a PyPI file URL" for r in rows if not r["url"].startswith(PYPI_FILES)]
    return rows, problems


def cmd_derive(args) -> int:
    act = json.loads(ACT_MANIFEST.read_text(encoding="utf-8"))
    lock_bytes = Path(args.lock).read_bytes()
    if sha256_bytes(lock_bytes) != act["engine"]["uv_lock_sha256"]:
        print("REFUSED: this uv.lock is not the one ACT's OmniVoice manifest records")
        return 2
    rows, problems = resolve(lock_bytes.decode("utf-8"), act)
    if problems:
        print("REFUSED:", *problems, sep="\n  ")
        return 2
    from packaging.tags import sys_tags

    manifest = {
        "schema": SCHEMA, "version": 1,
        "purpose": ("macOS P4A only (developer feasibility, never shipped): the exact files the bounded OmniVoice "
                    "experiment may acquire under the owner's consent. Wheels: upstream OmniVoice 0.2.1's own uv.lock "
                    "resolved for darwin arm64 / CPython 3.12 without extras, each the best wheel for the app's "
                    "interpreter. Model: ACT's pinned snapshot, copied unchanged from scripts/tts/omnivoice_manifest.json."),
        "engine": {"omnivoice": act["engine"]["omnivoice"], "python": act["engine"]["python"],
                   "platform": "macosx_arm64", "git_commit": act["engine"]["git_commit"],
                   "uv_lock_sha256": act["engine"]["uv_lock_sha256"], "uv_lock_url": LOCK_URL,
                   "resolved_for": {"python": platform.python_version(), "machine": platform.machine(),
                                    "best_tag": str(next(iter(sys_tags())))}},
        "licenses": act["licenses"], "model": act["model"], "wheels": rows,
        "totals": {"wheels": len(rows), "wheel_bytes": sum(r["size"] for r in rows),
                   "model_files": len(act["model"]["files"]),
                   "model_bytes": sum(e["size"] for e in act["model"]["files"].values())},
        "vs_windows": {
            "only_windows": sorted(f"{n}=={v}" for n, v in act["packages"]
                                   if n not in {r["name"] for r in rows}),
            "version_differs": sorted(f"{r['name']}: windows {dict(act['packages'])[r['name']]}, macOS {r['version']}"
                                      for r in rows if dict(act["packages"]).get(r["name"]) not in (None, r["version"])),
        },
    }
    text = json.dumps(manifest, indent=1, ensure_ascii=False) + "\n"
    if args.check:
        same = MANIFEST.is_file() and MANIFEST.read_text(encoding="utf-8") == text
        print("the manifest re-derives byte-for-byte" if same else "DIFFERS from a fresh derivation")
        return 0 if same else 1
    MANIFEST.write_text(text, encoding="utf-8")
    print(f"{MANIFEST.name}: {len(rows)} wheels, {manifest['totals']['wheel_bytes']:,} bytes; model "
          f"{manifest['totals']['model_bytes']:,} bytes; SHA-256 {consent_token()}")
    return 0


# --------------------------------------------------------------------------- #
# check-upstream
# --------------------------------------------------------------------------- #
def _get_json(url: str):
    import urllib.request

    request = urllib.request.Request(url, headers={"User-Agent": "act-p4a-metadata-check"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def cmd_check_upstream(_args) -> int:
    import concurrent.futures as cf

    manifest = load_manifest()

    def wheel(row: dict) -> dict:
        try:
            data = _get_json(f"https://pypi.org/pypi/{row['name']}/{row['version']}/json")
        except Exception as exc:  # noqa: BLE001
            return {"wheel": row["filename"], "ok": False, "why": f"metadata: {exc}"[:160]}
        match = [u for u in data.get("urls", []) if u["filename"] == row["filename"]]
        why = [] if match else ["not listed"]
        if match:
            u = match[0]
            why += [w for w, bad in (("sha256 differs", u["digests"]["sha256"] != row["sha256"]),
                                     ("size differs", u["size"] != row["size"]), ("yanked", bool(u.get("yanked"))))
                    if bad]
        return {"wheel": row["filename"], "ok": not why, "why": "; ".join(why)}

    with cf.ThreadPoolExecutor(8) as pool:
        wheels = list(pool.map(wheel, manifest["wheels"]))
    model = manifest["model"]
    listed = {e["path"]: e for e in _get_json(f"https://huggingface.co/api/models/{model['repo']}/tree/"
                                              f"{model['revision']}?recursive=1") if e.get("type") == "file"}
    files = []
    for path, spec in model["files"].items():
        entry = listed.get(path) or {}
        lfs = (entry.get("lfs") or {}).get("oid")
        why = [w for w, bad in (("not listed", not entry), ("size differs", entry and entry.get("size") != spec["size"]),
                                ("lfs sha256 differs", lfs is not None and lfs != spec["sha256"])) if bad]
        files.append({"file": path, "ok": not why, "why": "; ".join(why), "hash": "lfs" if lfs else "size"})
    record = {"checked": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "manifest_sha256": consent_token(),
              "wheels_ok": sum(w["ok"] for w in wheels), "wheels": len(wheels),
              "wheel_problems": [w for w in wheels if not w["ok"]],
              "model_ok": sum(f["ok"] for f in files), "model_files": len(files),
              "model_problems": [f for f in files if not f["ok"]], "model_rows": files,
              "unpinned_at_revision": sorted(p for p in listed if p not in model["files"])}
    write_json(area()["receipts"] / "check-upstream.json", record)
    print(json.dumps({k: v for k, v in record.items() if k != "model_rows"}, indent=1))
    return 0 if not record["wheel_problems"] and not record["model_problems"] else 1


# --------------------------------------------------------------------------- #
# op-probe
# --------------------------------------------------------------------------- #
def cmd_op_probe(_args) -> int:
    import torch
    import torch.nn.functional as F

    record = {"torch": torch.__version__, "python": platform.python_version(),
              "macos": subprocess.run(["sw_vers", "-productVersion"], capture_output=True, text=True).stdout.strip(),
              "build": subprocess.run(["sw_vers", "-buildVersion"], capture_output=True, text=True).stdout.strip(),
              "mps_built": torch.backends.mps.is_built(), "mps_available": torch.backends.mps.is_available(),
              "indicative": "torch here is the app's, not OmniVoice's pinned 2.8.0", "cases": []}
    if not record["mps_available"]:
        record["verdict"] = "BLOCKED: MPS is not available in this session"
        write_json(area()["receipts"] / f"op-probe-torch{torch.__version__}.json", record)
        print(record["verdict"])
        return 0
    gen = torch.Generator().manual_seed(20261116)
    vocab, mask, books = 1025, 1024, 8  # OmniVoiceConfig defaults: audio_vocab_size, audio_mask_id, num_audio_codebook

    def case(name: str, good: bool, **detail) -> None:
        record["cases"].append({"case": name, "ok": bool(good), **detail})

    for frames in (50, 375, 750):  # 2, 15 and 30 s of speech at 25 frames a second
        for dtype in (torch.float32, torch.float16):
            label = f"{frames}f {str(dtype)[6:]}"
            c_lp = F.log_softmax(torch.randn(1, books, frames, vocab, generator=gen) * 4.0, dim=-1)
            u_lp = F.log_softmax(c_lp + torch.randn(c_lp.shape, generator=gen), dim=-1)
            ref = torch.log_softmax(c_lp.to(dtype).float() + 2.0 * (c_lp.to(dtype).float() - u_lp.to(dtype).float()),
                                    -1)
            mps_c, mps_u = c_lp.to("mps", dtype), u_lp.to("mps", dtype)
            mps = torch.log_softmax(mps_c + 2.0 * (mps_c - mps_u), dim=-1)
            mps[..., mask] = float("-inf")
            diff = (mps[..., :mask].float().cpu() - ref[..., :mask]).abs().max().item()
            tol = 1e-4 if dtype == torch.float32 else 5e-2
            case(f"guided log_softmax {label}", torch.isfinite(mps[..., :mask]).all().item() and diff < tol,
                 max_abs_diff=diff, tol=tol)
            as_cpu = mps.float().cpu()
            wrong = int((as_cpu.argmax(dim=-1) != mps.argmax(dim=-1).cpu()).sum().item())
            case(f"argmax {label}", wrong == 0, mismatches=wrong, of=int(as_cpu[..., 0].numel()))
            case(f"max {label}", torch.equal(as_cpu.max(dim=-1)[0], mps.max(dim=-1)[0].float().cpu()))
            scores = as_cpu.max(dim=-1)[0]
            k = max(1, scores.numel() // 7)
            sym = set(torch.topk(scores.flatten(), k).indices.tolist()) ^ set(
                torch.topk(scores.to("mps", dtype).flatten(), k).indices.cpu().tolist())
            case(f"topk {label}", len(sym) <= (0 if dtype == torch.float32 else k // 50), symmetric_difference=len(sym),
                 k=k)
    for length in (400, 1200):
        q, kk, v = (torch.randn(2, 16, length, 128, generator=gen) for _ in range(3))
        attn = torch.ones(2, 1, length, length, dtype=torch.bool)
        attn[1, :, :, length // 2:] = False
        cpu = F.scaled_dot_product_attention(q, kk, v, attn_mask=attn)
        for dtype in (torch.float32, torch.float16):
            out = F.scaled_dot_product_attention(q.to("mps", dtype), kk.to("mps", dtype), v.to("mps", dtype),
                                                 attn_mask=attn.to("mps"))
            torch.mps.synchronize()
            diff = (out.float().cpu() - cpu).abs().max().item()
            tol = 1e-4 if dtype == torch.float32 else 2e-2
            case(f"sdpa L={length} {str(dtype)[6:]}", torch.isfinite(out).all().item() and diff < tol,
                 max_abs_diff=diff, tol=tol)
    record["failed"] = [c["case"] for c in record["cases"] if not c["ok"]]
    record["verdict"] = ("MPS agrees with the CPU (indicative)" if not record["failed"]
                         else "MPS DIFFERS from the CPU: " + ", ".join(record["failed"]))
    write_json(area()["receipts"] / f"op-probe-torch{torch.__version__}.json", record)
    print(record["verdict"], f"({len(record['cases'])} cases; torch {torch.__version__}; macOS {record['macos']})")
    return 0 if not record["failed"] else 1


# --------------------------------------------------------------------------- #
# plan / fetch
# --------------------------------------------------------------------------- #
def acquisition_items(manifest: dict) -> list[tuple[str, str, Path, int, str]]:
    items = [("wheel", w["url"], area()["wheels"] / w["filename"], w["size"], w["sha256"]) for w in manifest["wheels"]]
    m = manifest["model"]
    items += [("model", m["url_template"].format(repo=m["repo"], revision=m["revision"], path=rel),
               model_dir(manifest).joinpath(*rel.split("/")), e["size"], e["sha256"]) for rel, e in m["files"].items()]
    return items


def present(path: Path, size: int, sha256: str) -> bool:
    try:
        return path.is_file() and not venv_layout.is_link(path) and path.stat().st_size == size \
            and rt.sha256_file(path) == sha256
    except OSError:
        return False


def cmd_plan(_args) -> int:
    manifest = load_manifest()
    items = acquisition_items(manifest)
    todo = [i for i in items if not present(i[2], i[3], i[4])]
    wheel_bytes = sum(i[3] for i in todo if i[0] == "wheel")
    model_bytes = sum(i[3] for i in todo if i[0] == "model")
    free = shutil.disk_usage(REPO).free
    need = wheel_bytes + model_bytes + ENV_ESTIMATE_BYTES + OUTPUT_ESTIMATE_BYTES
    hosts = sorted({i[1].split("/")[2] for i in todo})
    plan = {
        "consent_token": consent_token(), "manifest": str(MANIFEST.relative_to(REPO)),
        "wheels": {"to_fetch": sum(1 for i in todo if i[0] == "wheel"), "bytes": wheel_bytes,
                   "destination": str(area()["wheels"].relative_to(REPO))},
        "model": {"repo": manifest["model"]["repo"], "revision": manifest["model"]["revision"],
                  "to_fetch": sum(1 for i in todo if i[0] == "model"), "bytes": model_bytes,
                  "destination": str(model_dir(manifest).relative_to(REPO))},
        "hosts": hosts, "transfer_bytes": wheel_bytes + model_bytes,
        "environment": {"destination": str(area()["venv"].relative_to(REPO)), "estimated_bytes": ENV_ESTIMATE_BYTES,
                        "built_from": "files/runtime-data/python (the app-owned CPython 3.12.15), offline from the "
                                      "verified wheels only (--no-index --no-deps --require-hashes)"},
        "outputs_estimated_bytes": OUTPUT_ESTIMATE_BYTES, "disk_needed_bytes": need, "free_bytes": free,
        "enough_disk": free > 2 * need,
        "not_acquired": ["Whisper or any other ASR model", "the eustlb/higgs-audio-v2-tokenizer fallback repo",
                         "Chatterbox, Qwen3 or any other engine", "MLX or converted weights", "a newer revision"],
    }
    write_json(area()["receipts"] / "plan.json", plan)
    print(json.dumps(plan, indent=1))
    return 0


def cmd_fetch(args) -> int:
    token = consent_token()
    if args.consent != token:
        print(f"REFUSED: no consent for this manifest. The owner consents to the plan whose token is {token}.")
        return 2
    manifest = load_manifest()
    items = [i for i in acquisition_items(manifest) if args.only in (None, i[0])]
    from tts import qwen3_setup  # the app's verified downloader: resumes, refuses a wrong size or hash

    fetched = kept = 0
    for kind, url, path, size, sha256 in items:
        if venv_layout.unsafe_component(REPO, path.parent) is not None:
            print(f"REFUSED: {path.parent} is reached through a link")
            return 2
        if present(path, size, sha256):
            kept += size
            continue
        print(f"[fetch] {kind}: {path.name} ({size:,} bytes)", flush=True)
        qwen3_setup.download_file(url, path, size, sha256)
        fetched += size
    record = {"finished": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "consent_token": token, "only": args.only,
              "fetched_bytes": fetched, "already_present_bytes": kept,
              "all_present": all(present(i[2], i[3], i[4]) for i in items)}
    write_json(area()["receipts"] / f"fetch-{args.only or 'all'}.json", record)
    print(json.dumps(record, indent=1))
    return 0 if record["all_present"] else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    derive = sub.add_parser("derive")
    derive.add_argument("--lock", default=str(area()["upstream"] / "uv.lock"))
    derive.add_argument("--check", action="store_true", help="re-derive and compare; write nothing")
    sub.add_parser("check-upstream")
    sub.add_parser("op-probe")
    sub.add_parser("plan")
    fetch = sub.add_parser("fetch")
    fetch.add_argument("--consent", required=True)
    fetch.add_argument("--only", choices=("wheel", "model"))
    args = parser.parse_args(argv)
    return {"derive": cmd_derive, "check-upstream": cmd_check_upstream, "op-probe": cmd_op_probe, "plan": cmd_plan,
            "fetch": cmd_fetch}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
