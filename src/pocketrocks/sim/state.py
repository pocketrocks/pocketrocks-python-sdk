"""Mutable game state and immutable result records for the sim engine."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PlayerSim:
    seat: int
    name: str
    cash: int
    hand_suits: list[int]  # unrevealed info cards, deal order
    won_suits: list[int] = field(default_factory=list)
    revealed_suits: list[int] = field(default_factory=list)
    loans: list[int] = field(default_factory=list)  # principals
    investments: list[tuple[int, int]] = field(default_factory=list)  # (lock, payout)
    objective_wire_ids: list[int] = field(default_factory=list)


@dataclass(frozen=True)
class RevealRecord:
    seat: int
    suit: int
    auto: bool


@dataclass(frozen=True)
class TurnRecord:
    turn_index: int
    action: str
    upcoming_before: tuple[int, ...]
    raw_bids: tuple[int, ...]
    effective_bids: tuple[int, ...]
    winner_seat: int
    paid: int
    bundle_suits: tuple[int, ...]
    claimed_objective_wire_ids: tuple[int, ...]
    reveal: RevealRecord | None


@dataclass(frozen=True)
class ScoreRow:
    seat: int
    name: str
    cash: int
    items_value: int
    objectives_value: int
    investments_value: int
    loans_value: int
    total: int
