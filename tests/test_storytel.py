import unittest

from grawlix.sources.storytel import Storytel


class FakeResponse:
    def __init__(self, *, headers=None, payload=None):
        self.headers = headers or {}
        self._payload = payload

    def json(self):
        return self._payload


class FakeClient:
    headers = {"authorization": "Bearer test"}

    async def get(self, url):
        if "/assets/" in url:
            return FakeResponse(headers={"Location": "https://example.invalid/book.epub"})
        return FakeResponse(
            payload={
                "title": "De Zwaluwentoren",
                "authors": [{"name": "Andrzej Sapkowski"}],
                "seriesInfo": {"name": "The Witcher", "orderInSeries": 6},
                "description": "Het zesde boek in de Witcher-serie.",
            }
        )


class StorytelMetadataTests(unittest.IsolatedAsyncioTestCase):
    async def test_download_uses_title_and_series_info_from_book_details(self):
        source = Storytel.__new__(Storytel)
        source._client = FakeClient()

        book = await source.download_book_from_id("123")

        self.assertEqual(book.metadata.title, "De Zwaluwentoren")
        self.assertEqual(book.metadata.authors, ["Andrzej Sapkowski"])
        self.assertEqual(book.metadata.series, "The Witcher")
        self.assertEqual(book.metadata.index, 6)
        self.assertEqual(book.metadata.description, "Het zesde boek in de Witcher-serie.")


if __name__ == "__main__":
    unittest.main()
