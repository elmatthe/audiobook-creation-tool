"""The ``optional-engines`` qualification: bounded REAL synthesis on Kokoro, Chatterbox Turbo and Qwen3-TTS (v0.7.2 Phase 8).

    verify.py --mode qualification --scenario optional-engines

Two voices per engine narrate one multi-paragraph text through the real TTS panel (``panel_run.py``, one contained process per
voice): for Chatterbox two of the six bundled reference voices, for Qwen3 one preset CustomVoice and one cloned voice. Eight workers
are asked for every time, because the local engines must stay at one whatever is asked.

**Offline, and nothing is installed.** The engines and models already on this computer are read where the application keeps them.
Every panel process refuses any non-loopback connection for its whole life and records each attempt; a missing model or engine is
BLOCKED with its name, never a download. The models and the Qwen3 engine are fingerprinted before and after and must be unchanged.

What is judged is the published MP3, decoded independently: that it is all there (a duration the text's length allows, speech
throughout, no long hole where a chunk went missing), that it ends as a narration ends (quiet, not cut off, no long tail), and
that source files are untouched. What is NOT judged: how it sounds. Listening is the owner's, and the samples are kept for it
under ``samples/`` in this run's folder.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import common  # noqa: E402

RUNTIME = common.REPO_ROOT / "files" / "runtime-data"
HUB = RUNTIME / "models" / "huggingface" / "hub"
#: engine -> (what must already be installed, the two voices narrated)
ENGINES = {
    "kokoro": ((HUB / "models--hexgrad--Kokoro-82M",),
               ("Kokoro Female (Default) - Heart (en-US)", "Kokoro Male - George (en-UK)")),
    "chatterbox": ((HUB / "models--ResembleAI--chatterbox-turbo", common.REPO_ROOT / "files" / "Cloned-Voice-Uploads"),
                   ("Chatterbox - Female 1", "Chatterbox - Male 3")),
    "qwen3": ((RUNTIME / "models" / "qwen3-tts", common.REPO_ROOT / ".venv" / "engines" / "qwen3" / "Scripts" / "python.exe"),
              ("Qwen3 - Ryan", "Qwen3 - Male 2")),
}
TEXT = """Chapter One.

The lighthouse keeper climbed the narrow stairs as the storm gathered over the harbour. He counted every step, as he had done for thirty years, and at the top he lit the great lamp. Far below, the first waves broke white against the rocks.

"Will it hold?" asked the boy, who had followed him up without being asked. The keeper did not answer at once. He trimmed the wick, wiped the glass with his sleeve, and listened to the wind find the gaps in the old stone.

By midnight the lamp was the only light for thirty miles. Two fishing boats came in under it, slowly, one behind the other, and the men on deck raised their hands to the tower as they passed.

In the morning the sea was flat and grey. The boy slept on a coil of rope by the door, and the keeper wrote one line in the log: the light was kept.
"""
#: Kokoro takes up to 3,000 characters in one piece, so its text is long enough to need two.
MORE = """
Chapter Two.

The supply boat came on the first calm day, low in the water with oil, flour and a crate of books that nobody had ordered. Its captain was a narrow woman called Maren, who talked the whole way up the path and stopped only to count the steps under her breath. She had counted them every month for eleven years and had never once reached the same number twice.

"You have a visitor," she said, and nodded at the boy, who was pretending to mend a net. "Does he belong to anyone?" The keeper said that he belonged to the weather, as far as he could tell, and that the weather had not been back to collect him.

They unloaded until noon. The oil went into the cool room under the stairs, forty tins in four rows, and the flour went up to the kitchen in two trips. The books stayed in their crate by the door. Maren said they were from a school on the mainland that had closed, and that the teacher had written the lighthouse on the lid because it was the only address she could think of where somebody would certainly be at home.

Chapter Three.

That winter the boy read every book in the crate, some of them twice. He read aloud in the evenings, slowly at first and then faster, while the keeper cleaned the lamp and pretended not to listen. There was a book about rivers, a book about the stars, and a thin green book of poems that neither of them understood and both of them liked.

On the longest night of the year the wind dropped completely. The sea lay still enough to show the light back to itself, one bright road running from the rocks to the edge of the world. The boy closed the book about the stars and went to the window. "It looks like a door," he said. The keeper came and stood beside him, and for once he agreed.

When spring came the boat brought a letter. It was addressed to the lighthouse, in careful handwriting, and it asked whether the books had arrived and whether anyone had found a use for them. The keeper gave the boy a pencil and the back of a chart, and the boy wrote for most of an afternoon. He began with the rivers.

Chapter Four.

The answer took a month to come back, and it was longer than the letter that had been sent. The teacher wrote that she had kept the school for nineteen years and had never been sure that anything she taught had travelled further than the playground wall. She asked which poem they had liked best. She asked whether the stars looked different from a tower. She asked, in a careful postscript, whether the boy would like more books, because she had a great many and nowhere to put them.

The keeper read it twice and put it under the lamp glass, where he kept the things he meant to answer. The boy read it nine times. Then he went down to the rocks to wait for the boat, although it was not due for another three weeks, and the keeper let him.
"""
TEXTS = {"kokoro": TEXT + MORE, "chatterbox": TEXT, "qwen3": TEXT}


def fingerprint(root: Path) -> dict:
    """How many files and bytes, and a digest of every name and size. Reading it changes nothing."""
    import hashlib

    digest, count, total = hashlib.sha256(), 0, 0
    if root.is_file():
        return {"files": 1, "bytes": root.stat().st_size}
    for folder, folders, files in os.walk(root):
        folders.sort()
        for name in sorted(files):
            if name.endswith((".pyc", ".lock")):
                continue
            path = Path(folder) / name
            try:
                size = path.stat().st_size
            except OSError:
                continue
            count += 1
            total += size
            digest.update(f"{path.relative_to(root).as_posix()}\0{size}\n".encode())
    return {"files": count, "bytes": total, "digest": digest.hexdigest()[:16]}


def gpu() -> dict:
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=name,driver_version,memory.total,memory.used", "--format=csv,noheader"],
                             capture_output=True, text=True, timeout=20, creationflags=0x08000000)
        return {"present": out.returncode == 0 and bool(out.stdout.strip()), "line": out.stdout.strip()}
    except (OSError, subprocess.SubprocessError) as exc:
        return {"present": False, "line": f"{type(exc).__name__}: {exc}"}


def judge(run: common.Scenario, engine: str, voice: str, record: dict) -> None:
    result = record["result"]
    name = f"{engine} / {voice}"
    if not run.check(f"{name}: the run produced a record", result is not None and record["ended"] == "exited",
                     record.get("no_result") or f"exit {record['exit']} after {record['seconds']} s"):
        return
    run.check(f"{name}: narrated to the end", result["finished"] and result["state"] == "SUCCEEDED" and result["succeeded"] == 1
              and not result["failed"], {key: result[key] for key in ("state", "succeeded", "failed", "cancelled")})
    outputs = result["outputs"]
    if not run.check(f"{name}: exactly one MP3 was published", len(outputs) == 1, [item["name"] for item in outputs]):
        return
    audio = outputs[0]
    stream = (audio["probe"].get("streams") or [{}])[0]
    run.check(f"{name}: it is a real MP3 that decodes without error", stream.get("codec_name") == "mp3" and audio["decode_exit"] == 0
              and not audio["decode_errors"], {"codec": stream.get("codec_name"), "errors": audio["decode_errors"]})
    characters = len(TEXTS[engine])
    seconds = audio["decoded_seconds"]
    run.check(f"{name}: its length is what {characters} characters take to read", characters / 30 <= seconds <= characters / 5,
              f"{seconds} s", seconds=seconds, sha256=audio["sha256"], bytes=audio["bytes"])
    run.check(f"{name}: there is speech throughout, with no hole where a chunk went missing",
              audio.get("voiced_fraction", 0) >= 0.4 and audio.get("rms_dbfs", -99) > -45 and audio.get("longest_inner_silence_s", 99) <= 3.5,
              {key: audio.get(key) for key in ("voiced_fraction", "rms_dbfs", "peak_dbfs", "longest_inner_silence_s")})
    run.check(f"{name}: it starts promptly and ends as a narration ends (quiet, not cut off, no long tail)",
              (audio.get("leading_silence_s") or 0) <= 2.0 and (audio.get("trailing_silence_s") or 0) <= 2.5
              and audio.get("last_frame_dbfs", 0) <= -30,
              {key: audio.get(key) for key in ("leading_silence_s", "trailing_silence_s", "last_frame_dbfs")})
    pieces = [int(number) for line in result["chunk_lines"] for found in re.findall(r"\d+\s*/\s*(\d+)|(\d+) (?:chunk|segment)", line)
              for number in found if number]
    run.check(f"{name}: the text was narrated in more than one piece", max(pieces, default=0) >= 2,
              f"largest count the log names: {max(pieces, default=0)}; {result['chunk_lines'][:2]}")
    one_worker = [line for line in result["worker_lines"] if re.search(r"\b1\b", line)]
    run.check(f"{name}: eight workers were asked for and one was used", bool(one_worker) and result["requested_workers"] == 8,
              result["worker_lines"][:4])
    run.check(f"{name}: nothing was downloaded, asked for or installed", not result["network_attempts"]
              and not [m for m in result["messages"] if m[0] in ("install-dialog", "showerror", "askyesno")],
              {"network": result["network_attempts"][:3], "messages": result["messages"][:3]})
    run.check(f"{name}: the source text is untouched and nothing but the MP3 was left in the output folder",
              result["sources_unchanged"] and not result["leftovers_in_output"], result["leftovers_in_output"][:5])
    sample = run.root / "samples" / f"{engine}--{re.sub(r'[^A-Za-z0-9]+', '-', voice).strip('-')}.mp3"
    sample.parent.mkdir(exist_ok=True)
    shutil.copyfile(Path(result["containment"]["output_base"]) / result["published_at_end"][0], sample)
    record["sample"] = str(sample.relative_to(run.root))
    record["measured"] = {"engine": engine, "voice": voice, "seconds": seconds, "sha256": audio["sha256"], **result["sampler"],
                          "run_seconds": result["run_seconds"], "identity": result["identity"]}


def body(run: common.Scenario) -> None:
    if not (common.SCRIPTS / "tts" / "epub2tts_gui.py").is_file():
        raise common.Blocked("the application's TTS code is not here")
    missing = [f"{engine}: {path.relative_to(common.REPO_ROOT)}" for engine, (needed, _voices) in ENGINES.items()
               for path in needed if not path.exists()]
    if missing:
        raise common.Blocked(f"not installed on this computer, and this scenario never downloads: {missing}")
    card = gpu()
    watched = {"models": RUNTIME / "models", "qwen3-engine": common.REPO_ROOT / ".venv" / "engines" / "qwen3",
               "chatterbox-conditionals": RUNTIME / "chatterbox", "reference-voices": common.REPO_ROOT / "files" / "Cloned-Voice-Uploads"}
    before = {name: fingerprint(path) for name, path in watched.items()}
    identity = run.identity(gpu=card, installed=before)
    run.log(f"identity: HEAD {identity['head']}, code {identity['code_digest'][:12]}, GPU {card['line']}")
    engines = ENGINES
    measured = []
    for engine, (_needed, voices) in engines.items():
        source = run.root / "source" / engine / "The Keeper.txt"
        source.parent.mkdir(parents=True)
        source.write_text(TEXTS[engine], encoding="utf-8")
        for voice in voices[:1] if run.args.smoke else voices:
            label = f"{engine}-{re.sub(r'[^A-Za-z0-9]+', '-', voice).strip('-').lower()}"
            case = run.root / "cases" / f"{label}.json"
            case.parent.mkdir(exist_ok=True)
            case.write_text(json.dumps({"label": label, "voice": voice, "workers": 8, "direct": [str(source)], "gpu": True,
                                        "timeout": 2400}), encoding="utf-8")
            record = run.child(label, HERE / "panel_run.py", ["--case", str(case)], timeout=2700,
                               env={"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "HF_HUB_DISABLE_TELEMETRY": "1"})
            judge(run, engine, voice, record)
            if record.get("measured"):
                measured.append(record["measured"])
    (run.root / "measured.json").write_text(json.dumps(measured, indent=1), encoding="utf-8")
    after = {name: fingerprint(path) for name, path in watched.items()}
    for name in watched:
        run.check(f"installed {name}: unchanged by the run", before[name] == after[name], f"{before[name]} -> {after[name]}")
    if not run.args.smoke:
        kinds = {item["engine"] for item in measured}
        run.check("every engine produced a measured sample", kinds == set(ENGINES), sorted(kinds))
        qwen = [item for item in measured if item["engine"] == "qwen3"]
        run.check("Qwen3 ran in its own engine process", all(any("python" in image for image in item["child_images_seen"]) for item in qwen)
                  and bool(qwen), [item["child_images_seen"] for item in qwen])
        # Recorded, not required: which device each engine ran on is a fact of this installation (its own Python packages decide),
        # and the report names it. What is required is that the measurement exists for every sample.
        run.check("memory was measured for every sample", all(item.get("peak_private_mb") for item in measured),
                  [(item["engine"], item.get("peak_private_mb"), item.get("gpu_used_mb_min"), item.get("gpu_used_mb_max"),
                    item.get("gpu_mb_attributed_to_this_tree")) for item in measured])


def main(argv=None) -> int:
    run = common.start("optional-engines", argv)
    return run if isinstance(run, int) else run.finish(body)


if __name__ == "__main__":
    raise SystemExit(main())
