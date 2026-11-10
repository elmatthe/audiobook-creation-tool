"""What a listener hears from a PDF (v0.7.2 Phase 8, ACT72-057 and ACT72-063).

Until this module nothing checked the PDF line cleaning against text a person wrote down first: a smoke extraction
looked for a substring, and a differential held the page join to its own earlier implementation.

Every case here is a real PDF, built line by line with PyMuPDF so each line of the page is exactly the line the test
names, and read back through the production extractor (``tts.pdf_extractor.extract_text_from_pdf``). Each fixture is
checked first: the raw text PyMuPDF hands the cleaner must be the lines the test laid out, so a case cannot pass or fail
because the page was not what it was meant to be. The expected narration is written out by hand in each test. It is
what a person reading the page aloud would say, never the cleaner's own output copied back.

Writing them that way found two defects the old checks could not see (ACT72-063, fixed with this module): a page number
was read out in the middle of any sentence that ran on to the next page, and it fused with a word hyphenated at the
foot of a page. The last section states the limits that remain, by name, so a change to any of them is deliberate.
"""

from __future__ import annotations

from pathlib import Path

import pytest

fitz = pytest.importorskip("fitz")

from tts import pdf_extractor  # noqa: E402

#: A book-sized page; body text starts well below the running head and ends well above the page number.
PAGE_WIDTH, PAGE_HEIGHT = 432, 648
BODY_TOP, LINE_STEP = 90, 18


def page(lines, *, head=None, number=None, number_at_top=False) -> dict:
    return {"lines": list(lines), "head": head, "number": number, "number_at_top": number_at_top}


def expected_raw(spec: dict) -> str:
    """The text PyMuPDF must hand the cleaner for one page: top to bottom, one line each."""
    top = [spec["head"]] if spec["head"] is not None else []
    if spec["number"] is not None and spec["number_at_top"]:
        top.append(str(spec["number"]))
    bottom = [str(spec["number"])] if spec["number"] is not None and not spec["number_at_top"] else []
    return "".join(line + "\n" for line in [*top, *spec["lines"], *bottom])


def make_pdf(folder: Path, name: str, *pages: dict) -> Path:
    """A real PDF with each line at its own baseline, validated before the cleaner ever sees it."""
    assert not any(spec["head"] is not None and spec["number_at_top"] for spec in pages), \
        "a running head and a top page number share a baseline; use one per page"
    document = fitz.open()
    for spec in pages:
        # Written top to bottom: PyMuPDF returns a page's text in the order it was written into the page.
        sheet = document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
        if spec["head"] is not None:
            sheet.insert_text((72, 40), spec["head"], fontname="helv", fontsize=9)
        if spec["number"] is not None and spec["number_at_top"]:
            sheet.insert_text((340, 40), str(spec["number"]), fontname="helv", fontsize=9)
        for index, line in enumerate(spec["lines"]):
            sheet.insert_text((72, BODY_TOP + index * LINE_STEP), line, fontname="helv", fontsize=11)
        if spec["number"] is not None and not spec["number_at_top"]:
            sheet.insert_text((210, 610), str(spec["number"]), fontname="helv", fontsize=9)
    path = folder / f"{name}.pdf"
    document.save(path)
    document.close()
    with fitz.open(path) as written:
        raw = [sheet.get_text("text") for sheet in written]
    assert raw == [expected_raw(spec) for spec in pages], "the fixture is not the page the test describes"
    return path


def narration(folder: Path, name: str, *pages: dict) -> str:
    return pdf_extractor.extract_text_from_pdf(str(make_pdf(folder, name, *pages)))


# --------------------------------------------------------------------------- #
# Words and sentences broken by the page's own line breaks
# --------------------------------------------------------------------------- #


def test_a_word_hyphenated_at_a_line_end_is_read_as_one_word(tmp_path):
    text = narration(tmp_path, "hyphen", page(["It was an impor-", "tant morning for the keeper."]))
    assert text == "It was an important morning for the keeper."


def test_a_sentence_wrapped_over_several_lines_is_read_as_one_sentence(tmp_path):
    text = narration(tmp_path, "wrapped", page([
        "The keeper climbed the narrow stairs as the",
        "storm gathered over the harbour, and at the",
        "top he lit the great lamp."]))
    assert text == ("The keeper climbed the narrow stairs as the storm gathered over the harbour, and at the top he "
                    "lit the great lamp.")


def test_paragraphs_stay_apart_and_a_chapter_heading_keeps_its_own_line(tmp_path):
    text = narration(tmp_path, "paragraphs", page([
        "Chapter 4: The Storm",
        "The wind rose after dark and the",
        "sea came over the rocks.",
        "By midnight the lamp was the only",
        "light for thirty miles.",
        '"Will it hold?" asked the boy.',
        '"It always has," said the keeper.']))
    assert text.split("\n") == [
        "Chapter 4: The Storm",
        "The wind rose after dark and the sea came over the rocks.",
        "By midnight the lamp was the only light for thirty miles.",
        '"Will it hold?" asked the boy.',
        '"It always has," said the keeper.']


# --------------------------------------------------------------------------- #
# Page numbers
# --------------------------------------------------------------------------- #


def test_a_page_number_under_a_sentence_that_runs_on_overleaf_is_not_read_out(tmp_path):
    """The usual page: it ends in the middle of a sentence, with its number printed underneath (ACT72-063)."""
    text = narration(
        tmp_path, "number-foot",
        page(["The keeper climbed the narrow stairs and the door", "stood"], number=12),
        page(["open to the night. He lit the lamp."], number=13))
    assert text == "The keeper climbed the narrow stairs and the door stood open to the night. He lit the lamp."


def test_a_page_number_above_the_text_is_not_read_out(tmp_path):
    text = narration(
        tmp_path, "number-head",
        page(["The keeper climbed the narrow stairs and the door", "stood"], number=12, number_at_top=True),
        page(["open to the night. He lit the lamp."], number=13, number_at_top=True))
    assert text == "The keeper climbed the narrow stairs and the door stood open to the night. He lit the lamp."


def test_a_page_number_after_a_finished_sentence_is_not_read_out_and_the_next_page_starts_a_new_paragraph(tmp_path):
    text = narration(
        tmp_path, "number-after-sentence",
        page(["The keeper climbed the narrow stairs.", "The door stood open."], number=12),
        page(["He lit the lamp."], number=13))
    assert text == "The keeper climbed the narrow stairs.\nThe door stood open.\n\nHe lit the lamp."


def test_a_sentence_carried_across_three_numbered_pages_is_read_straight_through(tmp_path):
    text = narration(
        tmp_path, "three-pages",
        page(["He counted every step, as he had done for", "thirty years, and at the"], number=198),
        page(["top of the tower, where the wind came", "through the broken"], number=199),
        page(["pane, he lit the great lamp."], number=200))
    assert text == ("He counted every step, as he had done for thirty years, and at the top of the tower, where the "
                    "wind came through the broken pane, he lit the great lamp.")
    assert not any(number in text for number in ("198", "199", "200"))


def test_a_word_hyphenated_at_the_foot_of_a_page_is_read_as_one_word(tmp_path):
    """Before ACT72-063 this page pair was read as "the morn3 ing light"."""
    text = narration(
        tmp_path, "hyphen-foot",
        page(["He counted the steps before the morn-"], number=3),
        page(["ing light reached the gallery."], number=4))
    assert text == "He counted the steps before the morning light reached the gallery."


# --------------------------------------------------------------------------- #
# Running heads
# --------------------------------------------------------------------------- #


def test_a_short_running_head_in_capitals_is_not_read_out(tmp_path):
    """Chapter numerals and abbreviations printed at the top of each page ("IV", "CH")."""
    text = narration(
        tmp_path, "short-heads",
        page(["The keeper climbed the narrow stairs and the door", "stood"], head="IV", number=12),
        page(["open to the night. He lit the lamp."], head="CH", number=13))
    assert text == "The keeper climbed the narrow stairs and the door stood open to the night. He lit the lamp."


# --------------------------------------------------------------------------- #
# What must not be joined, and what must not be deleted
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("heading", ["THE STORM", "The Long Night", "Chapter 52: Minefield", "Prologue 1"],
                         ids=["capitals", "title-case", "chapter-with-a-colon", "numbered-prologue"])
def test_a_heading_is_never_run_into_the_text_under_it(tmp_path, heading):
    text = narration(tmp_path, "heading", page([heading, "The wind rose after dark.", "Nobody slept."]))
    assert text.split("\n") == [heading, "The wind rose after dark.", "Nobody slept."]


def test_a_line_after_a_colon_or_a_closing_quote_starts_on_its_own(tmp_path):
    text = narration(tmp_path, "colon-quote", page([
        "He read the list aloud:",
        "oil, rope and a second lantern.",
        '"Is that all?"',
        "It was."]))
    assert text.split("\n") == ["He read the list aloud:", "oil, rope and a second lantern.", '"Is that all?"', "It was."]


def test_numbers_and_short_words_that_belong_to_the_text_are_kept(tmp_path):
    """A year in a sentence, a number that happens to wrap onto a line of its own in the middle of a page, a numbered
    line, and a one-word answer are text, not page furniture."""
    text = narration(tmp_path, "kept", page([
        "In 1984 he arrived with",
        "42",
        "crates of oil. He asked whether any had leaked:",
        "No.",
        "1. Not one of them.",
        "OK. He signed for all 42."], number=7))
    assert text.split("\n") == [
        "In 1984 he arrived with 42 crates of oil. He asked whether any had leaked:",
        "No.",
        "1. Not one of them.",
        "OK. He signed for all 42."]


def test_a_page_that_is_only_its_number_adds_nothing(tmp_path):
    text = narration(
        tmp_path, "blank-leaf",
        page(["The first part ends here."], number=40),
        page([], number=41),
        page(["The second part begins."], number=42))
    assert text == "The first part ends here.\n\nThe second part begins."


# --------------------------------------------------------------------------- #
# The two rules ACT72-063 added, at their edges (plain text, exactly as PyMuPDF hands it over)
# --------------------------------------------------------------------------- #


def test_only_a_bare_number_on_the_first_or_last_line_of_a_page_is_taken_for_its_page_number():
    drop = pdf_extractor._drop_page_number_at_the_edges
    assert drop("12\nThe door stood\nopen.\n") == "\nThe door stood\nopen.\n"
    assert drop("The door stood\nopen\n12\n") == "The door stood\nopen\n\n"
    assert drop("\n\n 12 \nThe door\n") == "\n\n\nThe door\n", "the first line that has text, whatever blank lines precede it"
    assert drop("He had\n42\ncrates.\n") == "He had\n42\ncrates.\n", "a number inside the page is text"
    assert drop("12 crates\nwere left\nin 1984\n") == "12 crates\nwere left\nin 1984\n", "a line with words is never one"
    assert drop("12\n") == "\n" and drop("") == "" and drop("\n\n") == "\n\n"
    assert drop("7\nOne line.\n8\n") == "\nOne line.\n\n", "both edges, when both are bare numbers"


def test_only_a_page_that_ends_in_a_hyphen_is_joined_to_the_next_page_without_a_space():
    join = pdf_extractor._join_words_split_across_pages
    assert join(["before the morn-", "ing light.", "A new page."]) == ["before the morning light.", "A new page."]
    assert join(["It ended.", "Another began."]) == ["It ended.", "Another began."]
    assert join(["one-", "two-", "three"]) == ["onetwothree"], "a word may be carried more than once"
    assert join(["only-"]) == ["only-"] and join([]) == []


# --------------------------------------------------------------------------- #
# The limits that remain, stated (ACT72-064: open, for the owner to decide)
# --------------------------------------------------------------------------- #
# These are not what a listener would want. They are what the rules do today, written down so that nobody mistakes them
# for covered behaviour and so that changing one is a decision. Each is rare beside the two defects fixed above, and a
# general answer (recognising a running head by its repetition, telling an acronym from a numeral) is new behaviour,
# not a repair.


def test_limit_a_running_head_longer_than_four_capitals_is_still_read_out(tmp_path):
    """Only a line of one to four capitals is treated as a running head. A book or chapter title printed at the top
    of every page is kept as a heading, so it is narrated at each page, here in the middle of a sentence."""
    text = narration(
        tmp_path, "long-head",
        page(["The keeper climbed the narrow stairs and the door", "stood"], head="THE LIGHTHOUSE KEEPER", number=12),
        page(["open to the night."], head="THE LIGHTHOUSE KEEPER", number=13))
    assert text == ("THE LIGHTHOUSE KEEPER\nThe keeper climbed the narrow stairs and the door stood "
                    "THE LIGHTHOUSE KEEPER\nopen to the night.")


def test_limit_a_compound_word_broken_at_its_own_hyphen_loses_the_hyphen(tmp_path):
    """A hyphen at a line end is always taken for a broken word; nothing can tell "well-known" from "impor-tant"."""
    text = narration(tmp_path, "compound", page(["He was a well-", "known keeper of twenty-", "three years."]))
    assert text == "He was a wellknown keeper of twentythree years."


def test_limit_a_line_that_is_only_a_short_word_in_capitals_is_dropped_wherever_it_is(tmp_path):
    """The running-head rule looks at the line, not at where it is on the page, so an acronym that wraps onto a line
    of its own is lost from the sentence, which then closes up around the gap."""
    text = narration(tmp_path, "acronym", page(["The lamp was supplied by", "NASA", "in 1969."]))
    assert text == "The lamp was supplied by in 1969."


def test_limit_a_bare_number_that_ends_a_page_is_taken_for_its_page_number(tmp_path):
    """The cost of ACT72-063's rule: on a page with no printed number, a sentence whose last line on that page is a
    number alone loses it. Justified text does not end a full line with one word, so this needs a very short line."""
    text = narration(
        tmp_path, "number-in-prose",
        page(["He counted the steps aloud until he reached", "100"]),
        page(["and then he stopped."]))
    assert text == "He counted the steps aloud until he reached and then he stopped."
