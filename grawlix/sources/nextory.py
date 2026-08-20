from grawlix.book import Book, Metadata, OnlineFile, BookData, OnlineFile, SingleFile, EpubInParts, Result, Series
from grawlix.encryption import AESEncryption
from grawlix.exceptions import InvalidUrl
from .source import Source

from datetime import date
from typing import Optional
import uuid
import rich
import base64

LOCALE = "en_GB"

class Nextory(Source):
    name: str = "Nextory"
    match = [
        r"https?://((www|catalog-\w\w).)?nextory.+"
    ]
    _authentication_methods = [ "login" ]


    @staticmethod
    def _create_device_id() -> str:
        """Create unique device id"""
        return str(uuid.uuid3(uuid.NAMESPACE_DNS, "audiobook-dl"))


    async def login(self, url: str, username: str, password: str) -> None:
        # Set permanent headers
        device_id = self._create_device_id()
        self._client.headers.update(
            {
                "X-Application-Id": "200",
                "X-App-Version": "2026.05.4",
                "X-Locale": LOCALE,
                "X-Model": "Personal Computer",
                "X-Device-Id": device_id,
                "X-Os-Info": "Android",
                "appid": "200",
            }
        )
        # Login for account
        session_response = await self._client.post(
            "https://api.nextory.com/user/v1/sessions",
            json = {
                "identifier": username,
                "password": password
            },
        )
        session_response = session_response.json()
        rich.print(session_response)
        login_token = session_response["login_token"]
        country = session_response["country"]
        self._client.headers.update(
            {
                "token": login_token,
                "X-Login-Token": login_token,
                "X-Country-Code": country,
            }
        )
        # Login for user
        profiles_response = await self._client.get(
            "https://api.nextory.com/user/v1/me/profiles",
        )
        profiles_response = profiles_response.json()
        rich.print(profiles_response)
        profile = profiles_response["profiles"][0]
        login_key = profile["login_key"]
        authorize_response = await self._client.post(
            "https://api.nextory.com/user/v1/profile/authorize",
            json = {
                "login_key": login_key
            }
        )
        authorize_response = authorize_response.json()
        rich.print(authorize_response)
        profile_token = authorize_response["profile_token"]
        self._client.headers.update({"X-Profile-Token": profile_token})
        self._client.headers.update({"X-Profile-Token": profile_token})


    @staticmethod
    def _find_epub_format(product_data: dict) -> dict:
        """Find the EPUB format metadata for a product."""
        for format in product_data["formats"]:
            if format["type"] == "epub":
                return format
        raise InvalidUrl


    @classmethod
    def _find_epub_id(cls, product_data: dict) -> str:
        """Find id of book format of type epub for given book"""
        return cls._find_epub_format(product_data)["identifier"]


    @staticmethod
    def _extract_id_from_url(url: str) -> str:
        """
        Extract id of book from url. This id is not always the internal id for
        the book.

        :param url: Url to book information page
        :return: Id in url
        """
        return url.split("-")[-1].replace("/", "")


    async def download(self, url: str) -> Result:
        url_id = self._extract_id_from_url(url)
        if "serier" in url:
            return await self._download_series(url_id)
        else:
            return await self._download_book(url_id)


    async def download_book_from_id(self, book_id: str) -> Book:
        return await self._download_book(book_id)


    async def _download_series(self, series_id: str) -> Series:
        """
        Download series from Nextory

        :param series_id: Id of series on Nextory
        :returns: Series data
        """
        response = await self._client.get(
            f"https://api.nextory.com/discovery/v1/series/{series_id}/products",
            params = {
                "content_type": "book",
                "page": 0,
                "per": 100,
            }
        )
        series_data = response.json()
        book_ids = []
        for book in series_data["products"]:
            book_id = book["id"]
            book_ids.append(book_id)
        return Series(
            title = series_data["products"][0]["series"]["name"],
            book_ids = book_ids,
        )


    @staticmethod
    def _extract_series_name(product_info: dict) -> Optional[str]:
        series = product_info.get("series")
        if not isinstance(series, dict):
            return None
        return series.get("name")


    @staticmethod
    def _extract_series_index(product_info: dict) -> int | float | str | None:
        # Nextory exposes the actual position in the series as a top-level
        # volume. The value inside the series object is an internal grouping.
        raw_volume = product_info.get("volume")
        if raw_volume is not None:
            try:
                volume = int(raw_volume)
                if volume > 0:
                    return volume
            except (TypeError, ValueError):
                pass
        series = product_info.get("series")
        if isinstance(series, dict):
            for key in ("position", "orderInSeries", "order", "number", "sequence", "index"):
                if series.get(key) is not None:
                    return series[key]
        for key in ("seriesPosition", "orderInSeries", "series_order", "series_index"):
            if product_info.get(key) is not None:
                return product_info[key]
        return None


    @staticmethod
    def _extract_description(product_info: dict) -> Optional[str]:
        description = (
            product_info.get("description_full")
            or product_info.get("description")
            or product_info.get("summary")
        )
        if isinstance(description, str):
            return description
        if isinstance(description, dict):
            for key in ("text", "value", "content", "html"):
                if isinstance(description.get(key), str):
                    return description[key]
        return None


    @staticmethod
    def _extract_publisher(format_info: dict) -> Optional[str]:
        publisher = format_info.get("publisher")
        if isinstance(publisher, str):
            return publisher
        if isinstance(publisher, dict) and isinstance(publisher.get("name"), str):
            return publisher["name"]
        return None


    @staticmethod
    def _extract_release_date(format_info: dict) -> Optional[date]:
        publication_date = format_info.get("publication_date")
        if not isinstance(publication_date, str):
            return None
        try:
            return date.fromisoformat(publication_date.split("T", 1)[0])
        except ValueError:
            return None


    async def _get_book_id_from_url_id(self, url_id: str) -> str:
        """
        Download book id from url id

        :param url_id: Id of book from url
        :return: Book id
        """
        response = await self._client.get(
            f"https://api.nextory.se/api/app/product/7.5/bookinfo",
            params = { "id": url_id },
        )
        rich.print(response.url)
        rich.print(response.content)
        exit()


    async def _download_book(self, book_id: str) -> Book:
        product_data = await self._client.get(
            f"https://api.nextory.com/library/v1/products/{book_id}"
        )
        product_data = product_data.json()
        epub_format = self._find_epub_format(product_data)
        epub_id = epub_format["identifier"]
        isbn = epub_format.get("isbn") or product_data.get("isbn")
        pages = await self._get_pages(epub_id)
        cover_url = epub_format.get("img_url") or product_data.get("img_url")
        if cover_url:
            pages.cover = OnlineFile(
                url = cover_url,
                extension = "jpg",
                headers = self._client.headers,
            )
        authors = [
            author["name"]
            for author in product_data.get("authors", [])
            if isinstance(author, dict) and author.get("name")
        ]
        return Book(
            data = pages,
            metadata = Metadata(
                title = product_data["title"],
                authors = authors,
                series = self._extract_series_name(product_data),
                index = self._extract_series_index(product_data),
                description = self._extract_description(product_data),
                language = product_data.get("language"),
                publisher = (
                    self._extract_publisher(epub_format)
                    or self._extract_publisher(product_data)
                ),
                identifier = str(isbn) if isbn else None,
                release_date = (
                    self._extract_release_date(epub_format)
                    or self._extract_release_date(product_data)
                ),
            )
        )


    @staticmethod
    def _fix_key(value: str) -> bytes:
        """Remove unused data and decode key"""
        return base64.b64decode(value[:-1])


    async def _get_pages(self, epub_id: str) -> BookData:
        """
        Download page information for book

        :param epub_id: Id of epub file
        :return: Page data
        """
        # Nextory books are for some reason split up into multiple epub files -
        # one for each chapter file. All of these files has to be decrypted and
        # combined afterwards. Many of the provided epub files contain the same
        # files and some of them contain the same file names but with variation
        # in the content and comments that describe what should have been there
        # if the book was whole from the start.
        response = await self._client.get(
            f"https://api.nextory.com/reader/books/{epub_id}/packages/epub"
        )
        epub_data = response.json()
        encryption = AESEncryption(
            key = self._fix_key(epub_data["crypt_key"]),
            iv = self._fix_key(epub_data["crypt_iv"])
        )
        files = []
        for part in epub_data["spines"]:
            files.append(
                OnlineFile(
                    url = part["spine_url"],
                    extension = "epub",
                    encryption = encryption
                )
            )
        files_in_toc = {}
        for item in epub_data["toc"]["childrens"]: # Why is it "childrens"?
            files_in_toc[item["src"]] = item["name"]
        return EpubInParts(
            files,
            files_in_toc
        )
