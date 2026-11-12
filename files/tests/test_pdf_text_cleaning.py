"""What a listener hears from a PDF (v0.7.2 Phase 8, ACT72-057 and ACT72-063; Phase 9, review finding P9-01).

Every case here is a real PDF, built line by line with PyMuPDF so each line of the page is exactly the line the test
names and stands exactly where the test puts it, and read back through the production extractor
(``tts.pdf_extractor.extract_text_from_pdf``). Each fixture is checked first: the raw text PyMuPDF hands the cleaner must
be the lines the test laid out, so a case cannot pass or fail because the page was not what it was meant to be. The
expected narration is written out by hand in each test. It is what a person reading the page aloud would say, never the
cleaner's own output copied back.

Phase 8 wrote these and found a page number read out in the middle of a sentence (ACT72-063). Its fix, and an older rule
beside it, took a line for page furniture by its shape alone, and four tests of this module then asserted the result as
"limits": a year that ended a page was deleted, and an acronym or an emphasised word on a line of its own was deleted
anywhere. The Phase 9 independent review showed those are lost narration (P9-01): "The signal is NOT a command" was read
as "The signal is a command". Those tests asserted the defect and are gone; the cases they covered are stated below as
what must be kept. Page furniture is now recognised by where it stands on the page and by what repeats across pages, so
the fixtures that have furniture place it where a book does: clear of the text, and on more than one page.

The last section states the limits that remain, by name. In every one of them text is read out that a listener might
not want; none of them loses a word.
"""

from __future__ import annotations

from pathlib import Path

import pytest

fitz = pytest.importorskip("fitz")

from tts import pdf_extractor  # noqa: E402

#: A book-sized page; body text starts well below the running head and ends well above the page number.
PAGE_WIDTH, PAGE_HEIGHT = 432, 648
BODY_TOP, LINE_STEP = 90, 18
HEAD_Y, FOOT_Y = 40, 610


def page(lines, *, head=None, number=None, number_at_top=False, head_size=9, number_size=9) -> dict:
    return {"lines": list(lines), "head": head, "number": number, "number_at_top": number_at_top,
            "head_size": head_size, "number_size": number_size}


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
            sheet.insert_text((72, HEAD_Y), spec["head"], fontname="helv", fontsize=spec["head_size"])
        if spec["number"] is not None and spec["number_at_top"]:
            sheet.insert_text((340, HEAD_Y), str(spec["number"]), fontname="helv", fontsize=spec["number_size"])
        for index, line in enumerate(spec["lines"]):
            sheet.insert_text((72, BODY_TOP + index * LINE_STEP), line, fontname="helv", fontsize=11)
        if spec["number"] is not None and not spec["number_at_top"]:
            sheet.insert_text((210, FOOT_Y), str(spec["number"]), fontname="helv", fontsize=spec["number_size"])
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


def test_a_range_of_numbers_broken_at_its_hyphen_keeps_both_numbers(tmp_path):
    """Until v0.7.2 Phase 9 every hyphen at a line end was dropped, so this was read as the one number 19391945 (the
    previous release, 204c33b, and the reviewed candidate both narrated "from 19391945 without a break")."""
    text = narration(tmp_path, "range", page(["He kept the light from 1939-", "1945 without a break."]))
    assert text == "He kept the light from 1939-1945 without a break."


def test_a_compound_with_a_name_broken_at_its_hyphen_keeps_the_hyphen(tmp_path):
    """A broken word carries on in a small letter. A capital after the hyphen is the second half of a compound."""
    text = narration(tmp_path, "name", page(["The chart was an Anglo-", "Saxon copy of a pre-", "Roman one."]))
    assert text == "The chart was an Anglo-Saxon copy of a pre-Roman one."


# --------------------------------------------------------------------------- #
# Page numbers: taken out where the pages count up together
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


def test_page_numbers_that_change_sides_between_pages_are_all_taken_out(tmp_path):
    """A chapter's first page carries its number at the foot, the others at the head: one count, two places."""
    text = narration(
        tmp_path, "sides",
        page(["The tide turned at four and"], number=31),
        page(["the boats came in on it, one after", "another, until the"], number=32, number_at_top=True),
        page(["harbour was full."], number=33, number_at_top=True))
    assert text == "The tide turned at four and the boats came in on it, one after another, until the harbour was full."


def test_a_word_hyphenated_at_the_foot_of_a_page_is_read_as_one_word(tmp_path):
    """Before ACT72-063 this page pair was read as "the morn3 ing light"."""
    text = narration(
        tmp_path, "hyphen-foot",
        page(["He counted the steps before the morn-"], number=3),
        page(["ing light reached the gallery."], number=4))
    assert text == "He counted the steps before the morning light reached the gallery."


def test_a_page_that_is_only_its_number_adds_nothing(tmp_path):
    text = narration(
        tmp_path, "blank-leaf",
        page(["The first part ends here."], number=40),
        page([], number=41),
        page(["The second part begins."], number=42))
    assert text == "The first part ends here.\n\nThe second part begins."


def test_a_page_with_no_text_at_all_adds_nothing_and_does_not_break_the_count(tmp_path):
    """An empty leaf between two numbered pages: the numbers still differ by the distance between their pages."""
    text = narration(
        tmp_path, "empty-leaf",
        page(["The first part ends where the"], number=40),
        page([]),
        page(["second part begins."], number=42))
    assert text == "The first part ends where the second part begins."


def test_a_pdf_with_no_text_on_any_page_is_refused_and_says_why(tmp_path):
    path = make_pdf(tmp_path, "scanned", page([]), page([]))
    with pytest.raises(ValueError, match="No readable text found"):
        pdf_extractor.extract_text_from_pdf(str(path))


# --------------------------------------------------------------------------- #
# Running heads: a short one is taken out where it repeats
# --------------------------------------------------------------------------- #


def test_a_short_running_head_in_capitals_is_not_read_out(tmp_path):
    """A chapter numeral printed at the head of each page of its chapter. (Until Phase 9 this fixture put a different
    word on each of its two pages, "IV" and "CH", and passed because every short line of capitals was deleted wherever
    it stood. A running head is the same word page after page; that is now what the fixture has and what the rule needs.)"""
    text = narration(
        tmp_path, "short-heads",
        page(["The keeper climbed the narrow stairs and the door", "stood"], head="IV", number=12),
        page(["open to the night. He lit the lamp."], head="IV", number=13))
    assert text == "The keeper climbed the narrow stairs and the door stood open to the night. He lit the lamp."


def test_a_page_with_a_running_head_a_number_and_an_acronym_loses_only_the_first_two(tmp_path):
    """Mixed: furniture at both edges of every page, and capitals and a number inside the text of the same pages."""
    text = narration(
        tmp_path, "mixed",
        page(["The lamp was supplied by", "NASA", "in 1969 and the safe opens with the code", "1984"], head="CH", number=7),
        page(["and closes when the handle turns."], head="CH", number=8))
    assert text == ("The lamp was supplied by NASA in 1969 and the safe opens with the code 1984 and closes when the handle "
                    "turns.")


# --------------------------------------------------------------------------- #
# What must be kept: numbers and capitals that are the text (review finding P9-01)
# --------------------------------------------------------------------------- #

#: What v0.7.1 (204c33b, the previous release) narrated from the reviewer's three-page PDF, recorded by this phase's
#: evidence script from that commit's own extractor. It kept the year and lost the negation.
PREVIOUS_RELEASE_NARRATED = ("The safe opens with the code 1984 and closes when the handle turns.\n\n"
                             "The signal is a command to open it.")


def test_the_reviewers_pdf_a_year_that_ends_a_page_and_a_not_on_a_line_of_its_own_are_both_read(tmp_path):
    """The Phase 9 reviewer's fixture: three pages, no printed page numbers, every line ordinary body text. The reviewed
    candidate read "The safe opens with the code and closes when the handle turns." and "The signal is a command to open
    it.": the code was gone and the meaning of the second sentence reversed."""
    text = narration(
        tmp_path, "reviewers",
        page(["The safe opens with the code", "1984"]),
        page(["and closes when the handle turns."]),
        page(["The signal is", "NOT", "a command to open it."]))
    assert text == ("The safe opens with the code 1984 and closes when the handle turns.\n\n"
                    "The signal is NOT a command to open it.")
    first, second = text.split("\n\n")
    was_first, was_second = PREVIOUS_RELEASE_NARRATED.split("\n\n")
    assert first == was_first, "the previous release read the year too; only the reviewed candidate lost it"
    assert second != was_second and second.replace(" NOT", "") == was_second, "the previous release lost the negation as well"


def test_a_number_that_is_the_first_line_of_a_page_is_read(tmp_path):
    text = narration(
        tmp_path, "number-first",
        page(["The keeper paid the chandler"]),
        page(["1984", "pounds for the new lamp."]))
    assert text == "The keeper paid the chandler 1984 pounds for the new lamp."


def words(text: str) -> list[str]:
    """What is read, in order, whatever lines it is on: for a case whose subject is the words and not the line breaks."""
    return text.split()


def test_a_number_on_a_line_of_its_own_after_a_colon_is_read(tmp_path):
    """It follows a finished line and ends its page, exactly where a page number would be. Until Phase 9 it was deleted
    for that (by the previous release as well, which deleted every line of digits left on its own)."""
    text = narration(tmp_path, "number-after-colon", page(["The safe opens with one code:", "1984"]), page(["Nobody else knew it."]))
    assert words(text) == words("The safe opens with one code: 1984 Nobody else knew it.")


def test_numbers_that_count_up_across_pages_are_read_when_they_stand_in_the_run_of_the_text(tmp_path):
    """Two pages whose last lines are 12 and 13, exactly as two page numbers would count. They are lines of the text, set
    at the text's own spacing under the line before them, and that is what keeps them: counting up is not enough."""
    text = narration(
        tmp_path, "counting-in-the-text",
        page(["On the first night the keeper counted", "12"]),
        page(["lamps along the shore, and on the second", "13"]),
        page(["of them were still burning."]))
    assert text == ("On the first night the keeper counted 12 lamps along the shore, and on the second 13 of them were "
                    "still burning.")


def test_a_year_that_ends_a_page_is_read_and_the_page_number_under_it_is_not(tmp_path):
    text = narration(
        tmp_path, "year-over-number",
        page(["The safe opens with the code", "1984"], number=12),
        page(["and closes when the handle turns."], number=13))
    assert text == "The safe opens with the code 1984 and closes when the handle turns."


@pytest.mark.parametrize("word", ["NOT", "NASA", "UN", "OK", "I", "IV"])
def test_a_short_word_in_capitals_on_a_line_of_its_own_inside_a_sentence_is_read(tmp_path, word):
    """The previous release and the reviewed candidate both read this page as "The lamp was supplied by in 1969."."""
    text = narration(tmp_path, "capitals", page(["The lamp was supplied by", word, "in 1969."]))
    assert text == f"The lamp was supplied by {word} in 1969."


def test_numbers_and_short_words_that_belong_to_the_text_are_kept(tmp_path):
    """A year in a sentence, a number that happens to wrap onto a line of its own in the middle of a page, a numbered
    line, and a one-word answer are text, not page furniture."""
    text = narration(tmp_path, "kept", page([
        "In 1984 he arrived with",
        "42",
        "crates of oil. He asked whether any had leaked:",
        "No.",
        "1. Not one of them.",
        "OK. He signed for all 42."]))
    assert text.split("\n") == [
        "In 1984 he arrived with 42 crates of oil. He asked whether any had leaked:",
        "No.",
        "1. Not one of them.",
        "OK. He signed for all 42."]


def test_a_chapter_numeral_that_stands_once_above_its_chapter_is_read(tmp_path):
    """It is a heading, not a running head: nothing repeats it. Until Phase 9 it was deleted with every short line of
    capitals."""
    text = narration(tmp_path, "numeral", page(["IV", "The Storm", "The wind rose after dark."]), page(["Nobody slept."]))
    assert text.split("\n") == ["IV", "The Storm", "The wind rose after dark.", "", "Nobody slept."]


def test_the_same_capitals_set_as_a_title_on_two_pages_are_read(tmp_path):
    """Set larger than the text under it, a line is a title however often it comes: only a line no larger than the page's
    text is taken for a running head."""
    text = narration(
        tmp_path, "titles",
        page(["The wind rose after dark."], head="II", head_size=20),
        page(["Nobody slept that night."], head="II", head_size=20))
    assert text == "II\nThe wind rose after dark.\n\nII\nNobody slept that night."


def placed_pdf(folder: Path, name: str, pages: list[list[tuple[float, str, float]]], **size) -> Path:
    """A real PDF with each line exactly where the test puts it: ``(baseline, text, font size)``, top to bottom."""
    document = fitz.open()
    for lines in pages:
        sheet = document.new_page(**size)
        for at, text, fontsize in lines:
            sheet.insert_text((72, at), text, fontname="helv", fontsize=fontsize)
    path = folder / f"{name}.pdf"
    document.save(path)
    document.close()
    with fitz.open(path) as written:
        raw = [sheet.get_text("text") for sheet in written]
    assert raw == ["".join(text + "\n" for _at, text, _size in lines) for lines in pages], "not the page the test describes"
    return path


@pytest.mark.parametrize("word", ["NOT", "I", "FBI", "NASA"])
def test_the_same_short_capitals_in_the_body_of_two_pages_are_read_on_both(tmp_path, word):
    """v0.7.2 Phase 9 remote re-review R9-01, on the reviewer's own pages: PyMuPDF's default page, two lines of text at
    the top, and an emphasised word a few lines further down, standing clear of the line before it at the same height on
    both pages. It is the lowest line of each page, so it was taken for a running head on both and deleted: "The next
    command is The signal has been checked." Nothing in a page's body is furniture now, however often it repeats."""
    page_lines = [(80, "The signal has been checked.", 11), (96, "The next command is", 11), (160, word, 11)]
    text = pdf_extractor.extract_text_from_pdf(str(placed_pdf(tmp_path, "repeated-body", [page_lines, page_lines])))
    assert words(text) == words(f"The signal has been checked. The next command is {word} " * 2)


def test_a_repeated_body_word_is_read_while_the_running_head_and_page_numbers_in_the_margins_are_not(tmp_path):
    """The positive control beside it: the same book page as the rest of this module, with its running head and number
    in the margins and a word of the text standing alone further down, at the same height on both pages."""
    def leaf(number: int):
        return [(HEAD_Y, "IV", 9), (BODY_TOP, "The signal has been checked", 11), (BODY_TOP + LINE_STEP, "twice over, and", 11),
                (BODY_TOP + 2 * LINE_STEP, "the next command is", 11), (BODY_TOP + 3 * LINE_STEP, "always", 11),
                (BODY_TOP + 7 * LINE_STEP, "NOT", 11), (FOOT_Y, str(number), 9)]
    path = placed_pdf(tmp_path, "head-body-number", [leaf(12), leaf(13)], width=PAGE_WIDTH, height=PAGE_HEIGHT)
    text = pdf_extractor.extract_text_from_pdf(str(path))
    assert words(text) == words("The signal has been checked twice over, and the next command is always NOT " * 2)


def test_capitals_in_the_bottom_margin_that_a_sentence_runs_into_are_read_and_a_running_head_there_is_not(tmp_path):
    """At the foot of the page, where a running head can stand, a line of capitals that the sentence above it runs into
    (that line does not end) is that sentence's word. The control: the same capitals under a finished sentence, at the
    same height on two pages, are the running head, and are taken out as before."""
    runs_on = narration(tmp_path, "foot-word", page(["The next command is"], number="NOT"),
                        page(["The next command is"], number="NOT"))
    assert words(runs_on) == words("The next command is NOT The next command is NOT")
    finished = narration(tmp_path, "foot-head", page(["The command was checked."], number="IV"),
                         page(["The command was checked."], number="IV"))
    assert words(finished) == words("The command was checked. The command was checked.")


# The Phase 9 focused closure review's geometry (R9-01, ACT72-070): PyMuPDF's default page, a line of text at y=620 and a
# bare number at y=750, inside the foot margin and clear of the text. Each case below changes one thing only.
def foot_numbers(folder: Path, name: str, lines: list[str], numbers: list[str], size: float = 11) -> str:
    pages = [[(620, line, 11), (750, number, size)] for line, number in zip(lines, numbers)]
    return pdf_extractor.extract_text_from_pdf(str(placed_pdf(folder, name, pages)))


@pytest.mark.parametrize("numbers", [["1984", "1985"], ["42", "43"], ["1984", "1985", "1986"]],
                         ids=["the-reviewers-codes", "an-answer", "three-pages"])
def test_numbers_that_sentences_run_into_are_read_even_when_they_count_with_their_pages(tmp_path, numbers):
    """The review's reproduction: "The required access code is" with its code under it, 1984 on one page and 1985 on the
    next. The codes count up exactly as page numbers would, so both were taken out. Each sentence runs into its number
    and each number is set as the text is: nothing marks them as the pages' rather than the sentences', so they are read."""
    text = foot_numbers(tmp_path, "codes", ["The required access code is"] * len(numbers), numbers)
    assert words(text) == [word for number in numbers for word in ["The", "required", "access", "code", "is", number]]


def test_numbers_that_do_not_count_with_their_pages_are_read_in_the_same_place(tmp_path):
    """The review's own control: 1984 and 9001 do not count with their pages, so they were never page numbers."""
    text = foot_numbers(tmp_path, "not-counting", ["The required access code is"] * 2, ["1984", "9001"])
    assert words(text) == words("The required access code is 1984 The required access code is 9001")


@pytest.mark.parametrize("lines, size", [
    (["The page ends here.", "So does this one."], 11),
    (["The required access code is", "So does this one."], 11),
    (["The required access code is", "The required access code is"], 9),
], ids=["under-finished-sentences", "one-page-under-a-finished-sentence", "set-smaller-than-the-text"])
def test_page_numbers_in_the_same_place_are_still_taken_out(tmp_path, lines, size):
    """Printed page numbers 198 and 199 in the very place of the codes above, and they are taken out: one of them stands
    apart from the text, under a finished sentence, or both are set smaller than the text, as a page number is."""
    text = foot_numbers(tmp_path, "folios", lines, ["198", "199"], size=size)
    assert words(text) == words(" ".join(lines))


def test_a_running_head_and_page_numbers_beside_numbers_of_the_text_are_told_apart(tmp_path):
    """A book page with its running head and its page number in the margins, an unfinished sentence ending the text, and
    on the next page a year the text names: the head and the numbers go, the year stays."""
    def leaf(number: int, last: str):
        return [(HEAD_Y, "IV", 9), (BODY_TOP, "The keeper wrote the year down", 11), (BODY_TOP + LINE_STEP, last, 11),
                (FOOT_Y, str(number), 9)]
    path = placed_pdf(tmp_path, "head-numbers-year", [leaf(198, "and the code beside"), leaf(199, "it: 1984.")],
                      width=PAGE_WIDTH, height=PAGE_HEIGHT)
    text = pdf_extractor.extract_text_from_pdf(str(path))
    assert words(text) == words("The keeper wrote the year down and the code beside The keeper wrote the year down it: 1984.")


def test_ambiguous_a_year_alone_in_the_foot_margin_under_finished_sentences_is_taken_for_a_page_number(tmp_path):
    """Stated, not solved: a bare number alone in the foot margin, under a finished sentence, counting with the next
    page's, is a page number by every mark the page carries, and is taken out even when it was meant as a year. The same
    years that do not count with their pages are read. Nothing on the pages tells the first case from a book's page
    numbers; preserving it would mean reading every book's page numbers aloud (v0.7.2 Phase 9 focused closure)."""
    taken = foot_numbers(tmp_path, "year-folio", ["The vault was sealed."] * 2, ["1984", "1985"])
    assert words(taken) == words("The vault was sealed. The vault was sealed.")
    kept = foot_numbers(tmp_path, "year-text", ["The vault was sealed."] * 2, ["1984", "1990"])
    assert words(kept) == words("The vault was sealed. 1984 The vault was sealed. 1990")


# --------------------------------------------------------------------------- #
# What must not be joined
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("heading", ["THE STORM", "The Long Night", "Chapter 52: Minefield", "Prologue 1"],
                         ids=["capitals", "title-case", "chapter-with-a-colon", "numbered-prologue"])
def test_a_heading_is_never_run_into_the_text_under_it(tmp_path, heading):
    text = narration(tmp_path, "heading", page([heading, "The wind rose after dark.", "Nobody slept."]))
    assert text.split("\n") == [heading, "The wind rose after dark.", "Nobody slept."]


def test_a_heading_under_an_unfinished_line_stays_a_heading_when_a_new_sentence_follows_it(tmp_path):
    """The capitals are joined into a sentence only when the sentence visibly runs through them: the line after them
    carries on in a small letter. Here a new sentence starts under them, so they stay a heading."""
    text = narration(tmp_path, "heading-after-list", page(["Oil, rope and a second lantern", "THE STORM", "The wind rose after dark."]))
    assert text.split("\n") == ["Oil, rope and a second lantern", "THE STORM", "The wind rose after dark."]


def test_a_line_after_a_colon_or_a_closing_quote_starts_on_its_own(tmp_path):
    text = narration(tmp_path, "colon-quote", page([
        "He read the list aloud:",
        "oil, rope and a second lantern.",
        '"Is that all?"',
        "It was."]))
    assert text.split("\n") == ["He read the list aloud:", "oil, rope and a second lantern.", '"Is that all?"', "It was."]


# --------------------------------------------------------------------------- #
# The evidence itself, at its edges
# --------------------------------------------------------------------------- #


def edge(page_index: int, text: str, at: float = FOOT_Y, line: int = 0):
    return pdf_extractor._EdgeLine(page_index, line, text, at)


def test_a_bare_number_is_a_page_number_only_when_another_page_counts_with_it():
    furniture = pdf_extractor._furniture
    assert furniture([edge(0, "12"), edge(1, "13")]) == {0: {0}, 1: {0}}
    assert furniture([edge(4, "12"), edge(9, "17")]) == {4: {0}, 9: {0}}, "pages apart count by the distance between them"
    assert furniture([edge(0, "12")]) == {}, "one number alone proves nothing"
    assert furniture([edge(0, "12"), edge(1, "12")]) == {}, "the same number twice is not a count"
    assert furniture([edge(0, "12"), edge(1, "14")]) == {}, "two numbers that do not count with their pages"
    assert furniture([edge(0, "12"), edge(1, "14"), edge(2, "15")]) == {1: {0}, 2: {0}}, "the one that does not count stays text"
    assert furniture([edge(0, "1984"), edge(1, "1985")]) == {0: {0}, 1: {0}}, \
        "two edge lines that count with their pages are page numbers to anyone looking at the pages: a known limit of the rule"
    assert furniture([edge(0, "1234567"), edge(1, "1234568")]) == {}, "seven digits are not a page number"
    assert furniture([edge(0, "12 crates"), edge(1, "13 crates")]) == {}, "a line with words is never one"


def test_short_capitals_are_a_running_head_only_when_the_same_word_stands_at_the_same_height_on_another_page():
    furniture = pdf_extractor._furniture
    assert furniture([edge(0, "IV", HEAD_Y), edge(1, "IV", HEAD_Y)]) == {0: {0}, 1: {0}}
    assert furniture([edge(0, "IV", HEAD_Y), edge(1, "IV", HEAD_Y + 1.5)]) == {0: {0}, 1: {0}}, "a point or two apart is one height"
    assert furniture([edge(0, "IV", HEAD_Y)]) == {}
    assert furniture([edge(0, "IV", HEAD_Y), edge(1, "CH", HEAD_Y)]) == {}, "two different words are two headings"
    assert furniture([edge(0, "IV", HEAD_Y), edge(1, "IV", 300.0)]) == {}, "the same word somewhere else on the page"
    assert furniture([edge(0, "IV", HEAD_Y), edge(0, "IV", HEAD_Y, line=3)]) == {}, "twice on one page is not another page"
    assert furniture([edge(0, "NASAS", HEAD_Y), edge(1, "NASAS", HEAD_Y)]) == {}, "five capitals are not a short head"
    assert furniture([edge(0, "The Storm", HEAD_Y), edge(1, "The Storm", HEAD_Y)]) == {}, "a longer head is not taken out (a stated limit)"


def test_only_a_line_that_stands_clear_at_the_top_or_bottom_of_its_page_can_be_furniture(tmp_path):
    """The geometry, read from real pages: which lines the extractor will even consider."""
    path = make_pdf(
        tmp_path, "edges",
        page(["The keeper climbed the narrow stairs and the door", "stood", "open"], head="IV", number=12),
        page(["The safe opens with the code", "1984"]),
        page([], number=14),
        page(["One line only."]))
    with fitz.open(path) as document:
        found = [pdf_extractor._read_page(sheet, index) for index, sheet in enumerate(document)]
    assert [(line.text, line.line, round(line.at)) for line in found[0][1]] == [("IV", 0, HEAD_Y), ("12", 4, FOOT_Y)]
    assert found[1][1] == [], "a number at the text's own spacing under the line before it is a line of the text"
    assert [(line.text, round(line.at)) for line in found[2][1]] == [("14", FOOT_Y)], "a leaf that holds only its number"
    # Alone on its page, but where the page's text is printed, not in its margin: not even a candidate (R9-01). Until the
    # remote re-review it was one, and only its not repeating kept it.
    assert found[3][1] == [], "a line in the body of the page is never furniture"
    assert [raw for raw, _edges in found] == [expected_raw(spec) for spec in (
        page(["The keeper climbed the narrow stairs and the door", "stood", "open"], head="IV", number=12),
        page(["The safe opens with the code", "1984"]), page([], number=14), page(["One line only."]))], \
        "the text itself is what get_text('text') always gave"


def test_without_the_pages_geometry_nothing_is_taken_for_furniture():
    """No layout, or a layout whose lines are not the text's lines: every line is kept."""
    raw = "12\nThe door stood open.\n"
    assert pdf_extractor._edge_lines(0, raw, None) == []
    assert pdf_extractor._edge_lines(0, raw, {"blocks": []}) == []
    other = {"blocks": [{"type": 0, "lines": [{"bbox": (0, 30, 9, 42), "dir": (1.0, 0.0),
                                               "spans": [{"text": "13", "size": 9.0, "origin": (0, 40)}]}]}]}
    assert pdf_extractor._edge_lines(0, raw, other) == []
    assert pdf_extractor._clean_page_text(raw) == "12 The door stood open."


def test_only_a_page_that_ends_in_a_hyphen_is_joined_to_the_next_page_without_a_space():
    join = pdf_extractor._join_words_split_across_pages
    assert join(["before the morn-", "ing light.", "A new page."]) == ["before the morning light.", "A new page."]
    assert join(["It ended.", "Another began."]) == ["It ended.", "Another began."]
    assert join(["one-", "two-", "three"]) == ["onetwothree"], "a word may be carried more than once"
    assert join(["only-"]) == ["only-"] and join([]) == []
    assert join(["from 1939-", "1945 on."]) == ["from 1939-1945 on."], "a range keeps its hyphen across the page too"
    assert join(["an Anglo-", "Saxon copy."]) == ["an Anglo-Saxon copy."]
    assert join(["he said -", "and left."]) == ["he said -", "and left."], "a dash is no word's hyphen: the pages stay two"


def test_a_hyphen_at_a_line_end_is_dropped_only_from_a_word_that_carries_on_in_a_small_letter():
    mend = pdf_extractor._dehyphenate
    assert mend("impor-\ntant") == "important" and mend("impor- \n  tant") == "important"
    assert mend("a-\nb-\nc") == "abc", "one word broken twice"
    assert mend("1939-\n1945") == "1939-1945" and mend("20-\nyear") == "20-year" and mend("page-\n3") == "page-3"
    assert mend("Anglo-\nSaxon") == "Anglo-Saxon"
    assert mend("he said -\nand left") == "he said -\nand left", "a dash with a space before it is left for the line join"
    assert mend("no hyphen\nhere") == "no hyphen\nhere"


# --------------------------------------------------------------------------- #
# Sizing reads what a conversion reads
# --------------------------------------------------------------------------- #


def test_sizing_cleans_a_pdf_exactly_as_the_conversion_does(tmp_path):
    """Worker sizing reads PDFs through ``pdf_text_sample``. It must take out the same furniture and keep the same text."""
    pages = (page(["The lamp was supplied by", "NASA", "in 1969 and the safe opens with the code", "1984"], head="CH", number=7),
             page(["and closes when the handle turns."], head="CH", number=8),
             page(["The signal is", "NOT", "a command to open it."], head="CH", number=9))
    path = make_pdf(tmp_path, "sized", *pages)
    count, read, sample = pdf_extractor.pdf_text_sample(str(path), 50)
    assert (count, read) == (3, 3)
    assert sample == pdf_extractor.extract_text_from_pdf(str(path)) == (
        "The lamp was supplied by NASA in 1969 and the safe opens with the code 1984 and closes when the handle turns.\n\n"
        "The signal is NOT a command to open it.")


def test_sizing_a_sample_of_a_long_pdf_still_knows_its_page_numbers(tmp_path):
    """Only some pages are read, evenly spread. Their numbers still differ by the distance between the pages read."""
    path = make_pdf(tmp_path, "long", *(page([f"Page {index} of the story runs on and"], number=101 + index) for index in range(12)))
    count, read, sample = pdf_extractor.pdf_text_sample(str(path), 4)
    assert (count, read) == (12, 4)
    assert sample == "Page 0 of the story runs on and Page 3 of the story runs on and Page 6 of the story runs on and Page 9 of the story runs on and"


def test_a_long_book_is_read_whole_with_every_head_and_number_taken_out(tmp_path):
    """Three hundred pages, each with the chapter's running head, its number and two lines that run on to the next."""
    count = 300
    pages = [page([f"leaf {index} begins and", "runs on to"], head="IV", number=index + 1) for index in range(count)]
    text = narration(tmp_path, "book", *pages)
    assert text == " ".join(f"leaf {index} begins and runs on to" for index in range(count))


# --------------------------------------------------------------------------- #
# The limits that remain, stated (ACT72-064: for the owner)
# --------------------------------------------------------------------------- #
# In each of these, something is read out that a listener might not want, or a word comes out oddly. In none of them is
# a word of the text lost: that is the line Phase 9 drew, and why these are limits and not defects. Each is here by name
# so that nobody mistakes it for covered behaviour and so that changing one is a decision.


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
    """A hyphen at a line end before a small letter is taken for a broken word; nothing can tell "well-known" from
    "impor-tant". Both halves are read; only the hyphen is gone."""
    text = narration(tmp_path, "compound", page(["He was a well-", "known keeper of twenty-", "three years."]))
    assert text == "He was a wellknown keeper of twentythree years."


def test_limit_a_page_number_or_running_head_that_nothing_repeats_is_read_out(tmp_path):
    """A one-page document's number, and a head or number that stands on one page only: nothing counts with it, so it is
    text. The price of never deleting a line on its shape alone."""
    one_page = narration(tmp_path, "one-page", page(["The keeper lit the lamp."], head="IV", number=7))
    assert one_page.split("\n") == ["IV", "The keeper lit the lamp.", "7"]
    skipped = narration(
        tmp_path, "one-off",
        page(["The first page ends."], number=12),
        page(["The second page ends."], number=14))
    assert words(skipped) == words("The first page ends. 12 The second page ends. 14")


def test_limit_a_drop_capital_set_on_a_line_of_its_own_is_read_as_a_letter_by_itself(tmp_path):
    """A chapter's large first letter, which the page holds as a piece of text of its own. Until Phase 9 it was deleted
    with every short line of capitals, so the chapter began "he wind rose"; now the letter is read, apart from its word."""
    text = narration(tmp_path, "drop-capital", page(["T", "he wind rose after dark."]))
    assert text.split("\n") == ["T", "he wind rose after dark."]


def test_limit_capitals_at_the_very_end_or_start_of_a_page_keep_a_line_break_inside_their_sentence(tmp_path):
    """Whether a sentence runs through a line of capitals is read from the line after it on the same page. When the page
    ends or begins with the capitals there is no such line: every word is read, with a pause where the page turned."""
    at_the_end = narration(tmp_path, "caps-end", page(["The signal is", "NOT"]), page(["a command to open it."]))
    assert at_the_end.split("\n") == ["The signal is", "NOT a command to open it."]
    at_the_start = narration(tmp_path, "caps-start", page(["The signal is"]), page(["NOT", "a command to open it."]))
    assert at_the_start.split("\n") == ["The signal is NOT", "a command to open it."]
