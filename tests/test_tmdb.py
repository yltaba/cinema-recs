import asyncio
import traceback

import duckdb
import httpx
import pytest
import respx

from recs.tmdb import BASE_URL, TMDB, TMDBError


@pytest.mark.parametrize("status", [400, 401, 403])
def test_http_error_does_not_expose_credentials(status):
    secret = "SYNTHETIC_TEST_KEY"

    async def run():
        con = duckdb.connect()
        try:
            async with TMDB(con, secret) as tmdb:
                with respx.mock() as router:
                    router.get(f"{BASE_URL}/movie/1").mock(
                        return_value=httpx.Response(status, text=secret))
                    with pytest.raises(TMDBError) as caught:
                        await tmdb.fetch("/movie/1", {})
                    rendered = "".join(traceback.format_exception(caught.value))
                    assert secret not in rendered and "api_key=" not in rendered
                    assert str(status) in str(caught.value)
        finally:
            con.close()

    asyncio.run(run())
