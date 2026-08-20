import unittest
from datetime import date
from unittest.mock import AsyncMock

from grawlix.book import EpubInParts
from grawlix.sources.nextory import Nextory


class FakeResponse:
    def json(self):
        return {
            "title": "De Zwaluwentoren",
            "authors": [{"name": "Andrzej Sapkowski"}],
            "series": {"name": "The Witcher", "vol": 0},
            "volume": 6,
            "description_full": "Het zesde boek in de Witcher-serie.",
            "language": "nl",
            "formats": [{
                "type": "epub",
                "identifier": "epub-123",
                "publisher": {"name": "Boekerij"},
                "isbn": "9789022599829",
                "publication_date": "2023-06-15",
            }],
        }


class FakeClient:
    async def get(self, url):
        return FakeResponse()


class NextoryMetadataTests(unittest.IsolatedAsyncioTestCase):
    async def test_download_maps_complete_product_metadata(self):
        source = Nextory.__new__(Nextory)
        source._client = FakeClient()
        source._get_pages = AsyncMock(return_value=EpubInParts(files=[], files_in_toc={}))

        book = await source._download_book("123")

        self.assertEqual(book.metadata.title, "De Zwaluwentoren")
        self.assertEqual(book.metadata.authors, ["Andrzej Sapkowski"])
        self.assertEqual(book.metadata.series, "The Witcher")
        self.assertEqual(book.metadata.index, 6)
        self.assertEqual(book.metadata.description, "Het zesde boek in de Witcher-serie.")
        self.assertEqual(book.metadata.language, "nl")
        self.assertEqual(book.metadata.publisher, "Boekerij")
        self.assertEqual(book.metadata.identifier, "9789022599829")
        self.assertEqual(book.metadata.release_date, date(2023, 6, 15))
        source._get_pages.assert_awaited_once_with("epub-123")

    def test_series_index_accepts_product_level_fallback(self):
        self.assertEqual(Nextory._extract_series_index({"seriesPosition": "6.5"}), "6.5")

    def test_series_index_prefers_nextory_volume(self):
        self.assertEqual(
            Nextory._extract_series_index({"volume": 4, "series": {"position": 99}}),
            4,
        )

    def test_description_accepts_nested_api_value(self):
        self.assertEqual(
            Nextory._extract_description({"description": {"text": "Beschrijving"}}),
            "Beschrijving",
        )


if __name__ == "__main__":
    unittest.main()
