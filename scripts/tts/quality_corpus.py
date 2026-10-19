"""Purpose-built, copyright-safe QA corpus for v0.6.5 TTS quality work (plan Section 8).

Every passage here is original text written for this harness — never copied from
another source — so it carries no licensing or attribution concern and can be
freely regenerated, extended, or shared as evidence. Nothing in this module
performs synthesis; it only supplies text. The dev-only ``--quality-suite``
sample generator is the consumer.

Corpus identity (P12): :func:`corpus_identity` hashes every item's text so a
manifest can record exactly which corpus version produced a given sample,
without needing to track full audio output in the repository.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True)
class CorpusItem:
    """One named passage plus what it exists to stress."""

    name: str
    purpose: str
    text: str

    @property
    def char_count(self) -> int:
        return len(self.text)


# --------------------------------------------------------------------------- #
# 1. Short difficult-text baseline — every retained voice reads this one.
# --------------------------------------------------------------------------- #
# Deliberately dense: it packs the plan's Section 7 false-boundary list (
# Mr./Mrs./Dr./Prof., e.g./i.e./vs., initials, a decimal, times, a ratio, a
# URL, an ellipsis, quoted dialogue, a closing quote after punctuation, and a
# parenthetical) into one short, natural-sounding paragraph rather than a
# checklist, so the listening pass hears them in context.
DIFFICULT_SHORT = CorpusItem(
    name="difficult_short",
    purpose="Short per-voice baseline; every false-boundary case from Section 7.",
    text=(
        "Dr. Elena Marsh checked the logbook one last time. It was 6:45 when "
        "J. R. Alvarez, the harbor master, radioed that the ferry would not "
        "arrive before 7:15. \"I still don't believe it,\" she murmured, "
        "unfolding the note (found wedged beneath the lamp-room door) one "
        "more time. The ratio of questions to answers in it felt close to "
        "3:1, and the beam's rotation had slowed by 2.5 degrees per second, "
        "a change no one could explain. Mr. Okafor and Mrs. Yates both "
        "blamed the storm; Prof. Whitfield's theory, i.e. that the light "
        "had never truly gone dark, kept circling back to her, e.g. it had "
        "simply gone unwatched, vs. gone out entirely. She had read the "
        "full report at https://example.com/lighthouse-log before setting "
        "it aside... the light flickered once, then steadied. \"Are you "
        "coming up, or not?\" Mrs. Yates called from the stairs below."
    ),
)

# --------------------------------------------------------------------------- #
# 2. Structural/join stress — deliberately crosses each backend's chunk limit
#    with no convenient paragraph break near the boundary, forcing a
#    mid-paragraph continuation split rather than a natural sentence pause.
# --------------------------------------------------------------------------- #
STRUCTURAL_STRESS_CHATTERBOX = CorpusItem(
    name="structural_stress_chatterbox",
    purpose="Crosses Chatterbox's 300-char chunk ceiling with no paragraph break.",
    text=(
        "The wind came in off the strait before dawn, rattling the shutters "
        "twice, then three times, before the keeper finally rose to check "
        "the lamp. She climbed the spiral stairs without a lantern, "
        "trusting the count of steps she had learned as a girl, and at the "
        "top she found the glass fogged over from the cold snap that had "
        "settled in overnight. Below, the harbor lights blinked on one by "
        "one, small and steady, as the first boats pushed out past the "
        "breakwater into water still dark as slate."
    ),
)

STRUCTURAL_STRESS_KOKORO_EDGE = CorpusItem(
    name="structural_stress_kokoro_edge",
    purpose="Crosses Kokoro/Edge's ~3,000-char chunk ceiling; paragraph breaks "
            "present but positioned away from the limit.",
    text=(
        "The keeper's log for that stretch of coast went back four "
        "generations, and every entry before this one agreed on the same "
        "plain fact: the light turned, and it did not stop turning. Elena "
        "had read most of the older volumes twice, first as a child bored "
        "on a rainy afternoon and later as an apprentice looking for "
        "anything that resembled the fault she now faced. Neither reading "
        "had prepared her for a night when the beam simply slowed, as "
        "though something heavy had settled onto the mechanism and no one "
        "had noticed the extra weight.\n\n"
        "She traced the drive shaft down from the lamp room to the "
        "clockwork room below, running a bare hand along the housing the "
        "way her predecessor had taught her, feeling for heat, for grit, "
        "for anything that did not belong. The gears turned true under her "
        "fingers. The mercury bath beneath them sat level and undisturbed. "
        "Whatever had reached into the rotation, it had left no mark "
        "anyone could touch, and that bothered her more than a broken part "
        "ever could have, because a broken part could at least be "
        "replaced.\n\n"
        "Outside, the fog had thickened enough to swallow the breakwater "
        "entirely, and twice she thought she heard an engine idling "
        "somewhere past the rocks, closer than any boat had business being "
        "on a night like this. She told herself it was the wind finding a "
        "gap in the old stone, the same trick it played every autumn, and "
        "she almost believed it. The log open on the desk behind her still "
        "waited for an entry, and for the first time in eleven years on "
        "this rock, she did not know what honest sentence to write in "
        "it.\n\n"
        "By the time the sun came up gray and thin over the water, the "
        "beam had returned to its ordinary, indifferent rhythm, as if "
        "nothing at all had happened, and the only evidence that anything "
        "had was the half page of careful notes in Elena's own hand and "
        "the fading, unreasonable certainty that something out past the "
        "breakwater had been watching the light exactly as closely as she "
        "had.\n\n"
        "She telephoned no one that morning, though the harbor master's "
        "office kept regular hours and would gladly have taken her call. "
        "Instead she sat with the log open in front of her and read back "
        "through the last decade of entries, page by careful page, looking "
        "for any earlier keeper who might have noticed the same half "
        "second and simply never thought it worth writing down. She found "
        "nothing conclusive, only a handful of oddly terse nights scattered "
        "across the years, each one otherwise unremarkable, each one "
        "ending its entry a little sooner than the surrounding pages did, "
        "as though whoever wrote it had decided partway through that some "
        "things were better left for the next keeper to rediscover on "
        "their own rather than inherit secondhand.\n\n"
        "She spent the rest of that morning doing the ordinary work a "
        "keeper does after a strange night: refilling the log, checking "
        "the weather line for anything worth flagging, and resisting the "
        "urge to call the harbor master's office before she had a single "
        "fact worth reporting. A half-remembered engine and a beam that "
        "occasionally hesitated were not, on their own, the kind of thing "
        "that justified pulling anyone else out to a rock in heavy fog, "
        "and she had learned the hard way, early in her first winter, that "
        "a keeper who cried wolf even once earned a reputation that "
        "outlasted every later correction.\n\n"
        "So she watched, and she waited, and she kept the kind of careful, "
        "unglamorous notes that never made it into any story anyone told "
        "about lighthouse keepers, and that was exactly how, three nights "
        "later, she finally caught the fault behaving long enough to trace "
        "it to its source."
    ),
)

# --------------------------------------------------------------------------- #
# 3. Sustained narration / longer stress — one continuous original story.
#    SUSTAINED_NARRATION is a clean paragraph-aligned prefix of the same
#    text LONGER_STRESS uses in full, so the two are directly comparable
#    rather than unrelated passages (computed below, not hand-sliced).
# --------------------------------------------------------------------------- #
_STORY_PARAGRAPHS: tuple[str, ...] = (
    "Elena Marsh had kept the light on Gannet Rock for eleven years, and in "
    "that time she had learned that the sea rewarded patience and punished "
    "assumption in roughly equal measure. The lighthouse itself was older "
    "than the town it served, older than the harbor master's office, older "
    "than any living memory of who had first decided that this particular "
    "outcropping of granite needed a warning fixed to the top of it. She "
    "had inherited the post from a keeper named Halloran, who had inherited "
    "it from someone whose name nobody quite remembered, and she had spent "
    "her first winter alone learning every creak the tower made so that a "
    "new one would announce itself the moment it began.",

    "That was why the change in the beam's rhythm troubled her so much more "
    "than the storms ever had. A storm was loud and honest about what it "
    "wanted. This was quiet, a fraction of a second added to each rotation, "
    "so small that the harbor master's office had not even flagged it in "
    "their weekly log, and so consistent that Elena was certain it was not "
    "an accident of weather or wear. Something was slowing the light on "
    "purpose, or something was slowing it by a process she did not yet "
    "understand, and either possibility kept her awake long after the "
    "practical parts of her mind insisted she had already done everything "
    "useful that a sleepless night could accomplish.",

    "She began, as her training insisted she should, with the mechanism "
    "itself. The clockwork drive beneath the lamp room turned on a bath of "
    "mercury that had not been disturbed, by her own hand, in three years. "
    "She checked the weights, the cables, the small brass regulator that "
    "had needed replacing exactly once in living memory. Everything moved "
    "as it always had, smooth and cool and entirely uninterested in "
    "explaining itself. If the fault lived in the machine, it was hiding "
    "somewhere she had not yet learned to look, and Gannet Rock did not "
    "reward the assumption that a problem must be small simply because it "
    "was hard to find.",

    "The second night she watched from the gallery instead of the "
    "clockwork room, timing each rotation against the harbor clock with a "
    "notebook balanced on the rail. The pattern held: two full turns at the "
    "ordinary pace, then one turn stretched by perhaps half a second, as "
    "regular as a held breath. She noted the wind direction, the tide, the "
    "temperature of the glass under her palm, anything that might later "
    "prove to matter even if it seemed irrelevant now. Halloran had always "
    "said that a keeper's job was ninety percent noticing things that "
    "turned out not to matter, so that the ten percent that did would not "
    "slip past unnoticed.",

    "It was on the third night that she heard the engine. Not the ferry, "
    "which she knew by the particular unevenness of its idle, and not the "
    "harbor patrol boat, which announced itself from a mile off with a "
    "distinctive rattle in its exhaust. This was smaller, closer to the "
    "rocks than any sensible pilot would bring a boat in fog this thick, "
    "and it cut out entirely within a minute or two of the light's next "
    "slowed rotation. Elena stood very still at the gallery rail, straining "
    "to separate the sound of waves against granite from anything that "
    "might be a hull, and heard nothing further before the beam resumed its "
    "ordinary pace.",

    "She did not mention the engine in her log. Not yet. A keeper who "
    "reported unverified engine noise near a hazardous shoal in heavy fog "
    "would draw a well-meaning but time-consuming visit from the harbor "
    "patrol, and Elena wanted one more night of her own observations before "
    "she invited anyone else's assumptions into the investigation. She was "
    "aware, distantly, that this was not strictly the by-the-book response, "
    "and she made her peace with that the same way she made her peace with "
    "most decisions on the rock: by trusting eleven years of noticing "
    "things that turned out to matter.",

    "The fourth night, she moved her notebook to the clockwork room and "
    "left the gallery door propped for sound instead of sight. When the "
    "rhythm caught again, faint and half a second long, she was already "
    "kneeling beside the drive shaft with her palm flat against the "
    "housing, and this time she felt it: not heat, not grit, but the "
    "faintest additional resistance, gone again almost before she was sure "
    "she had felt anything at all. It was not the mechanism slowing itself. "
    "Something was, very briefly, touching it from outside the housing, in "
    "a place the housing was not built to be touched.",

    "She traced the seam of the casing with a flashlight and found what "
    "eleven years of maintenance checks had never required her to look "
    "for: a narrow service panel, painted over so many times it had become "
    "invisible, low on the seaward side of the clockwork room. It was not "
    "in Halloran's diagrams. It was not in the harbor authority's original "
    "blueprints, which she had read more than once out of simple curiosity "
    "about the building she lived inside. It was, as far as she could tell "
    "from the layers of paint sealing its edges, older than either "
    "document, and it had clearly been opened, however carefully, more "
    "recently than the paint suggested.",

    "Behind the panel she found a second, smaller mechanism, hand-built and "
    "unmistakably added after the original clockwork had been installed. "
    "It was not sabotage, not exactly; it was closer to a splice, a "
    "deliberate tap into the rotation that drew off a fraction of the "
    "drive's motion into a second, much smaller light she could not "
    "immediately locate from inside the tower. Someone, at some point in "
    "the lighthouse's long and only partially documented history, had "
    "built a second signal into the first one, and had done it well enough "
    "that eleven years of careful keepers had never noticed the theft of "
    "half a second per rotation.",

    "It took her the better part of a week, and one deliberately vague "
    "conversation with the harbor master's oldest surviving clerk, to piece "
    "together what the second light had once been for. During a period "
    "the official records preferred not to dwell on, the rock had "
    "apparently done double duty: one beam for the shipping lanes, exactly "
    "as intended, and one considerably dimmer pulse timed to the tap in the "
    "clockwork, aimed low across the water toward a cove no chart bothered "
    "naming. Whether it had guided smugglers, fishermen avoiding a wartime "
    "curfew, or something else the clerk declined to specify, no one now "
    "living could say for certain, and the honest answer no longer seemed "
    "to matter as much as the mechanism itself.",

    "What did matter was that the splice had not been abandoned so much as "
    "forgotten, and forgotten mechanisms on a rock this exposed to salt and "
    "weather did not stay silent forever. Somewhere in the intervening "
    "decades, corrosion or settling stone had loosened a linkage just "
    "enough that the old secondary light occasionally caught, drawing its "
    "fraction of a second from the primary beam whether anyone still wanted "
    "it to or not, and sending an equally forgotten pulse out toward a cove "
    "that had not seen whatever traffic it once served in longer than "
    "anyone alive could remember.",

    "Elena spent the better part of a gray, wind-scoured morning deciding "
    "what to do about a hundred-year-old secret she had not asked to "
    "inherit. She could seal the panel again, as generations before her "
    "evidently had, and let the fraction of a second remain someone else's "
    "problem for another few decades. She could report it exactly as she "
    "had found it, and let the harbor authority decide whether a piece of "
    "the coast's history belonged in a museum, a repair order, or both. "
    "What she could not do, she decided, was leave the mystery unrecorded "
    "the way every keeper before her apparently had, because the next "
    "person to notice half a second missing from the rotation deserved a "
    "better answer than a week of sleepless nights.",

    "In the end she wrote it up plainly: the timing anomaly, the panel, the "
    "splice, the clerk's careful non-answer about the cove, and her own "
    "best guess at a repair that would stop the drift without erasing "
    "whatever the mechanism had once meant to whoever built it. She left "
    "the entry unsealed in the front of the log, where the next keeper "
    "would find it long before they found any reason to go looking on "
    "their own, because Halloran had been right about one thing above all "
    "the others: a keeper's real job was making sure the next person up "
    "the stairs never had to start from nothing.",

    "The following week, with the linkage quietly reset and the panel "
    "resealed under fresh paint of her own, the beam turned exactly as it "
    "always had, two steady rotations after another, with nothing left to "
    "count against a harbor clock at three in the morning. Elena told "
    "herself she did not miss the half second, and mostly, on the nights "
    "the fog stayed thin enough to see the mainland lights, she believed "
    "it. On the thicker nights, she still found herself listening for an "
    "engine that never returned, and writing one more line in the log to "
    "say, honestly, that the light had behaved.",

    "The harbor master's clerk, true to his careful non-answers, never did "
    "confirm what the cove had once been used for, though he did mention, "
    "on her next supply run into town, that his own grandmother had kept "
    "house for a keeper on Gannet Rock during the years the official "
    "records preferred to skip. He offered nothing further, and Elena did "
    "not press him, because she had already decided that some parts of a "
    "hundred-year-old secret were more useful left exactly as uncertain as "
    "she had found them. A lighthouse, she had come to think, was allowed "
    "to keep a few of its own answers, provided the light itself kept "
    "doing the one job that actually mattered to anyone still out on the "
    "water.",

    "She did add one line to the log that she suspected no keeper before "
    "her had ever thought necessary: a short note, dated and initialed, "
    "describing exactly where the panel sat, exactly how the linkage had "
    "been reset, and exactly what a slowed rotation might mean if it ever "
    "began again after she was gone. It was not much, measured against a "
    "hundred years of silence on the subject, but it was more than she had "
    "been given, and she had spent enough sleepless nights on this rock to "
    "know precisely how much that kind of small, deliberate honesty was "
    "worth to whoever climbed these stairs next.",

    "Winter came in hard after that, the way it always did on Gannet Rock, "
    "and the ordinary business of keeping a light through storms and fog "
    "and the long stretches of nothing in between left little room for "
    "wondering about smugglers who were almost certainly dead now, or "
    "coves that had not seen unlawful traffic in longer than anyone alive "
    "could verify. Elena kept her log the way she always had, faithfully "
    "and a little more than the job strictly required, and if she still "
    "paused sometimes at three in the morning to listen for an engine that "
    "never came back, she told herself that was simply what eleven, now "
    "twelve, years on this rock had taught her to do.",
)

_FULL_STORY = "\n\n".join(_STORY_PARAGRAPHS)


def _prefix_by_paragraph(full_text: str, target_chars: int) -> str:
    """Smallest paragraph-aligned prefix of ``full_text`` at or past
    ``target_chars`` — never a mid-sentence cut, so the "sustained" sample
    stays a clean, independently listenable excerpt of the "longer" one."""
    paragraphs = full_text.split("\n\n")
    acc: list[str] = []
    total = 0
    for para in paragraphs:
        acc.append(para)
        total += len(para) + (2 if acc else 0)
        if total >= target_chars:
            break
    return "\n\n".join(acc)


SUSTAINED_NARRATION = CorpusItem(
    name="sustained_narration",
    purpose="~5,000-char sustained-narration baseline (adjustable) for "
            "representative voices.",
    text=_prefix_by_paragraph(_FULL_STORY, 5000),
)

LONGER_STRESS = CorpusItem(
    name="longer_stress",
    purpose="Full longer stress passage for representative voices — a strict "
            "superset of SUSTAINED_NARRATION, same story, further in.",
    text=_FULL_STORY,
)

# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #
ALL_ITEMS: tuple[CorpusItem, ...] = (
    DIFFICULT_SHORT,
    STRUCTURAL_STRESS_CHATTERBOX,
    STRUCTURAL_STRESS_KOKORO_EDGE,
    SUSTAINED_NARRATION,
    LONGER_STRESS,
)

_ITEMS_BY_NAME = {item.name: item for item in ALL_ITEMS}


def get_item(name: str) -> CorpusItem:
    return _ITEMS_BY_NAME[name]


def corpus_identity() -> str:
    """A short hash identifying the exact corpus text in use (P12).

    Order- and content-sensitive: any wording change to any item changes
    this identity, so a manifest recorded against one identity always means
    the same text was read.
    """
    digest = hashlib.sha256()
    for item in ALL_ITEMS:
        digest.update(item.name.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(item.text.encode("utf-8"))
        digest.update(b"\x00")
    return digest.hexdigest()[:16]
