from io import BytesIO
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

from grawlix.book import Book, EpubInParts, HtmlFiles, Metadata, OfflineFile, SingleFile
from grawlix.output.epub import Epub
from grawlix.output.epub_metadata import DC_NS, normalize_epub_metadata

CONTAINER = b"""<?xml version="1.0"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
  <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>
"""


def create_epub(metadata: str) -> bytes:
    opf = f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
  <metadata xmlns:dc="{DC_NS}">{metadata}</metadata>
  <manifest/><spine/>
</package>
""".encode()
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=ZIP_STORED)
        archive.writestr("META-INF/container.xml", CONTAINER, compress_type=ZIP_DEFLATED)
        archive.writestr("OEBPS/content.opf", opf, compress_type=ZIP_DEFLATED)
        archive.writestr("OEBPS/chapter.xhtml", b"<html/>", compress_type=ZIP_DEFLATED)
    return output.getvalue()


def read_metadata(path: Path) -> ET.Element:
    with ZipFile(path) as archive:
        root = ET.fromstring(archive.read("OEBPS/content.opf"))
    return next(element for element in root.iter() if element.tag.endswith("}metadata"))


class EpubMetadataTests(unittest.TestCase):
    def test_normalizes_title_author_and_series(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Andrzej Sapkowski De zwaluwentoren.epub"
            path.write_bytes(
                create_epub(
                    """
                    <dc:title>The Witcher</dc:title>
                    <dc:creator>Wrong author</dc:creator>
                    <meta name="calibre:series" content="The Witcher"/>
                    """
                )
            )

            normalize_epub_metadata(
                path,
                Metadata(
                    title="De Zwaluwentoren",
                    authors=["Andrzej Sapkowski"],
                    series="The Witcher",
                    index=6,
                    description="Het zesde boek in de Witcher-serie.",
                ),
            )

            metadata = read_metadata(path)
            self.assertEqual(
                [element.text for element in metadata.findall(f"{{{DC_NS}}}title")],
                ["De Zwaluwentoren"],
            )
            self.assertEqual(
                [element.text for element in metadata.findall(f"{{{DC_NS}}}creator")],
                ["Andrzej Sapkowski"],
            )
            named_meta = {
                element.get("name"): element.get("content")
                for element in metadata
                if element.tag.endswith("}meta")
            }
            self.assertEqual(named_meta["calibre:series"], "The Witcher")
            self.assertEqual(named_meta["calibre:series_index"], "6")
            self.assertEqual(
                metadata.find(f"{{{DC_NS}}}description").text,
                "Het zesde boek in de Witcher-serie.",
            )
            collection = next(
                element
                for element in metadata
                if element.get("property") == "belongs-to-collection"
            )
            self.assertEqual(collection.text, "The Witcher")
            refinements = {
                element.get("property"): element.text
                for element in metadata
                if element.get("refines") == f"#{collection.get('id')}"
            }
            self.assertEqual(refinements["collection-type"], "series")
            self.assertEqual(refinements["group-position"], "6")

            with ZipFile(path) as archive:
                self.assertEqual(archive.infolist()[0].filename, "mimetype")
                self.assertEqual(archive.infolist()[0].compress_type, ZIP_STORED)
                self.assertEqual(archive.read("OEBPS/chapter.xhtml"), b"<html/>")

    def test_preserves_existing_series_when_source_has_none(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "book.epub"
            path.write_bytes(
                create_epub(
                    """
                    <dc:title>Incorrect title</dc:title>
                    <meta name="calibre:series" content="Existing series"/>
                    """
                )
            )

            normalize_epub_metadata(path, Metadata(title="Correct title"))

            metadata = read_metadata(path)
            series = next(
                element for element in metadata if element.get("name") == "calibre:series"
            )
            self.assertEqual(series.get("content"), "Existing series")


class EpubOutputTests(unittest.IsolatedAsyncioTestCase):
    async def test_single_file_download_is_normalized(self):
        raw_epub = create_epub("<dc:title>The Witcher</dc:title>")
        book = Metadata(
            title="De Zwaluwentoren",
            authors=["Andrzej Sapkowski"],
            series="The Witcher",
        )

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "book.epub"
            output = Epub()
            try:
                await output.download(
                    Book(
                        metadata=book,
                        data=SingleFile(OfflineFile(content=raw_epub, extension="epub")),
                    ),
                    str(path),
                    None,
                )
            finally:
                await output.close()

            metadata = read_metadata(path)
            self.assertEqual(metadata.find(f"{{{DC_NS}}}title").text, "De Zwaluwentoren")

    async def test_generated_epub_paths_are_normalized(self):
        cases = [
            (HtmlFiles(htmlfiles=[]), "_download_html_files"),
            (EpubInParts(files=[], files_in_toc={}), "_download_epub_in_parts"),
        ]
        for data, method_name in cases:
            with self.subTest(data=type(data).__name__):
                output = Epub()
                method = AsyncMock()
                setattr(output, method_name, method)
                metadata = Metadata(title="Correct title", series="Correct series")
                try:
                    with patch("grawlix.output.epub.normalize_epub_metadata") as normalize:
                        await output.download(Book(metadata=metadata, data=data), "book.epub", None)
                finally:
                    await output.close()

                method.assert_awaited_once()
                normalize.assert_called_once_with("book.epub", metadata)


class MetadataTests(unittest.TestCase):
    def test_series_index_is_safe_for_output_templates(self):
        self.assertEqual(Metadata(title="Book", index=6).as_dict()["index"], "6")


if __name__ == "__main__":
    unittest.main()
