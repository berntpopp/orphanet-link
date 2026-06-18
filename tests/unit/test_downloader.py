"""Unit tests for the conditional Orphadata downloader (respx-mocked)."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from orphanet_link.config import OrphanetDataConfig
from orphanet_link.exceptions import DownloadError
from orphanet_link.ingest import downloader
from orphanet_link.ingest.downloader import BulkDownload, download_file, download_files


@pytest.fixture
def config(tmp_path: Path) -> OrphanetDataConfig:
    return OrphanetDataConfig(
        data_dir=tmp_path,
        base_url="https://www.orphadata.com/data/xml/",
    )


def _url(config: OrphanetDataConfig, filename: str) -> str:
    return config.base_url + filename


# ---------------------------------------------------------------------------
# download_file
# ---------------------------------------------------------------------------


@respx.mock
def test_download_file_200_stores_file(config: OrphanetDataConfig) -> None:
    filename = "en_product1.xml"
    url = _url(config, filename)
    respx.get(url).mock(
        return_value=httpx.Response(
            200,
            text="<JDBOR/>",
            headers={
                "ETag": '"v1"',
                "Last-Modified": "Mon, 01 Jun 2026 00:00:00 GMT",
                "Content-Length": "8",
            },
        )
    )
    res = download_file(config, "product1", filename)

    assert res.not_modified is False
    assert res.path is not None
    assert res.path.exists()
    assert res.path.name == filename
    assert res.etag == '"v1"'
    assert res.content_length == 8


@respx.mock
def test_download_file_304_reuses_cached(config: OrphanetDataConfig) -> None:
    filename = "en_product1.xml"
    url = _url(config, filename)

    # First call: seed cache with ETag.
    respx.get(url).mock(
        return_value=httpx.Response(
            200,
            text="<JDBOR/>",
            headers={"ETag": '"v1"', "Last-Modified": "Mon, 01 Jun 2026 00:00:00 GMT"},
        )
    )
    res1 = download_file(config, "product1", filename)
    assert res1.not_modified is False
    assert res1.path is not None and res1.path.exists()

    # Second call: server returns 304.
    respx.get(url).mock(return_value=httpx.Response(304))
    res2 = download_file(config, "product1", filename)

    assert res2.not_modified is True
    assert res2.path is not None and res2.path.exists()


@respx.mock
def test_download_file_500_raises_download_error(config: OrphanetDataConfig) -> None:
    filename = "en_product1.xml"
    url = _url(config, filename)
    respx.get(url).mock(return_value=httpx.Response(500))

    with pytest.raises(DownloadError, match="500"):
        download_file(config, "product1", filename)


@respx.mock
def test_download_file_404_raises_download_error(config: OrphanetDataConfig) -> None:
    filename = "en_product1.xml"
    url = _url(config, filename)
    respx.get(url).mock(return_value=httpx.Response(404))

    with pytest.raises(DownloadError):
        download_file(config, "product1", filename)


@respx.mock
def test_download_file_force_skips_cache(config: OrphanetDataConfig) -> None:
    filename = "en_product1.xml"
    url = _url(config, filename)

    # Seed the cache.
    respx.get(url).mock(
        return_value=httpx.Response(
            200, text="v1", headers={"ETag": '"v1"'}
        )
    )
    download_file(config, "product1", filename)

    # With force=True no conditional headers are sent; server returns 200 again.
    respx.get(url).mock(
        return_value=httpx.Response(
            200, text="v2", headers={"ETag": '"v2"'}
        )
    )
    res = download_file(config, "product1", filename, force=True)
    assert res.not_modified is False
    assert res.etag == '"v2"'


# ---------------------------------------------------------------------------
# download_files (BulkDownload)
# ---------------------------------------------------------------------------


@respx.mock
def test_download_files_multiple_products(config: OrphanetDataConfig) -> None:
    files = {
        "product1": "en_product1.xml",
        "product4": "en_product4.xml",
    }
    for fname in files.values():
        respx.get(_url(config, fname)).mock(
            return_value=httpx.Response(200, text="<JDBOR/>", headers={"ETag": f'"{fname}"'})
        )

    bulk = download_files(config, files)
    assert isinstance(bulk, BulkDownload)
    assert bulk.not_modified is False
    assert bulk.path("product1") is not None
    assert bulk.path("product4") is not None


@respx.mock
def test_download_files_all_304_not_modified(config: OrphanetDataConfig) -> None:
    files = {
        "product1": "en_product1.xml",
        "product4": "en_product4.xml",
    }
    # Seed cache.
    for fname in files.values():
        respx.get(_url(config, fname)).mock(
            return_value=httpx.Response(200, text="x", headers={"ETag": f'"{fname}"'})
        )
    download_files(config, files)

    # Now everything 304s.
    for fname in files.values():
        respx.get(_url(config, fname)).mock(return_value=httpx.Response(304))
    bulk = download_files(config, files)

    assert bulk.not_modified is True


@respx.mock
def test_download_files_required_500_raises(config: OrphanetDataConfig) -> None:
    files = {"product1": "en_product1.xml"}
    respx.get(_url(config, "en_product1.xml")).mock(return_value=httpx.Response(500))

    with pytest.raises(DownloadError):
        download_files(config, files)


@respx.mock
def test_download_files_optional_404_degrades(config: OrphanetDataConfig) -> None:
    files = {
        "product1": "en_product1.xml",
        "product3_156": "en_product3_156.xml",
    }
    respx.get(_url(config, "en_product1.xml")).mock(
        return_value=httpx.Response(200, text="<JDBOR/>", headers={"ETag": '"a"'})
    )
    respx.get(_url(config, "en_product3_156.xml")).mock(
        return_value=httpx.Response(404)
    )

    # product1 is required; product3_156 is optional — must NOT raise.
    bulk = download_files(config, files, optional={"product3_156"})

    assert bulk.path("product1") is not None
    assert bulk.path("product3_156") is None
    assert "product3_156" in bulk.results


@respx.mock
def test_download_files_optional_500_degrades(config: OrphanetDataConfig) -> None:
    files = {
        "product1": "en_product1.xml",
        "funct": "en_funct_consequences.xml",
    }
    respx.get(_url(config, "en_product1.xml")).mock(
        return_value=httpx.Response(200, text="<JDBOR/>", headers={"ETag": '"a"'})
    )
    respx.get(_url(config, "en_funct_consequences.xml")).mock(
        return_value=httpx.Response(503)
    )

    bulk = download_files(config, files, optional={"funct"})
    assert bulk.path("product1") is not None
    # funct was optional and failed -> degraded (no path, no exception)
    assert bulk.path("funct") is None


@respx.mock
def test_download_files_paths_property(config: OrphanetDataConfig) -> None:
    files = {"product1": "en_product1.xml"}
    respx.get(_url(config, "en_product1.xml")).mock(
        return_value=httpx.Response(200, text="<JDBOR/>", headers={"ETag": '"a"'})
    )
    bulk = download_files(config, files)
    assert "product1" in bulk.paths
    assert isinstance(bulk.paths["product1"], Path)


@respx.mock
def test_download_files_validators(config: OrphanetDataConfig) -> None:
    files = {"product1": "en_product1.xml"}
    respx.get(_url(config, "en_product1.xml")).mock(
        return_value=httpx.Response(
            200,
            text="<JDBOR/>",
            headers={"ETag": '"v99"', "Last-Modified": "Mon, 01 Jan 2024 00:00:00 GMT"},
        )
    )
    bulk = download_files(config, files)
    v = bulk.validators()
    assert "product1" in v
    assert v["product1"]["etag"] == '"v99"'


@respx.mock
def test_cache_written_and_read(config: OrphanetDataConfig, tmp_path: Path) -> None:
    filename = "en_product1.xml"
    url = _url(config, filename)

    respx.get(url).mock(
        return_value=httpx.Response(
            200, text="x", headers={"ETag": '"cached"', "Last-Modified": "Thu, 01 Jan 2026 00:00:00 GMT"}
        )
    )
    download_file(config, "product1", filename)

    cache = downloader._read_cache(config)
    assert url in cache
    assert cache[url]["etag"] == '"cached"'
