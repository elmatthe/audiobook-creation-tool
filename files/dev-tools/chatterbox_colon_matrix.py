"""Plan 01B checkpoint A6: the Chatterbox colon text-level behaviour matrix. Development only; no audio, no network.

For every colon category the plan names, each case is traced through the production path with speech preparation
``off`` and ``v1`` (the A5 bundled mode table, no user files):

  source -> prepared text (``prepare(..., CHATTERBOX)``) -> chunks (``split_for_chatterbox``)
         -> generate() inputs (``split_at_prose_colon``; >1 input = the 75 ms PCM gap is inserted)
         -> tokenizer input under the production patch (``_structural_colon_punc_norm``)
         -> tokenizer input under the pinned wheel's own ``chatterbox.tts_turbo.punc_norm`` (what removing the patch gives)

and, when the pinned tokenizer files are in the in-tree model cache, the token ids of both tokenizer inputs. The
result answers A6 criterion 1 mechanically: which colons still reach ``generate()`` and would be corrupted without
the patch, and which prose colons rely on the assembly-level pause.

Run from the repository root with the root ``.venv``:  python files/dev-tools/chatterbox_colon_matrix.py
Writes ``files/dev-work/speech-ab/a6/text-matrix.json`` and ``text-matrix.md``.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from tts import chatterbox_synth as cbx  # noqa: E402
from tts.quality_corpus import DIFFICULT_SHORT  # noqa: E402
from tts.speech.pipeline import SETTING_OFF, SETTING_V1, build_snapshot, prepare  # noqa: E402
from tts.speech.profiles import CHATTERBOX as ROUTE  # noqa: E402

OUT = REPO_ROOT / "files" / "dev-work" / "speech-ab" / "a6"
TOKENIZER_DIR_GLOB = "files/runtime-data/models/huggingface/hub/models--ResembleAI--chatterbox-turbo/snapshots/*"

#: (category, case id, source). Sources are short sentences; DIFFICULT_SHORT is the canonical fixture, unabridged.
CASES = [
    ("time", "time-cued", "The ferry left at 6:45 p.m. and docked at 7:15 a.m."),
    ("time", "time-cue-word", "It was 6:45 when the radio crackled."),
    ("time", "time-cued-1:30", "Meet me at 1:30 by the gate."),
    ("time", "time-ambiguous-1:30", "His best lap was 1:30 flat."),
    ("time", "time-ambiguous-3:15", "The score stood at 3:15 after the break."),
    ("time", "time-hms", "The recording ran 01:02:03 in total."),
    ("ratio", "ratio-cued", "The odds were 3:1 against them, a ratio of 10:9 at best."),
    ("ratio", "ratio-bare", "They mixed it 2:1 with water."),
    ("prose", "prose-heading", "Chapter 3008: Beautiful Dream.\n\nThe night was calm."),
    ("prose", "prose-sentence", "She had one rule: never trust the first reading."),
    ("prose", "prose-dialogue", "He said: \"Wait for me.\" She answered: \"No.\""),
    ("prose", "prose-end-of-string", "There was only one thing left to say:"),
    ("prose", "prose-list", "Bring three things: rope, salt and a lamp."),
    ("url", "url-https", "She read it at https://example.com/lighthouse-log before bed."),
    ("url", "url-ftp", "The archive is at ftp://files.example.org/logs today."),
    ("url", "url-mailto", "Write to mailto:keeper@example.com for a copy."),
    ("path", "path-windows", "The file is saved in C:\\Users\\keeper\\log.txt on the old laptop."),
    ("ambiguous", "scripture", "The verse was John 3:16, read aloud twice."),
    ("ambiguous", "section-ref", "See Section 3.5 and clause 4:2 of the charter."),
    ("structure", "metadata", "Title: The Harbor Light\nAuthor: A. Keeper\n\n# Chapter 1: Fog\n\nThe light turned."),
    ("control", "colon-free", "The beam\u2019s rotation slowed\u2026 \u201cAre you coming?\u201d \u2014 she called \u2013 twice."),
    ("control", "colon-free-numbers", "Mr. Okafor counted 2.5 degrees and 1,200 boats in 1999."),
    ("fixture", "difficult-short", DIFFICULT_SHORT.text),
]


def _tokenizer():
    """The pinned model's own tokenizer, offline, or None when the files are absent."""
    snapshots = sorted(REPO_ROOT.glob(TOKENIZER_DIR_GLOB))
    if not snapshots:
        return None
    try:
        from transformers import AutoTokenizer

        return AutoTokenizer.from_pretrained(str(snapshots[-1]), local_files_only=True)
    except Exception as exc:  # evidence tool: report, never fail the matrix
        print(f"tokenizer unavailable: {type(exc).__name__}: {exc}")
        return None


def trace(source: str, snapshot, wheel_punc_norm, tokenizer) -> dict:
    prepared = prepare(source, snapshot, ROUTE)
    chunks = cbx.split_for_chatterbox(prepared.text)
    calls = []
    for chunk in chunks:
        segments = cbx.split_at_prose_colon(chunk)
        for segment in segments:
            patched = cbx._structural_colon_punc_norm(segment)
            wheel = wheel_punc_norm(segment)
            row = {"generate_input": segment, "patched_tokenizer_input": patched, "wheel_tokenizer_input": wheel,
                   "colons_reaching_generate": segment.count(":"), "colons_reaching_tokenizer_patched": patched.count(":"),
                   "colons_reaching_tokenizer_wheel": wheel.count(":"), "patch_changes_tokenizer_input": patched != wheel}
            if tokenizer is not None:
                row["patched_ids"] = tokenizer(patched).input_ids
                row["wheel_ids"] = tokenizer(wheel).input_ids
            calls.append(row)
    pauses = sum(len(cbx.split_at_prose_colon(c)) - 1 for c in chunks)
    return {"prepared": prepared.text, "edits": prepared.details(), "chunks": len(chunks), "generate_calls": len(calls),
            "colon_pauses_75ms": pauses, "calls": calls,
            "structural_colons_needing_patch": sum(c["colons_reaching_tokenizer_patched"] for c in calls),
            "patch_changes_tokenizer_input": any(c["patch_changes_tokenizer_input"] for c in calls)}


def build() -> dict:
    from chatterbox.tts_turbo import punc_norm as wheel_punc_norm

    tokenizer = _tokenizer()
    snapshots = {SETTING_OFF: build_snapshot(SETTING_OFF, user_dir=None), SETTING_V1: build_snapshot(SETTING_V1, user_dir=None)}
    rows = []
    for category, case_id, source in CASES:
        row = {"category": category, "id": case_id, "source": source,
               "source_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest()}
        for setting, snapshot in snapshots.items():
            row[setting] = trace(source, snapshot, wheel_punc_norm, tokenizer)
        rows.append(row)
    return {"tool": "files/dev-tools/chatterbox_colon_matrix.py", "route": ROUTE, "tokenizer_ids": tokenizer is not None,
            "colon_pause_ms": cbx.COLON_PAUSE_MS, "rows": rows}


def _cell(text: str) -> str:
    return "`" + text.replace("|", "\\|").replace("\n", "\u23ce").replace("`", "'") + "`"


def markdown(matrix: dict) -> str:
    lines = ["# A6 Chatterbox colon text matrix", "",
             "Generated by `files/dev-tools/chatterbox_colon_matrix.py` (no audio). Per mode: the text that reaches `generate()` "
             "(joined with ` || ` where the prose-colon split makes several calls), the tokenizer input with the production "
             "patch, and the tokenizer input the pinned wheel gives without it. **Kept** = colons the patch keeps out of the "
             "wheel's blanket `:` -> `,`; **pauses** = 75 ms PCM gaps inserted.", ""]
    for row in matrix["rows"]:
        if row["id"] == "difficult-short":
            continue
        lines += [f"## {row['category']} / {row['id']}", "", f"Source: {_cell(row['source'])}", "",
                  "| Mode | Reaches generate() | Tokenizer input (patched) | Tokenizer input (wheel, no patch) | Calls | Pauses | Kept |",
                  "|---|---|---|---|---|---|---|"]
        for mode in (SETTING_OFF, SETTING_V1):
            t = row[mode]
            lines.append("| {} | {} | {} | {} | {} | {} | {} |".format(
                mode, _cell(" || ".join(c["generate_input"] for c in t["calls"])),
                _cell(" || ".join(c["patched_tokenizer_input"] for c in t["calls"])),
                _cell(" || ".join(c["wheel_tokenizer_input"] for c in t["calls"])),
                t["generate_calls"], t["colon_pauses_75ms"], t["structural_colons_needing_patch"]))
        lines.append("")
    ds = next(r for r in matrix["rows"] if r["id"] == "difficult-short")
    lines += ["## fixture / DIFFICULT_SHORT (unabridged)", ""]
    for mode in (SETTING_OFF, SETTING_V1):
        t = ds[mode]
        lines += [f"**{mode}:** {t['chunks']} chunks, {t['generate_calls']} generate() calls, {t['colon_pauses_75ms']} colon pauses, "
                  f"{t['structural_colons_needing_patch']} colons kept by the patch; edits: {'; '.join(t['edits']) or 'none'}", ""]
        for c in t["calls"]:
            if c["patch_changes_tokenizer_input"]:
                lines.append(f"- patched {_cell(c['patched_tokenizer_input'])}")
                lines.append(f"  wheel   {_cell(c['wheel_tokenizer_input'])}")
        lines.append("")
    return "\n".join(lines) + "\n"


def main() -> int:
    matrix = build()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "text-matrix.json").write_text(json.dumps(matrix, indent=1, ensure_ascii=False), encoding="utf-8")
    (OUT / "text-matrix.md").write_text(markdown(matrix), encoding="utf-8")
    for row in matrix["rows"]:
        print(f"{row['id']:22} " + "  ".join(
            f"{m}: calls={row[m]['generate_calls']} pauses={row[m]['colon_pauses_75ms']} kept={row[m]['structural_colons_needing_patch']}"
            for m in (SETTING_OFF, SETTING_V1)))
    print("tokenizer ids:", matrix["tokenizer_ids"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
