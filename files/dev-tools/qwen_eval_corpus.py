"""Canonical difficult-fantasy passages for the Plan 01 voice evaluation (dev-only).

Original text written for this evaluation: no copyrighted excerpt, no filler loops and no
metadata-looking first line (a line starting with ``Title:``, ``Author:`` or ``#`` would be
silently dropped or rewritten by the Chatterbox and Kokoro file paths, so none exists).
Every voice and engine reads exactly the same words; the title is an ordinary paragraph.

The passages stress what the plan lists: invented proper names that repeat, dialogue,
abbreviations (Dr., Mr., Mrs., Prof., St., Capt.), initials, numbers, dates and times,
decimal and ratio punctuation, ellipses and title/paragraph transitions.

The production ``quality_corpus`` module is intentionally not edited: its corpus identity
and expected results stay exactly as they were.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True)
class EvalPassage:
    name: str
    text: str

    @property
    def char_count(self) -> int:
        return len(self.text)

    @property
    def word_count(self) -> int:
        return len(self.text.split())

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()


EVAL_SHORT = EvalPassage(
    name="eval_short",
    text=(
        "Captain Ysolde Thornquill-Vaarwen studied the harbor of Kaerthellin through a "
        "cracked brass spyglass. It was 4:50 in the morning on the 14th of Emberfall, and "
        "Dr. Maelis Orrowyn had not yet returned from St. Quillon's Isle.\n\n"
        "\"Three ships,\" the signalman muttered. \"Perhaps four... I cannot tell, Captain.\"\n\n"
        "\"Count again, Mr. Dunmarrow.\"\n\n"
        "He counted again. His lips moved over the numbers as if they might rearrange "
        "themselves.\n\n"
        "The tide had risen 2.5 fathoms since midnight, and the lanterns of the Zephyrine "
        "Fleet burned in a ratio of nearly 3:1 against the harbor guard, a margin no one "
        "at the Tidewatch could explain. A. M. Thornwick, the quartermaster, swore it was "
        "the work of the Hollowed Choir, whose bells had not rung in over 200 years. "
        "Ysolde lowered the glass. \"If the Choir has woken,\" she said quietly, \"then "
        "Kaerthellin has until dawn.\"\n\n"
        "Behind them, high in the dark, something very large began, slowly, to ring."
    ),
)

EVAL_LONG = EvalPassage(
    name="eval_long",
    text=(
        "The Ninth Bell of Kaerthellin\n\n"
        "Nobody in Kaerthellin could say who had hung the ninth bell, only that it had never "
        "rung. Eight bells spoke from the Tidewatch tower: one for each watch of the day, and "
        "the Mourning Bell, which sounded for drowned sailors. The ninth hung beneath them in "
        "the dark of the belfry, green with salt, its clapper bound in a rope that no living "
        "hand had tied. Captain Ysolde Thornquill-Vaarwen had climbed past it 212 times a year "
        "for nineteen years, and in all that time she had never once looked up.\n\n"
        "That changed on the 14th of Emberfall, at 4:50 in the morning. She was standing at the "
        "harbor window with a cracked brass spyglass, counting the lanterns of the Zephyrine "
        "Fleet, when a single low note rolled down the tower stairs and through the floor of the "
        "room. It was not loud. It was the sound of a very large thing clearing its throat. "
        "Every cup on the table shivered, the cat left the room, and Mr. Dunmarrow, the "
        "signalman, dropped his pencil and did not pick it up.\n\n"
        "\"That was the ninth bell,\" he whispered. \"Captain, that was the ninth bell.\"\n\n"
        "\"Bells do not ring themselves, Mr. Dunmarrow.\"\n\n"
        "\"No, ma'am. But that one has been silent for three hundred years... and the rope is "
        "still on it. I checked the rope myself last winter.\"\n\n"
        "Ysolde set down the spyglass. Through the window the harbor lay black and flat, and "
        "the tide, which had been falling when she came on watch, was climbing the pilings "
        "again. By her own marks it had risen 2.5 fathoms since midnight, which was "
        "impossible, and the lanterns of the Zephyrine Fleet had begun to burn in a pattern "
        "she had only ever seen in a book: three bright for every one dim, a ratio of 3:1, "
        "repeating without a pause. A fleet that signaled like that was not looking for a "
        "harbor. It was answering something.\n\n"
        "Down on the quay the town was waking in the wrong order. Mrs. Bracegirdle, the baker, "
        "had flung open her shutters in her nightgown, and the ferrymen stood in a silent row "
        "with their caps in their hands. Somewhere a child was asking why the bells sounded "
        "different today, and nobody had the heart to say that only one of them had. A town of "
        "that size should have been a hum, a rattle, a hundred small arguments. Instead there "
        "was only the water, slapping the pilings, and under it, very faintly, a second sound, "
        "as if the tower itself were still humming from the note.\n\n"
        "By 5:10 the whole tower was awake. Dr. Maelis Orrowyn arrived first, wet to the knees "
        "after rowing back from St. Quillon's Isle, where she had spent the night setting the "
        "broken arm of a lighthouse boy. A. M. Thornwick, the quartermaster, came next, "
        "buttoning his coat wrong, and behind him came Prof. Ilvaren Oake, who taught the "
        "history of the coast and had once written four hundred pages about the Hollowed "
        "Choir without, as he now admitted, believing a word of them.\n\n"
        "\"The old accounts agree on three points,\" the professor said, unrolling a map on the "
        "table and weighting its corners with the captain's cups. \"First, that there were "
        "nine bells, e.g. eight for the living and one for the debt. Second, that the ninth "
        "was cast from the anchors of ships the sea had already taken. Third, and this is the "
        "part I never printed, that it rings only when the sea remembers what it is owed.\"\n\n"
        "\"Owed by whom?\" asked Thornwick.\n\n"
        "Prof. Oake tapped a smudged page. \"The inscription, if my copyist can be trusted, "
        "reads: Cast of nine hundred anchors, hung to remember what the harbor would rather "
        "forget. I assumed it was poetry. Poets in those days were fond of exaggerating the "
        "cost of their metal.\" He looked up. \"There were nine hundred anchors, Captain. I "
        "counted them in the customs ledgers myself, from the 9th of Frostwane to the end of "
        "that winter. Nine hundred ships, 3,100 sailors... and not one of them was ever "
        "listed as lost. Every entry says only that they were delayed.\"\n\n"
        "\"By Kaerthellin, Quartermaster. By all of us, vs. by any one of us, I could not "
        "tell you. The accounts were never that precise.\"\n\n"
        "Thornwick had begun to count under his breath, the way sailors do when the sea has "
        "stopped making sense. He counted the lanterns of the Zephyrine Fleet twice, and the "
        "second count disagreed with the first by exactly one lamp, which he took as an insult. "
        "\"Forty-one,\" he said, then, \"forty-two. They are adding ships, Captain, or the harbor "
        "is subtracting us.\" Nobody laughed. On the quay below, the ferrymen had begun to kneel, "
        "one after another, not in prayer exactly, but the way people lower themselves to listen "
        "at a door for a sound they have not yet heard.\n\n"
        "Dr. Orrowyn had said nothing until then. She was looking out of the window at the "
        "tide, and at the lanterns, and her face had the stillness of someone doing "
        "arithmetic. \"The fleet is not approaching,\" she said at last. \"I have been "
        "watching their lamps for ten minutes. They are holding position at a distance of "
        "exactly 2.5 leagues, and they are not drifting, which no ship at anchor in this "
        "current can do. Captain, those are not ships. They are the shape of ships, hung "
        "there for us to count.\"\n\n"
        "Mr. Dunmarrow made a small sound. Nobody looked at him.\n\n"
        "Ysolde said nothing for a while. She was thinking of her grandmother's habit of leaving "
        "a lantern burning on the harbor wall every year on the 14th of Emberfall, a habit "
        "nobody in the family had ever explained, and which Ysolde, to her shame, had stopped "
        "keeping the winter her grandmother died. She had told herself that candles were "
        "expensive and that the dead did not read calendars.\n\n"
        "\"Then someone should ask them what they want,\" said Ysolde.\n\n"
        "She climbed the tower alone. The stairs were narrow and slick, and she counted them "
        "as she had always counted them, 212 steps from the harbor room to the belfry, and "
        "when she came out into the cold wind among the eight great bells she did what she "
        "had never done in nineteen years. She looked up. The ninth bell was no longer green. "
        "It shone like new bronze, and the rope on its clapper hung in loose coils on the "
        "floor, cut cleanly through, as if by a very careful knife.\n\n"
        "Beneath the bell, scratched into the oak of the frame where only a person on her "
        "knees could read it, were nine hundred tally marks in groups of five, and a single "
        "line of letters worn almost smooth: OWED, AND NOT FORGIVEN. Ysolde ran her thumb along "
        "the grooves. Someone had counted every one. Someone had stood in this exact spot, in "
        "this exact wind, with a knife and a lantern, and made certain that the number could "
        "never be lost, even if the names were.\n\n"
        "She did not ring it. She understood, standing there with the wind pulling at her coat, "
        "that ringing it was not her part. The Choir's bells had never been rung to be heard. "
        "They had been rung to be answered. So she took the small brass handbell that every "
        "keeper of the Tidewatch carried, the one used for nothing but the Mourning "
        "ceremony, and she rang it once for the drowned, and once for the debt, and a third "
        "time for Kaerthellin, which had forgotten.\n\n"
        "Far out on the water, the lanterns of the Zephyrine Fleet went out together, like "
        "a held breath finally let go. The tide fell. By 6:30 the harbor was an ordinary "
        "harbor again, gray and busy and smelling of tar, and the first fishing boats were "
        "pushing out past the breakwater as though nothing had happened at all.\n\n"
        "Prof. Oake took a long while to put his map away. \"I shall have to write the "
        "fourth chapter again,\" he said. Mr. Dunmarrow found his pencil. Dr. Orrowyn went "
        "back to St. Quillon's Isle to check on the boy, and A. M. Thornwick, who had "
        "believed in the Hollowed Choir from the beginning, did not say a single word of "
        "I told you so, which Ysolde considered the finest courtesy of his career.\n\n"
        "In the weeks that followed, Kaerthellin did something it had not done in three "
        "centuries: it argued about its past in public. Fishermen's wives produced letters "
        "from the backs of drawers. The ferrymen's guild opened its oldest ledger and found "
        "the delayed ships, nine hundred of them, and beside each name a small cross in faded "
        "ink, as though somebody long ago had been unable to bring themselves to cross it out. "
        "Prof. Oake wrote his corrected chapter in eleven days and, for the first time in his "
        "life, was not entirely sure he was finished.\n\n"
        "The ninth bell never rang again. But on the 14th of Emberfall every year after, "
        "at 4:50 in the morning, the keeper of the Tidewatch climbed past it, stopped on the "
        "212th step, and looked up."
    ),
)

PASSAGES: dict[str, EvalPassage] = {EVAL_SHORT.name: EVAL_SHORT, EVAL_LONG.name: EVAL_LONG}

#: Planning targets from the plan (Section 5); calibration, not permission to cut text.
WORD_TARGETS: dict[str, tuple[int, int]] = {"eval_short": (150, 180), "eval_long": (1300, 1600)}
AUDIO_TARGET_SECONDS: dict[str, tuple[int, int]] = {"eval_short": (45, 90), "eval_long": (480, 720)}

#: First lines the Chatterbox/Kokoro file paths treat as metadata; no passage may start a line so.
_RESERVED_LINE_PREFIXES = ("Title:", "Author:", "#")


def reserved_prefix_lines(text: str) -> list[str]:
    """Lines an engine's file reader would silently drop or rewrite; must be empty."""
    return [ln for ln in text.splitlines() if ln.strip().startswith(_RESERVED_LINE_PREFIXES)]


def corpus_manifest() -> dict:
    """Exact identity of the frozen evaluation text: counts and SHA-256 per passage."""
    return {
        name: {
            "chars": p.char_count,
            "words": p.word_count,
            "sha256": p.sha256,
            "target_words": list(WORD_TARGETS[name]),
            "target_seconds": list(AUDIO_TARGET_SECONDS[name]),
        }
        for name, p in PASSAGES.items()
    }
