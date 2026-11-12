"""The ``edge-low-memory`` qualification: REAL Microsoft Edge speech through the real TTS panel (v0.7.2 Phase 8).

    verify.py --mode qualification --scenario edge-low-memory --network online-edge

The routine journeys replay recorded speech at the service boundary, so they say nothing about the real service. This does: every
case is a contained process (``panel_run.py``) driving the real panel, worker pool, requests, assembly, encoder and publication
against Microsoft's service. It needs the network, so it runs only when the gate was given ``--network online-edge``; without that
grant it is BLOCKED and sends nothing.

Cases, each judged from what was requested, what was published and when:

  overlap-8        eight files added directly, eight workers: all eight really in flight at once, each narrated whole.
  folder-mixed     a folder of text files and real PDFs (with printed page numbers) under eight workers.
  cancel-active    Cancel while files are being synthesized: it ends promptly, no request starts afterwards, nothing is
                   published afterwards, and whatever was published is a whole narration.
  cancel-finalize  Cancel as the one file's finalization (assembly) begins: nothing is published and nothing is left reserved.
  pause-then-cancel  Pause lets the files in flight finish and starts no new file; a paused run then cancels at once.
  low-memory       the same eight-file queue under a real per-process memory limit: it reaches an end, never hangs, publishes
                   only whole files, and leaves no assembly reservation behind.

The texts are short and original, and the whole scenario sends a few hundred short requests: enough to prove the behaviour, small
beside one audiobook. It is not a load test of the service, and a service refusal is reported as BLOCKED, not as a product failure.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import common  # noqa: E402

VOICE = "Edge Male - Steffan (en-US)"
#: The service saying no, as distinct from the application failing: these make the scenario BLOCKED.
SERVICE_REFUSALS = ("403", "429", "NoAudioReceived", "getaddrinfo", "Cannot connect", "timed out", "WSServerHandshakeError", "503")
SENTENCES = (
    "The harbour was quiet when the first boat went out.",
    "Nobody on the quay looked up from mending nets.",
    "A gull stood on the bollard and watched the tide turn.",
    "By seven the fog had lifted from the far shore.",
    "The baker's boy ran down the steps with two warm loaves.",
    "Somebody had left a ladder against the chandler's wall.",
    "The church clock was four minutes slow, as it had always been.",
    "Out past the point the water changed from grey to green.",
    "An old dog slept in the doorway of the sail loft.",
    "The ferry sounded its horn twice and backed away from the pier.",
)


def text_for(index: int, sentences: int) -> str:
    """A short original text, different for every file, in paragraphs of five sentences."""
    lines = [f"Part {index + 1}."]
    body = [SENTENCES[(index * 3 + n) % len(SENTENCES)].replace("The harbour", f"Harbour number {index + 1}") for n in range(sentences)]
    for start in range(0, sentences, 5):
        lines.append(" ".join(body[start:start + 5]))
    return "\n\n".join(lines) + "\n"


def write_texts(folder: Path, count: int, sentences: int) -> list[str]:
    folder.mkdir(parents=True)
    paths = []
    for index in range(count):
        path = folder / f"Harbour {index + 1:02d}.txt"
        path.write_text(text_for(index, sentences), encoding="utf-8")
        paths.append(str(path))
    return paths


def write_pdf(path: Path, index: int) -> None:
    """A real two-page PDF whose sentence runs across the page break, with a printed page number under each page."""
    import fitz

    document = fitz.open()
    words = text_for(index, 6).split("\n\n")[1].split(" ")
    half = len(words) // 2
    for number, part in enumerate((words[:half], words[half:]), start=1):
        sheet = document.new_page(width=432, height=648)
        for row in range(0, len(part), 8):
            sheet.insert_text((54, 90 + row // 8 * 18), " ".join(part[row:row + 8]), fontname="helv", fontsize=11)
        sheet.insert_text((210, 610), str(40 + number), fontname="helv", fontsize=9)
    document.save(path)
    document.close()


def overlap(intervals: list[tuple[float, float]]) -> int:
    events = sorted([(start, 1) for start, _end in intervals] + [(end, -1) for _start, end in intervals], key=lambda item: (item[0], item[1]))
    live = best = 0
    for _at, change in events:
        live += change
        best = max(best, live)
    return best


def whole(audio: dict, characters: int) -> list[str]:
    """Why a published MP3 is not a whole narration of a text this long; empty when it is."""
    problems = []
    stream = (audio["probe"].get("streams") or [{}])[0]
    if stream.get("codec_name") != "mp3" or audio["decode_exit"] != 0 or audio["decode_errors"]:
        problems.append(f"does not decode cleanly: {audio['decode_errors'][:80]}")
    if not characters / 30 <= audio["decoded_seconds"] <= characters / 4:
        problems.append(f"{audio['decoded_seconds']} s for {characters} characters")
    if audio.get("voiced_fraction", 0) < 0.35 or (audio.get("longest_inner_silence_s") or 0) > 4.0:
        problems.append(f"speech {audio.get('voiced_fraction')} of the time, longest silence {audio.get('longest_inner_silence_s')} s")
    if (audio.get("trailing_silence_s") or 0) > 2.5 or audio.get("last_frame_dbfs", 0) > -30:
        problems.append(f"ending: {audio.get('trailing_silence_s')} s of silence, last frame {audio.get('last_frame_dbfs')} dBFS")
    return problems


class Edge:
    def __init__(self, run: common.Scenario) -> None:
        self.run = run
        self.sources = run.root / "sources"

    def case(self, label: str, **case) -> dict | None:
        path = self.run.root / "cases" / f"{label}.json"
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps({"label": label, "voice": VOICE, "online": True, "observe_edge": True, "timeout": 900, **case}),
                        encoding="utf-8")
        record = self.run.child(label, HERE / "panel_run.py", ["--case", str(path)], timeout=1200)
        result = record["result"]
        if not self.run.check(f"{label}: the run reached an end and left a record", result is not None and result["finished"],
                              record.get("no_result") or f"exit {record['exit']}, {record['ended']} after {record['seconds']} s"):
            return None
        refused = [r["error"] for r in result["requests"] if r.get("error") and any(mark in r["error"] for mark in SERVICE_REFUSALS)]
        every = [r for r in result["requests"] if "end" in r]
        if every and len(refused) == len(every):
            raise common.Blocked(f"Microsoft's service answered none of {len(every)} requests in {label}: {refused[0][:200]}")
        self.run.check(f"{label}: the run's own folders were its only output, source files untouched",
                       result["sources_unchanged"] and not result["leftovers_in_output"], result["leftovers_in_output"][:5])
        self.run.check(f"{label}: nothing was published after the run said it had ended",
                       result["published_at_settle"] == result["published_at_end"], [result["published_at_settle"], result["published_at_end"]])
        self.run.check(f"{label}: no assembly reservation and no temporary work was left behind",
                       not result["assembly_reservation_after"] and not result["temp_left"],
                       {"reservation": result["assembly_reservation_after"], "temp": result["temp_left"][:6]})
        return result

    def whole_outputs(self, label: str, result: dict, characters: int, expected: int | None = None) -> None:
        problems = {audio["name"]: found for audio in result["outputs"] if (found := whole(audio, characters))}
        self.run.check(f"{label}: every published MP3 is a whole narration that ends properly", not problems
                       and (expected is None or len(result["outputs"]) == expected),
                       problems or f"{len(result['outputs'])} file(s)", outputs=[{k: a.get(k) for k in ("name", "sha256", "decoded_seconds")}
                                                                                 for a in result["outputs"]])

    # ------------------------------------------------------------------ the cases
    def overlap_8(self) -> None:
        files = write_texts(self.sources / "overlap", 8, 6)
        result = self.case("overlap-8", direct=files, workers=8)
        if result is None:
            return
        run = self.run
        run.check("overlap-8: all eight files were narrated", result["state"] == "SUCCEEDED" and result["succeeded"] == 8 and not result["failed"],
                  {key: result[key] for key in ("state", "succeeded", "failed")})
        peak = overlap([(f["start"], f["end"]) for f in result["files"] if "end" in f])
        run.check("overlap-8: eight files were really in flight at once", peak == 8, f"peak {peak}; {result['worker_lines'][:2]}")
        run.check("overlap-8: every request was answered", all(r.get("ok") for r in result["requests"]) and len(result["requests"]) >= 8,
                  f"{len(result['requests'])} requests, {sum(1 for r in result['requests'] if not r.get('ok'))} not answered")
        self.whole_outputs("overlap-8", result, len(text_for(0, 6)), 8)

    def folder_mixed(self) -> None:
        folder = self.sources / "mixed"
        write_texts(folder, 4, 6)
        for index in (4, 5):
            write_pdf(folder / f"Harbour {index + 1:02d}.pdf", index)
        result = self.case("folder-mixed", folders=[str(folder)], workers=8)
        if result is None:
            return
        run = self.run
        run.check("folder-mixed: four text files and two PDFs were all narrated", result["state"] == "SUCCEEDED" and result["succeeded"] == 6
                  and not result["failed"], {key: result[key] for key in ("state", "succeeded", "failed")})
        peak = overlap([(f["start"], f["end"]) for f in result["files"] if "end" in f])
        run.check("folder-mixed: the folder's files ran side by side", peak >= 4, f"peak {peak}")
        # A PDF's text is its one paragraph (no "Part N." heading line), so it is a little shorter than a text file's.
        problems = {audio["name"]: found for audio in result["outputs"]
                    if (found := whole(audio, len(text_for(0, 6)) - (12 if audio["name"].lower().startswith(("harbour 05", "harbour 06")) else 0)))}
        names = " ".join(audio["name"] for audio in result["outputs"])
        run.check("folder-mixed: both PDFs were narrated among them", "Harbour 05" in names and "Harbour 06" in names, names[:200])
        run.check("folder-mixed: every published MP3 is a whole narration that ends properly", not problems and len(result["outputs"]) == 6,
                  problems or "6 files")

    def cancel_active(self) -> None:
        files = write_texts(self.sources / "cancel", 8, 40)
        result = self.case("cancel-active", direct=files, workers=8, action={"do": "cancel", "when": {"after_requests": 12}})
        if result is None:
            return
        run = self.run
        action = (result["actions"] or [None])[0]
        if not run.check("cancel-active: Cancel was pressed while files were being synthesized", action is not None
                         and any(f["start"] < action["at"] < f.get("end", 1e9) for f in result["files"]), action):
            return
        took = result["settled_at"] - action["at"]
        run.check("cancel-active: the run ended as cancelled, promptly", result["state"] == "CANCELLED" and result["cancelled"] and took <= 10.0,
                  f"{result['state']} {took:.2f} s after Cancel", seconds_to_stop=round(took, 2))
        late = [r for r in result["requests"] if r["start"] > action["at"] + 0.3]
        run.check("cancel-active: no request was started after Cancel (no retry, no fallback)", not late,
                  f"{len(late)} of {len(result['requests'])} requests began later than 0.3 s after Cancel")
        late_files = [f for f in result["files"] if f["start"] > action["at"] + 0.3]
        run.check("cancel-active: no file was started after Cancel", not late_files, late_files[:3])
        run.check("cancel-active: nothing was published after Cancel", result["published_at_end"] == action["published_at_action"],
                  [action["published_at_action"], result["published_at_end"]])
        run.check("cancel-active: far fewer requests were sent than the queue holds", len(result["requests"]) < 8 * 40 // 2,
                  f"{len(result['requests'])} of about {8 * 41}")
        self.whole_outputs("cancel-active", result, len(text_for(0, 40)))

    def cancel_finalize(self) -> None:
        files = write_texts(self.sources / "finalize", 1, 30)
        result = self.case("cancel-finalize", direct=files, workers=1, action={"do": "cancel", "when": {"after_assemblies": 1}})
        if result is None:
            return
        run = self.run
        action = (result["actions"] or [None])[0]
        if not run.check("cancel-finalize: Cancel was pressed as finalization began", action is not None and bool(result["assemblies"])
                         and all(r.get("ok") for r in result["requests"]), {"action": action, "assemblies": result["assemblies"][:2]}):
            return
        took = result["settled_at"] - action["at"]
        run.check("cancel-finalize: the run ended as cancelled, promptly", result["state"] == "CANCELLED" and took <= 10.0,
                  f"{result['state']} {took:.2f} s after Cancel", seconds_to_stop=round(took, 2))
        run.check("cancel-finalize: the narration that was being finished was not published", result["published_at_end"] == [],
                  result["published_at_end"])
        run.check("cancel-finalize: no request followed", not [r for r in result["requests"] if r["start"] > action["at"]], "")

    def pause_then_cancel(self) -> None:
        files = write_texts(self.sources / "pause", 6, 8)
        result = self.case("pause-then-cancel", direct=files, workers=2,
                           action={"do": "pause", "when": {"after_requests": 3}, "hold_seconds": 8})
        if result is None:
            return
        run = self.run
        pause = next((a for a in result["actions"] if a["action"] == "pause"), None)
        cancel = next((a for a in result["actions"] if a["action"] == "cancel-while-paused"), None)
        if not run.check("pause-then-cancel: Pause was pressed during synthesis, and the paused run was then cancelled",
                         pause is not None and cancel is not None, result["actions"]):
            return
        in_flight = [f for f in result["files"] if f["start"] < pause["at"] < f.get("end", 1e9)]
        run.check("pause-then-cancel: the files in flight at Pause were finished, not abandoned", bool(in_flight)
                  and all(str(f.get("outcome")) not in ("None",) and "raised" not in str(f.get("outcome")) for f in in_flight),
                  [(f["source"], f.get("outcome")) for f in in_flight])
        started_late = [f for f in result["files"] if pause["at"] + 0.3 < f["start"]]
        run.check("pause-then-cancel: no new file was started after Pause", not started_late, [(f["source"], f["start"]) for f in started_late])
        requests_during_hold = [r for r in result["requests"] if r["start"] > max(f.get("end", 0) for f in in_flight) + 0.3] if in_flight else []
        run.check("pause-then-cancel: once those files had finished, no request was made while paused", not requests_during_hold,
                  len(requests_during_hold))
        took = result["settled_at"] - cancel["at"]
        run.check("pause-then-cancel: a paused run cancels at once", result["state"] == "CANCELLED" and took <= 5.0, f"{took:.2f} s",
                  seconds_to_stop=round(took, 2))
        run.check("pause-then-cancel: fewer files were narrated than were queued", 0 < len(result["outputs"]) < 6, len(result["outputs"]))
        run.check("pause-then-cancel: nothing was published after the cancel", result["published_at_end"] == cancel["published_at_action"],
                  [cancel["published_at_action"], result["published_at_end"]])
        self.whole_outputs("pause-then-cancel", result, len(text_for(0, 8)))

    def low_memory(self) -> None:
        files = write_texts(self.sources / "lowmem", 8, 25)
        result = self.case("low-memory", direct=files, workers=8, job_memory_headroom_mb=96, timeout=900)
        if result is None:
            return
        run = self.run
        limit = result["memory_limit"] or {}
        run.check("low-memory: a real per-process memory limit was in force", bool(limit.get("applied")), limit)
        run.check("low-memory: the run reached a proper end under it", result["state"] in ("SUCCEEDED", "COMPLETED_WITH_FAILURES", "FAILED"),
                  {key: result[key] for key in ("state", "succeeded", "failed")}, peak_private_mb=result["sampler"]["peak_private_mb"])
        run.check("low-memory: every file is accounted for, as narrated or as failed", (result["succeeded"] or 0) + (result["failed"] or 0) == 8,
                  {key: result[key] for key in ("succeeded", "failed")})
        import re

        effective = [int(n) for line in result["worker_lines"] for n in re.findall(r"Effective workers: (\d+)", line)]
        felt = (bool(effective) and effective[0] < 8 and any("memory" in line.lower() for line in result["worker_lines"])) \
            or (result["failed"] or 0) > 0
        run.check("low-memory: the limit was really felt (fewer workers because of memory, or a file that failed for it)", felt,
                  result["worker_lines"][:3])
        run.check("low-memory: the process stayed inside its limit", result["sampler"]["peak_private_mb"] <= (limit.get("limit_mb") or 0) + 64,
                  f"peak {result['sampler']['peak_private_mb']} MB of {limit.get('limit_mb')} MB")
        run.check("low-memory: a file that failed says why", (result["failed"] or 0) == 0 or bool(result["failure_messages"]),
                  result["failure_messages"][:3])
        self.whole_outputs("low-memory", result, len(text_for(0, 25)), result["succeeded"])
        run.log(f"low-memory: memory lines {result['memory_lines'][:4]}; worker lines {result['worker_lines'][:3]}")


def body(run: common.Scenario) -> None:
    if run.args.network != "online-edge":
        raise common.Blocked("this scenario sends real requests to Microsoft's speech service and was not given --network online-edge; "
                             "nothing was sent")
    if not (common.SCRIPTS / "tts" / "epub2tts_gui.py").is_file():
        raise common.Blocked("the application's TTS code is not here")
    identity = run.identity(voice=VOICE)
    run.log(f"identity: HEAD {identity['head']}, code {identity['code_digest'][:12]}")
    edge = Edge(run)
    # --smoke rehearses the same cases; only the verdict differs (SMOKE, never PASS).
    for case in (edge.overlap_8, edge.folder_mixed, edge.cancel_active, edge.cancel_finalize, edge.pause_then_cancel, edge.low_memory):
        case()


def main(argv=None) -> int:
    run = common.start("edge-low-memory", argv, network=("online-edge",))
    return run if isinstance(run, int) else run.finish(body)


if __name__ == "__main__":
    raise SystemExit(main())
