"""vendor-analytics' HTTP routes: the rug-pull participants trigger for C04, and the reset."""

import json

import httpx
import pytest
from mcp.shared.memory import create_connected_server_and_client_session as connect

import vendor_analytics.server as vendor


@pytest.fixture
async def http():
    vendor._set_description(vendor.BENIGN)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=vendor.app), base_url="http://vendor") as c:
        yield c
    vendor._set_description(vendor.BENIGN)  # leave the shared server benign for other tests


async def listed_description() -> str:
    async with connect(vendor.mcp._mcp_server) as session:
        return (await session.list_tools()).tools[0].description


async def test_rugpull_swaps_in_the_poisoned_description(http):
    assert (await http.get("/health")).json()["rug_pulled"] is False
    assert await listed_description() == vendor.BENIGN

    assert (await http.post("/rugpull")).json() == {"ok": True, "rug_pulled": True}
    assert (await http.get("/health")).json()["rug_pulled"] is True
    assert await listed_description() == vendor.POISONED  # what a re-listing client now receives


async def test_reset_restores_the_approved_description(http):
    await http.post("/rugpull")
    assert (await http.post("/reset")).json() == {"ok": True, "rug_pulled": False}
    assert await listed_description() == vendor.BENIGN


async def test_the_tool_itself_stays_harmless(http):
    async with connect(vendor.mcp._mcp_server) as session:
        result = await session.call_tool(vendor.TOOL, {"horizon_hours": 6})
    forecast = json.loads(result.content[0].text)
    assert len(forecast["demand_m3h"]) == 6  # the payload is the description, not the code
