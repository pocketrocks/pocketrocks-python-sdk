"""The SDK speaks exactly one bot-wire protocol version, from one knob.

Before this file existed there were two: ``config.protocol_version`` (env
``POCKETROCKS_PROTOCOL_VERSION``, default 2) and the codec's own constant. They
were unlinked, so setting the env var to 3 negotiated v3 at the handshake and
then failed every decode. Now ``pocketrocks.protocol.PROTOCOL_VERSION`` is the
version, the config defaults to it and refuses anything else, and both the
handshake URL and every frame the runtime encodes or accepts carry it.
"""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest

from pocketrocks import ActionId, BotDecision, DecisionContext, PocketRocksBot, Suit
from pocketrocks.config import BotConfig
from pocketrocks.internal.bot_wire import bot_wire_protocol_versions
from pocketrocks.protocol import PROTOCOL_VERSION, decode_frame
from pocketrocks.testing import FakeTransport, heartbeat_bytes, scenario
from pocketrocks.types import RuntimeEvent

# The v2 golden frame the SDK shipped before the cutover (the former
# tests/fixtures/bot_wire_v2.json). Kept inline, not as a fixture: it exists
# here only to prove the SDK no longer accepts it.
_V2_DECISION_REQUEST_HEX = (
    "020300112233445566778899aabbccddeeff80b883a1f732011f050103140004080c1014020401020304"
    "0201010203030402010405020303040103010103"
)


def test_the_sdk_version_is_the_codec_v3_constant() -> None:
    assert PROTOCOL_VERSION == bot_wire_protocol_versions["v3"] == 3


def test_config_defaults_to_the_codec_version() -> None:
    assert BotConfig.from_env(api_key="k", bot_id="b").protocol_version == PROTOCOL_VERSION


@pytest.mark.parametrize("raw", ["2", "4"])
def test_env_var_naming_another_version_fails_fast(
    monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    # The footgun: a version the handshake would offer but the codec cannot
    # speak. Refused at construction, naming the variable and the fix, rather
    # than negotiated and then failing on the first frame.
    monkeypatch.setenv("POCKETROCKS_PROTOCOL_VERSION", raw)
    with pytest.raises(ValueError, match="POCKETROCKS_PROTOCOL_VERSION") as excinfo:
        BotConfig.from_env(api_key="k", bot_id="b")
    message = str(excinfo.value)
    assert str(PROTOCOL_VERSION) in message
    assert "pip install --upgrade" in message


def test_constructor_argument_naming_another_version_fails_fast() -> None:
    with pytest.raises(ValueError, match="protocol_version"):
        BotConfig.from_env(api_key="k", bot_id="b", protocol_version=2)


def test_constructor_argument_equal_to_the_codec_version_is_accepted() -> None:
    config = BotConfig.from_env(api_key="k", bot_id="b", protocol_version=PROTOCOL_VERSION)
    assert config.protocol_version == PROTOCOL_VERSION


class _MaxBidBot(PocketRocksBot):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.events: list[RuntimeEvent] = []

    async def choose_decision(self, context: DecisionContext) -> BotDecision:
        return BotDecision.submit_bid(context.legal_max_amount or 0)

    async def on_runtime_event(self, event: RuntimeEvent) -> None:
        self.events.append(event)


def _request_bytes() -> bytes:
    return (
        scenario(players=3, starting_cash=20)
        .turn(ActionId.AUCTION1, resources=(Suit.BRICK, Suit.WOOD))
        .deciding(seat=0, hand=[Suit.BRICK], kind="submitBid")
        .to_bytes(deadline_at=int(time.time() * 1000) + 5_000)
    )


async def test_negotiated_version_is_the_version_on_every_frame_sent() -> None:
    # One knob, three surfaces: the handshake query, the leading varint of every
    # frame the runtime writes, and the version the SDK decoder accepts.
    transport = FakeTransport(
        [heartbeat_bytes("11111111-1111-1111-1111-111111111111"), _request_bytes()]
    )
    bot = _MaxBidBot(
        api_key="k",
        bot_id="b",
        server_url="ws://example.test",
        reconnect=False,
        transport=transport,
    )
    await bot.run_async()

    assert transport.connected_url is not None
    negotiated = parse_qs(urlparse(transport.connected_url).query)["protocolVersion"]
    assert negotiated == [str(PROTOCOL_VERSION)]
    assert len(transport.sent_messages) == 2  # heartbeat response + decision
    for payload in transport.sent_messages:
        assert payload[0] == PROTOCOL_VERSION
        decode_frame(payload)  # the SDK's own decoder accepts what it wrote


async def test_a_frame_in_another_version_is_malformed_to_the_sdk() -> None:
    # The server serves exactly one version; a frame in any other is as
    # malformed as a bad byte. The old v2 golden frame is the concrete case.
    v2_frame = bytes.fromhex(_V2_DECISION_REQUEST_HEX)
    with pytest.raises(ValueError, match="unexpected bot wire protocol version"):
        decode_frame(v2_frame)

    transport = FakeTransport([v2_frame])
    bot = _MaxBidBot(
        api_key="k",
        bot_id="b",
        server_url="ws://example.test",
        reconnect=False,
        transport=transport,
    )
    await bot.run_async()

    assert transport.sent_messages == []
    malformed = [e for e in bot.events if e.kind == "malformedFrame"]
    assert len(malformed) == 1
    assert "protocol version" in malformed[0].details["error"]
