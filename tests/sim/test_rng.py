from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

import pytest

from pocketrocks.sim import rng
from pocketrocks.sim.constants import ACTION_DECK, ALL_OBJECTIVE_WIRE_IDS, ITEM_DECK_SUITS

_FIXTURES = Path(__file__).parent.parent / "fixtures" / "botsdk"


def _shuffle_cases() -> list[dict[str, Any]]:
    data = json.loads((_FIXTURES / "shuffles.json").read_text())
    return list(data["cases"])


@pytest.mark.parametrize("case", _shuffle_cases(), ids=lambda c: f"{c['seed']}-{c['size']}")
def test_matches_ts_shuffle(case: dict[str, Any]) -> None:
    size = int(case["size"])
    assert rng.shuffled(list(range(size)), str(case["seed"])) == case["permutation"]


def test_same_seed_same_result() -> None:
    assert rng.shuffled(list(range(30)), "abc") == rng.shuffled(list(range(30)), "abc")


def test_input_not_mutated() -> None:
    items = list(range(10))
    rng.shuffled(items, "abc")
    assert items == list(range(10))


def test_empty_seed_rejected() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        rng.shuffled(list(range(5)), "")


def _assert_batch_matches_scalar(groups: tuple[tuple[Any, ...], ...], seeds: list[str]) -> None:
    actual = rng.batch_shuffled_many(groups, seeds)

    assert len(actual) == len(groups)
    for group, shuffled_group in zip(groups, actual, strict=True):
        assert shuffled_group.shape == (len(seeds), len(group))
        assert shuffled_group.tolist() == [rng.shuffled(group, seed) for seed in seeds]


def test_batch_matches_scalar_for_canonical_setup_groups_and_unicode_seeds() -> None:
    groups = (
        ITEM_DECK_SUITS,
        ACTION_DECK,
        tuple(range(5)),
        ALL_OBJECTIVE_WIRE_IDS,
    )

    _assert_batch_matches_scalar(groups, ["a", "é", "石🪨", "seed-with-many-bytes"])


def test_batch_matches_scalar_for_randomized_seeds() -> None:
    randomizer = random.Random(8675309)  # noqa: S311 -- test fixture RNG, not security-sensitive
    seeds = [randomizer.randbytes(randomizer.randrange(1, 80)).hex() for _ in range(127)]

    _assert_batch_matches_scalar((tuple(range(47)), tuple("pocketrocks")), seeds)


def test_batch_matches_scalar_for_mixed_seed_lengths_above_mt_state_size() -> None:
    _assert_batch_matches_scalar(
        (tuple(range(30)),),
        ["short", "x" * 625, "y" * 700, "also-short"],
    )


def test_batch_chunking_preserves_seed_order_and_results() -> None:
    groups = (ITEM_DECK_SUITS, ACTION_DECK, ALL_OBJECTIVE_WIRE_IDS)
    seeds = [f"chunk-seed-{index}" for index in range(73)]
    full = rng.batch_shuffled_many(groups, seeds)
    first = rng.batch_shuffled_many(groups, seeds[:19])
    second = rng.batch_shuffled_many(groups, seeds[19:])

    for full_group, first_group, second_group in zip(full, first, second, strict=True):
        assert full_group.tolist() == first_group.tolist() + second_group.tolist()


def test_batch_matches_scalar_when_random_js_rejection_sampling_is_exercised() -> None:
    # A large non-power-of-two range makes random-js's uint32 rejection branch
    # observable while keeping the expected scalar result practical to compute.
    group = tuple(range(100_000))

    _assert_batch_matches_scalar((group,), ["rejection-1"])


@pytest.mark.parametrize("seeds", [[], ["valid", ""]])
def test_batch_rejects_missing_or_empty_seeds(seeds: list[str]) -> None:
    with pytest.raises(ValueError, match="non-empty"):
        rng.batch_shuffled_many((tuple(range(5)),), seeds)
