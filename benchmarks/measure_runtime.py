from __future__ import annotations

import asyncio
import statistics
import time
from dataclasses import dataclass

from pocketrocks import BotDecision, DecisionContext, PocketRocksBot
from pocketrocks.internal.bot_wire_v2 import (
    AuctionResolvedEvent,
    DecisionRequest,
    GameSetupEvent,
    TurnOpenedEvent,
    decode_frame,
    encode_frame,
)
from pocketrocks.protocol import build_decision_context


@dataclass(slots=True, frozen=True)
class BenchmarkResult:
    name: str
    iterations: int
    average_ms: float
    p95_ms: float


def now_ms() -> int:
    return int(time.time() * 1000)


def build_request(*, player_count: int, turn_depth: int) -> DecisionRequest:
    events = [
        GameSetupEvent(
            kind="gameSetup",
            player_count=player_count,
            starting_cash=20,
            value_chart=(0, 4, 8, 12, 16, 20),
            initial_tiebreak_seat=1,
            objective_ids=(1, 2, 3, 4),
        )
    ]
    for index in range(turn_depth):
        events.append(
            TurnOpenedEvent(
                kind="turnOpened",
                action_id=1 if index % 2 == 0 else 2,
                resource_ids=((index % 5) + 1, ((index + 1) % 5) + 1),
            )
        )
        bids = tuple((index + seat) % 5 for seat in range(player_count))
        events.append(AuctionResolvedEvent(kind="auctionResolved", bids_by_seat=bids))
    return DecisionRequest(
        kind="decisionRequest",
        request_id="00112233-4455-6677-8899-aabbccddeeff",
        deadline_at=now_ms() + 5_000,
        decision_kind="submitBid",
        common_events=tuple(events),
        bot_seat=0,
        current_hand_suit_ids=(1, 2, 3),
    )


def summarize(name: str, samples: list[float]) -> BenchmarkResult:
    ordered = sorted(samples)
    p95_index = max(0, int(len(ordered) * 0.95) - 1)
    return BenchmarkResult(
        name=name,
        iterations=len(samples),
        average_ms=statistics.mean(samples),
        p95_ms=ordered[p95_index],
    )


def benchmark_decode(request_bytes: bytes, iterations: int) -> BenchmarkResult:
    samples: list[float] = []
    for _ in range(iterations):
        started = time.perf_counter()
        decode_frame(request_bytes)
        samples.append((time.perf_counter() - started) * 1000)
    return summarize("decode", samples)


def benchmark_decode_and_reconstruct(request_bytes: bytes, iterations: int) -> BenchmarkResult:
    samples: list[float] = []
    for _ in range(iterations):
        started = time.perf_counter()
        frame = decode_frame(request_bytes)
        build_decision_context(frame, received_at=now_ms())
        samples.append((time.perf_counter() - started) * 1000)
    return summarize("decode_and_reconstruct", samples)


class BenchmarkBot(PocketRocksBot):
    async def choose_decision(self, context: DecisionContext) -> BotDecision:
        if context.legal_max_amount is None or context.legal_max_amount <= 0:
            return BotDecision.pass_turn()
        return BotDecision.submit_bid(context.legal_max_amount)


async def benchmark_parallel_callbacks(iterations: int) -> BenchmarkResult:
    bot = BenchmarkBot(
        api_key="benchmark-key",
        bot_id="benchmark-bot",
        reconnect=False,
    )
    context = build_decision_context(
        build_request(player_count=5, turn_depth=20),
        received_at=now_ms(),
    )
    samples: list[float] = []
    for _ in range(iterations):
        started = time.perf_counter()
        await asyncio.gather(*(bot.choose_decision(context) for _ in range(32)))
        samples.append((time.perf_counter() - started) * 1000)
    return summarize("parallel_callback_batch_32", samples)


def print_result(result: BenchmarkResult) -> None:
    print(
        f"{result.name}: iterations={result.iterations} "
        f"avg_ms={result.average_ms:.4f} p95_ms={result.p95_ms:.4f}"
    )


async def main() -> None:
    for player_count in (3, 4, 5):
        for turn_depth in (5, 10, 20):
            request = build_request(player_count=player_count, turn_depth=turn_depth)
            encoded = encode_frame(request)
            print(f"scenario: players={player_count} turns={turn_depth} bytes={len(encoded)}")
            print_result(benchmark_decode(encoded, 200))
            print_result(benchmark_decode_and_reconstruct(encoded, 200))
    print_result(await benchmark_parallel_callbacks(50))


if __name__ == "__main__":
    asyncio.run(main())
