"""EPUB-exclusive functions extracted from ``scripts/Universal/tts/epub2tts_edge/epub2tts_edge.py``.

Preserved verbatim from commit 3d9de97e7befc27fa22210bdcc27f174aa594883, the final
commit in which EPUB was an active application input. Reference material only:
this file is never imported, never packaged and never collected as tests.

Original module: scripts/Universal/tts/epub2tts_edge/epub2tts_edge.py
Retirement:      v0.6.1 Plan 4 Phase 5 (maintainer decision, 2026-08-11).
Licence:         GPL-3.0, inherited from epub2tts-edge by Christopher Aedo
                 (https://github.com/aedocw/epub2tts-edge). The surviving Edge
                 synthesis engine in production is the same derivation, so the
                 attribution obligation applies there as well as here.

The remainder of the original module — the whole Edge synthesis engine used by
PDF and TXT — stayed in production and is NOT reproduced here.
"""

# ruff: noqa
# Original imports these functions depended on, at their original spellings:
#     import os, re, sys, warnings, zipfile
#     import ebooklib
#     from ebooklib import epub
#     from bs4 import BeautifulSoup
#     from lxml import etree
#     from PIL import Image
#
# Original module-level side effect, removed from production with these functions:
#     warnings.filterwarnings("ignore", module="ebooklib.epub")

namespaces = {
   "calibre":"http://calibre.kovidgoyal.net/2009/metadata",
   "dc":"http://purl.org/dc/elements/1.1/",
   "dcterms":"http://purl.org/dc/terms/",
   "opf":"http://www.idpf.org/2007/opf",
   "u":"urn:oasis:names:tc:opendocument:xmlns:container",
   "xsi":"http://www.w3.org/2001/XMLSchema-instance",
}

def chap2text_epub(chap):
    blacklist = [
        "[document]",
        "noscript",
        "header",
        "html",
        "meta",
        "head",
        "input",
        "script",
    ]
    paragraphs = []
    soup = BeautifulSoup(chap, "html.parser")

    # Extract chapter title (assuming it's in an <h1> tag)
    chapter_title = soup.find("h1")
    if chapter_title:
        chapter_title_text = chapter_title.text.strip()
    else:
        chapter_title_text = None

    # Always skip reading links that are just a number (footnotes)
    for a in soup.findAll("a", href=True):
        if not any(char.isalpha() for char in a.text):
            a.extract()

    chapter_paragraphs = soup.find_all("p")
    if len(chapter_paragraphs) == 0:
        print(f"Could not find any paragraph tags <p> in \"{chapter_title_text}\". Trying with <div>.")
        chapter_paragraphs = soup.find_all("div")

    for p in chapter_paragraphs:
        paragraph_text = "".join(p.strings).strip()
        paragraphs.append(paragraph_text)

    return chapter_title_text, paragraphs

def get_epub_cover(epub_path):
    try:
        with zipfile.ZipFile(epub_path) as z:
            t = etree.fromstring(z.read("META-INF/container.xml"))
            rootfile_path =  t.xpath("/u:container/u:rootfiles/u:rootfile",
                                        namespaces=namespaces)[0].get("full-path")

            t = etree.fromstring(z.read(rootfile_path))
            cover_meta = t.xpath("//opf:metadata/opf:meta[@name='cover']",
                                        namespaces=namespaces)
            if not cover_meta:
                print("No cover image found.")
                return None
            cover_id = cover_meta[0].get("content")

            cover_item = t.xpath("//opf:manifest/opf:item[@id='" + cover_id + "']",
                                            namespaces=namespaces)
            if not cover_item:
                print("No cover image found.")
                return None
            cover_href = cover_item[0].get("href")
            cover_path = os.path.join(os.path.dirname(rootfile_path), cover_href)
            if os.name == 'nt' and '\\' in cover_path:
                cover_path = cover_path.replace("\\", "/")
            return z.open(cover_path)
    except FileNotFoundError:
        print(f"Could not get cover image of {epub_path}")

def export(book, sourcefile, overwrite=False):
    book_contents = []
    cover_image = get_epub_cover(sourcefile)
    image_path = None

    if cover_image is not None:
        image = Image.open(cover_image)
        image_filename = sourcefile.replace(".epub", ".png")
        image_path = os.path.join(image_filename)
        image.save(image_path)
        print(f"Cover image saved to {image_path}")

    spine_ids = []
    for spine_tuple in book.spine:
        if spine_tuple[1] == 'yes': # if item in spine is linear
            spine_ids.append(spine_tuple[0])

    items = {}
    for item in book.get_items():
        if item.get_type() == ebooklib.ITEM_DOCUMENT:
            items[item.get_id()] = item

    for id in spine_ids:
        item = items.get(id, None)
        if item is None:
            continue
        chapter_title, chapter_paragraphs = chap2text_epub(item.get_content())
        book_contents.append({"title": chapter_title, "paragraphs": chapter_paragraphs})
    outfile = sourcefile.replace(".epub", ".txt")
    check_for_file(outfile, overwrite=overwrite)
    print(f"Exporting {sourcefile} to {outfile}")
    author = book.get_metadata("DC", "creator")[0][0]
    booktitle = book.get_metadata("DC", "title")[0][0]

    with open(outfile, "w", encoding='utf-8') as file:
        file.write(f"Title: {booktitle}\n")
        file.write(f"Author: {author}\n\n")

        file.write(f"# Title\n")
        file.write(f"{booktitle}, by {author}\n\n")
        for i, chapter in enumerate(book_contents, start=1):
            if chapter["paragraphs"] == [] or chapter["paragraphs"] == ['']:
                continue
            else:
                if chapter["title"] == None:
                    file.write(f"# Part {i}\n")
                else:
                    file.write(f"# {chapter['title']}\n\n")
                for paragraph in chapter["paragraphs"]:
                    clean = re.sub(r'[\s\n]+', ' ', paragraph)
                    clean = re.sub(r'[“”]', '"', clean)  # Curly double quotes to standard double quotes
                    clean = re.sub(r'[‘’]', "'", clean)  # Curly single quotes to standard single quotes
                    file.write(f"{clean}\n\n")

# ``check_for_file`` had exactly one caller — ``export`` above — so it is retired
# with it. It is preserved here unchanged.
def check_for_file(filename, overwrite=False):
    if os.path.isfile(filename):
        if overwrite:
            os.remove(filename)
        else:
            print(f"The file '{filename}' already exists.")
            ans = input("Do you want to overwrite the file? (y/n): ")
            if ans.lower() != "y":
                print("Exiting without overwriting the file.")
                sys.exit()
            else:
                os.remove(filename)


# --------------------------------------------------------------------------- #
# The CLI surfaces removed from ``main()`` in the same module.
# --------------------------------------------------------------------------- #
#
# The `sourcefile` help string (epub2tts_edge.py:669) was:
#        help="EPUB, PDF, or TXT file to process",
# and is now "PDF or TXT file to process".
#
# The removed argument (epub2tts_edge.py:769-773):
#        parser.add_argument(
#            "--epub-convert",
#            action="store_true",
#            help="With .epub input, export to text and continue to audio
#                  (default: export txt only)",
#        )
#
# The removed keyword at the `run_conversion_job(...)` call site (:802):
#        epub_convert=args.epub_convert,


def _archived_cli_epub_export_shortcut(args, epub, export, sys):
    """epub2tts_edge.py:780-783 — the pre-retirement CLI early exit, verbatim."""
    if args.sourcefile.endswith(".epub") and not args.epub_convert:
        book = epub.read_epub(args.sourcefile)
        export(book, args.sourcefile, overwrite=args.overwrite)
        sys.exit(0)
