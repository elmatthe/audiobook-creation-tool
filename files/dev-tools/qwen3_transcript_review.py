"""Owner review of the six Qwen3 clone reference transcripts (v0.6.7). Dev-only: never shipped, never imported by the app.

A Qwen3 clone is only ever made from an **owner-approved** transcript of its reference recording, bound to that recording's
SHA-256 (``tts.qwen3_runtime.load_transcript``). Since v0.7.0 P03C the app reads only the six approved texts it ships with
(``scripts/tts/data/bundled_clone_transcripts.json``); the local file this tool writes is a maintainer store the app reads
only when it is passed explicitly. Whisper wrote a draft for each recording; this tool makes the owner's check easy and keeps
the approval deliberate:

    python files/dev-tools/qwen3_transcript_review.py build            # write the offline review page
    python files/dev-tools/qwen3_transcript_review.py status           # which clones the app can use (the shipped bundle)
    python files/dev-tools/qwen3_transcript_review.py status --store FILE   # the same question for one local store
    python files/dev-tools/qwen3_transcript_review.py apply FILE        # DRY RUN: check the owner's decisions file
    python files/dev-tools/qwen3_transcript_review.py apply FILE --write   # record them in the local, untracked transcripts file

The page (``files/dev-work/qwen3-eval/transcript-review/review.html``) plays the six ORIGINAL reference recordings (embedded
byte for byte; each is checked against the SHA-256 the app registered), shows each Whisper draft beside an editable field and
lets the owner mark PASS or NEEDS CORRECTION. It downloads one decisions file; ``apply`` turns PASS entries into approved
transcripts. Nothing here approves anything by itself: ``apply`` writes only with ``--write``, only for entries the owner
marked PASS after saying they listened, and never touches the Whisper drafts, the recordings or any tracked file.
"""
from __future__ import annotations

import argparse
import base64
import datetime
import hashlib
import html
import json
import os
import sys
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
DRAFTS = ROOT / "files" / "dev-work" / "qwen3-eval" / "runs" / "qwen3-initial" / "transcripts" / "verified.json"
REVIEW_DIR = ROOT / "files" / "dev-work" / "qwen3-eval" / "transcript-review"
PAGE = REVIEW_DIR / "review.html"
DECISIONS_NAME = "qwen3-transcript-decisions.json"
SCHEMA = 1
PASS, NEEDS_CORRECTION = "PASS", "NEEDS_CORRECTION"


class ReviewError(RuntimeError):
    pass


def _rt():
    sys.path.insert(0, str(SCRIPTS))
    from tts import qwen3_runtime

    return qwen3_runtime


def clone_voices() -> list:
    rt = _rt()
    return [v for v in rt.QWEN3_VOICES if v.kind == rt.KIND_CLONE]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_drafts(path: Path = DRAFTS) -> dict:
    """The Whisper drafts, one per clone, each proven to be about the recording the app registered."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ReviewError(f"the draft transcripts could not be read ({exc})") from exc
    drafts = {}
    for voice in clone_voices():
        entry = data.get(voice.reference_name) if isinstance(data, dict) else None
        if not isinstance(entry, dict) or not isinstance(entry.get("text"), str):
            raise ReviewError(f"there is no draft transcript for {voice.reference_name}")
        if entry.get("wav_sha256") != voice.reference_sha256:
            raise ReviewError(f"the draft for {voice.reference_name} was made for a different recording than the app's")
        drafts[voice.voice_id] = entry["text"]
    return drafts


def review_id(drafts: dict) -> str:
    """Identifies this package: the recordings the app registered plus the draft text shown beside them."""
    rows = [[v.voice_id, v.reference_sha256, drafts[v.voice_id]] for v in clone_voices()]
    return sha256_bytes(json.dumps(rows, ensure_ascii=True).encode("utf-8"))[:16]


def _duration(data: bytes) -> float | None:
    import io

    try:
        with wave.open(io.BytesIO(data)) as handle:
            return handle.getnframes() / handle.getframerate()
    except (wave.Error, EOFError):
        return None


# --------------------------------------------------------------------------- #
# The review page
# --------------------------------------------------------------------------- #
CSS = """
:root{--bg:#fafaf7;--fg:#1d1d1b;--mut:#5d5d58;--card:#fff;--line:#d9d8d2;--acc:#1f5fbf;--ok:#1b7a3a;--bad:#a8431d}
@media (prefers-color-scheme:dark){:root{--bg:#161614;--fg:#ecebe6;--mut:#a3a29b;--card:#1f1f1c;--line:#38372f;--acc:#7aa7ff;--ok:#62c37f;--bad:#f09a73}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.5 system-ui,Segoe UI,sans-serif}
main{max-width:860px;margin:0 auto;padding:24px 16px 80px}h1{font-size:1.5rem;margin:0 0 4px}h2{font-size:1.1rem;margin:0}
.lead{color:var(--mut);margin:0 0 16px}ol{padding-left:1.2rem}li{margin:4px 0}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;margin:16px 0}
.head{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;align-items:baseline}
.mut{color:var(--mut);font-size:.85rem;word-break:break-all}audio{width:100%;margin:10px 0}
label{display:block;font-weight:600;margin:10px 0 4px}textarea{width:100%;min-height:7.5rem;font:inherit;padding:8px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--fg)}
.draft{background:var(--bg);border:1px dashed var(--line);border-radius:6px;padding:8px;white-space:pre-wrap}
.row{display:flex;gap:18px;flex-wrap:wrap;margin-top:10px;align-items:center}.row label{display:inline;font-weight:500;margin:0}
button{font:inherit;padding:8px 14px;border-radius:6px;border:1px solid var(--line);background:var(--card);color:var(--fg);cursor:pointer}
button.primary{background:var(--acc);color:#fff;border-color:var(--acc)}.state{font-weight:600}.state.pass{color:var(--ok)}.state.fix{color:var(--bad)}
.bar{position:sticky;bottom:0;background:var(--bg);border-top:1px solid var(--line);padding:12px 16px;display:flex;gap:12px;align-items:center;flex-wrap:wrap}
output{display:block;white-space:pre-wrap;font:.8rem ui-monospace,Consolas,monospace;margin-top:8px}
"""

JS = """
const DATA = JSON.parse(document.getElementById('data').textContent);
const KEY = 'act-qwen3-review-' + DATA.review_id;
const $ = (s, r = document) => r.querySelector(s);
const cards = [...document.querySelectorAll('.card')];
function stored(){try{return JSON.parse(localStorage.getItem(KEY) || '{}')}catch(e){return {}}}
function save(){try{const s = {};cards.forEach(c => s[c.dataset.voice] = read(c));localStorage.setItem(KEY, JSON.stringify(s))}catch(e){}}
function read(c){const r = c.querySelector('input[type=radio]:checked');
  return {text: $('textarea', c).value, listened: $('.listened', c).checked, decision: r ? r.value : null}}
function refresh(){
  let passed = 0, undecided = 0;
  cards.forEach(c => {const s = read(c), el = $('.state', c), same = s.text.trim() === DATA.drafts[c.dataset.voice].trim();
    if (s.decision === 'PASS') {passed++; el.textContent = 'PASS' + (same ? ' (draft kept as is)' : ' (your corrected text)'); el.className = 'state pass'}
    else if (s.decision === 'NEEDS_CORRECTION') {el.textContent = 'NEEDS CORRECTION'; el.className = 'state fix'}
    else {undecided++; el.textContent = 'not decided'; el.className = 'state'}});
  $('#summary').textContent = passed + ' of 6 marked PASS' + (undecided ? ', ' + undecided + ' not decided yet' : '');
}
function build(){
  const out = {schema: DATA.schema, kind: 'qwen3-transcript-review', review_id: DATA.review_id, decided_at: new Date().toISOString(), decisions: []};
  for (const c of cards){const s = read(c);
    if (s.decision === 'PASS' && !s.listened){alert('Tick "I listened to the whole recording" for ' + c.dataset.label + ' before marking it PASS.');return null}
    if (s.decision === 'PASS' && !s.text.trim()){alert('The transcript for ' + c.dataset.label + ' is empty.');return null}
    out.decisions.push({voice_id: c.dataset.voice, reference_name: c.dataset.ref, wav_sha256: c.dataset.sha, decision: s.decision, listened: s.listened, text: s.text})}
  return out;
}
function show(){const o = build(); if (!o) return null; const t = JSON.stringify(o, null, 2); $('#out').value = t; $('#outwrap').hidden = false; return t}
cards.forEach(c => {const s = stored()[c.dataset.voice];
  if (s){$('textarea', c).value = s.text; $('.listened', c).checked = !!s.listened;
    if (s.decision){const r = c.querySelector('input[value=' + s.decision + ']'); if (r) r.checked = true}}
  c.addEventListener('input', () => {save(); refresh()}); c.addEventListener('change', () => {save(); refresh()});
  $('.reset', c).addEventListener('click', () => {$('textarea', c).value = DATA.drafts[c.dataset.voice]; save(); refresh()})});
$('#download').addEventListener('click', () => {const t = show(); if (!t) return;
  const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([t], {type: 'application/json'})); a.download = DATA.filename;
  document.body.appendChild(a); a.click(); a.remove()});
$('#copy').addEventListener('click', async () => {const t = show(); if (!t) return;
  try {await navigator.clipboard.writeText(t); $('#copied').textContent = 'Copied.'} catch(e) {$('#out').select(); $('#copied').textContent = 'Select all in the box below and copy it.'}});
refresh();
"""


def _card(voice, draft: str, audio: bytes) -> str:
    seconds = _duration(audio)
    length = f"{seconds:.0f} s" if seconds else "length unknown"
    b64 = base64.b64encode(audio).decode("ascii")
    return f"""
<section class="card" data-voice="{html.escape(voice.voice_id)}" data-ref="{html.escape(voice.reference_name)}" data-sha="{voice.reference_sha256}" data-label="{html.escape(voice.label)}">
  <div class="head"><h2>{html.escape(voice.label)}</h2><span class="state">not decided</span></div>
  <div class="mut">Original recording {html.escape(voice.reference_name)}.wav &middot; {length} &middot; SHA-256 {voice.reference_sha256[:16]}&hellip; (checked against the app)</div>
  <audio controls preload="metadata" src="data:audio/wav;base64,{b64}"></audio>
  <label>Whisper's draft (read-only)</label>
  <div class="draft">{html.escape(draft)}</div>
  <label for="t-{html.escape(voice.voice_id)}">Your corrected transcript &mdash; exactly the words spoken</label>
  <textarea id="t-{html.escape(voice.voice_id)}" spellcheck="false">{html.escape(draft)}</textarea>
  <div class="row">
    <button type="button" class="reset">Reset to Whisper's draft</button>
    <span><input type="checkbox" class="listened" id="l-{html.escape(voice.voice_id)}"> <label for="l-{html.escape(voice.voice_id)}">I listened to the whole recording</label></span>
  </div>
  <div class="row">
    <span><input type="radio" name="d-{html.escape(voice.voice_id)}" value="PASS" id="p-{html.escape(voice.voice_id)}"> <label for="p-{html.escape(voice.voice_id)}"><b>PASS</b> &mdash; the text in the box is exactly what is spoken</label></span>
    <span><input type="radio" name="d-{html.escape(voice.voice_id)}" value="NEEDS_CORRECTION" id="n-{html.escape(voice.voice_id)}"> <label for="n-{html.escape(voice.voice_id)}"><b>NEEDS CORRECTION</b> &mdash; not right yet</label></span>
  </div>
</section>"""


def render_page(drafts: dict, audio: dict) -> str:
    rid = review_id(drafts)
    data = {"schema": SCHEMA, "review_id": rid, "filename": DECISIONS_NAME, "drafts": drafts}
    payload = json.dumps(data, ensure_ascii=True).replace("</", "<\\/")
    cards = "".join(_card(v, drafts[v.voice_id], audio[v.voice_id]) for v in clone_voices())
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Qwen3 clone transcript review</title><style>{CSS}</style></head>
<body><main>
<h1>Qwen3 clone transcript review</h1>
<p class="lead">Six original reference recordings, each with Whisper's draft of what is said. Nothing is approved until you mark it PASS and send the decisions file back.</p>
<ol>
  <li>Press play on a recording and read the draft while you listen. Listen to <b>all</b> of it.</li>
  <li>Fix the text in the box until it is <b>exactly</b> the words spoken: names and spellings, numbers, a missing or extra word, a clipped ending. Punctuation can be natural; the words are what matter. Use "Reset" to start over from the draft.</li>
  <li>Tick "I listened to the whole recording", then choose <b>PASS</b> (the box is exactly right) or <b>NEEDS CORRECTION</b> (you are not sure or want to come back).</li>
  <li>When all six are decided, press <b>Download decisions file</b>. It saves <code>{DECISIONS_NAME}</code> (usually to Downloads). Tell me where it is, or press <b>Copy decisions</b> and paste them into the chat. Your work is kept in this browser if you close the page.</li>
</ol>
{cards}
<div id="outwrap" hidden><label for="out">Your decisions (what the download contains)</label><textarea id="out" readonly style="min-height:10rem"></textarea></div>
</main>
<div class="bar"><span id="summary"></span><button type="button" class="primary" id="download">Download decisions file</button><button type="button" id="copy">Copy decisions</button><span id="copied" class="mut"></span></div>
<script type="application/json" id="data">{payload}</script>
<script>{JS}</script>
</body></html>
"""


def build(drafts_path: Path = DRAFTS, out: Path = PAGE) -> Path:
    """Write the review page. The recordings are read, hashed against the app's registration and embedded unchanged."""
    rt = _rt()
    drafts = load_drafts(drafts_path)
    audio = {}
    for voice in clone_voices():
        data = rt.reference_path(voice).read_bytes()
        if sha256_bytes(data) != voice.reference_sha256:
            raise ReviewError(f"{rt.reference_path(voice).name} is not the recording the app registered; refusing to build")
        audio[voice.voice_id] = data
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".tmp")
    tmp.write_text(render_page(drafts, audio), encoding="utf-8", newline="\n")
    os.replace(tmp, out)
    return out


# --------------------------------------------------------------------------- #
# Turning the owner's decisions into approvals
# --------------------------------------------------------------------------- #
def normalize(text: str) -> str:
    return " ".join(str(text).split())


def read_decisions(path: Path, drafts_path: Path = DRAFTS) -> list[dict]:
    """The owner's decisions file, checked against THIS package. Anything off is an error, never a guess."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise ReviewError(f"the decisions file could not be read ({exc})") from exc
    if not isinstance(data, dict) or data.get("kind") != "qwen3-transcript-review" or data.get("schema") != SCHEMA:
        raise ReviewError("this is not a decisions file from the review page")
    if data.get("review_id") != review_id(load_drafts(drafts_path)):
        raise ReviewError("the decisions were made on a different version of the review page; rebuild it and decide again")
    rt = _rt()
    by_id = {v.voice_id: v for v in clone_voices()}
    items = data.get("decisions")
    if not isinstance(items, list) or sorted(i.get("voice_id") for i in items if isinstance(i, dict)) != sorted(by_id):
        raise ReviewError("the decisions must cover exactly the six Qwen3 clone voices, once each")
    for item in items:
        voice = by_id[item["voice_id"]]
        if item.get("wav_sha256") != voice.reference_sha256 or item.get("reference_name") != voice.reference_name:
            raise ReviewError(f"{voice.label}: the decision is for a different recording than the app's")
        if item.get("decision") not in (PASS, NEEDS_CORRECTION, None):
            raise ReviewError(f"{voice.label}: unknown decision {item.get('decision')!r}")
        if not isinstance(item.get("text"), str):
            raise ReviewError(f"{voice.label}: the transcript text is missing")
        if item["decision"] == PASS:
            text = normalize(item["text"])
            if item.get("listened") is not True:
                raise ReviewError(f"{voice.label}: marked PASS without 'I listened to the whole recording'")
            if not text or len(text) > rt.MAX_TRANSCRIPT_CHARS:
                raise ReviewError(f"{voice.label}: an approved transcript must be 1-{rt.MAX_TRANSCRIPT_CHARS} characters")
    return items


def plan_changes(items: list[dict], existing: dict, today: str, *, would: bool = False) -> tuple[dict, list[str]]:
    """The new transcripts file content and a report that never prints a transcript."""
    out = dict(existing)
    report = []
    for item in items:
        voice = next(v for v in clone_voices() if v.voice_id == item["voice_id"])
        decision = item["decision"]
        if decision is None:
            report.append(f"{voice.label}: not decided - left as it was")
            continue
        text = normalize(item["text"])
        out[voice.reference_name] = {
            "text": text, "approved": decision == PASS, "wav_sha256": voice.reference_sha256,
            "text_sha256": sha256_bytes(text.encode("utf-8")),
            **({"approved_by": "owner (review page)", "approved_on": today} if decision == PASS else {})}
        verb = "would be " if would else ""
        result = f"{verb}APPROVED" if decision == PASS else f"{verb}saved as a draft, NOT approved"
        report.append(f"{voice.label}: {result} ({len(text)} characters)")
    return out, report


def apply(decisions: Path, *, write: bool = False, drafts_path: Path = DRAFTS, target: Path | None = None,
          today: str | None = None) -> list[str]:
    """Check the owner's decisions; with ``write=True`` record them in the local, untracked transcripts file."""
    rt = _rt()
    target = Path(target) if target is not None else rt.local_transcripts_path()
    items = read_decisions(decisions, drafts_path)
    existing = {}
    if target.is_file():
        try:
            existing = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ReviewError(f"the existing transcripts file could not be read, so it was not changed ({exc})") from exc
        if not isinstance(existing, dict):
            raise ReviewError("the existing transcripts file is not in the expected shape, so it was not changed")
    updated, report = plan_changes(items, existing, today or datetime.date.today().isoformat(), would=not write)
    if not write:
        return ["DRY RUN - nothing was written. Re-run with --write to record these.", *report]
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file():
        (target.with_name(target.name + ".previous")).write_bytes(target.read_bytes())
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(json.dumps(updated, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    os.replace(tmp, target)
    return [f"Recorded in {target.name} (local and untracked).", *report]


def status(target: Path | None = None) -> list[str]:
    """What the app would use (the shipped bundle), or -- with ``target`` -- what one explicitly chosen local store holds."""
    rt = _rt()
    override = Path(target) if target is not None else None
    lines = []
    for voice in clone_voices():
        t = rt.load_transcript(voice.voice_id, override=override)
        lines.append(f"{voice.label}: {'approved' if t.ok else 'NOT approved - ' + t.reason}")
    return lines


def main(argv: list[str]) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("build")
    p_status = sub.add_parser("status")
    p_status.add_argument("--store", help="check this local transcripts file instead of the shipped bundle")
    p_apply = sub.add_parser("apply")
    p_apply.add_argument("decisions")
    p_apply.add_argument("--write", action="store_true", help="record the decisions (default is a dry run)")
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            print(f"Review page: {build()}")
        elif args.command == "status":
            print("\n".join(status(Path(args.store) if args.store else None)))
        else:
            print("\n".join(apply(Path(args.decisions), write=args.write)))
    except ReviewError as exc:
        print("ERROR:", exc)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
