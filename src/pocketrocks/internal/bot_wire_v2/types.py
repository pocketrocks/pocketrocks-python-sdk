from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypeAlias

SuitId: TypeAlias = Literal[1, 2, 3, 4, 5]
ActionId: TypeAlias = Literal[1, 2, 3, 4, 5, 6]


@dataclass(frozen=True)
class GameSetupEvent:
    kind: Literal["gameSetup"]
    player_count: int
    starting_cash: int
    value_chart: tuple[int, int, int, int, int, int]
    initial_tiebreak_seat: int
    objective_ids: tuple[int, ...]


@dataclass(frozen=True)
class TurnOpenedEvent:
    kind: Literal["turnOpened"]
    action_id: int
    resource_ids: tuple[int, int]


@dataclass(frozen=True)
class AuctionResolvedEvent:
    kind: Literal["auctionResolved"]
    bids_by_seat: tuple[int, ...]


@dataclass(frozen=True)
class InfoRevealedEvent:
    kind: Literal["infoRevealed"]
    suit_id: int


CommonEvent: TypeAlias = GameSetupEvent | TurnOpenedEvent | AuctionResolvedEvent | InfoRevealedEvent


@dataclass(frozen=True)
class HeartbeatRequest:
    kind: Literal["heartbeatRequest"]
    request_id: str
    deadline_at: int


@dataclass(frozen=True)
class HeartbeatResponse:
    kind: Literal["heartbeatResponse"]
    request_id: str


@dataclass(frozen=True)
class DecisionRequest:
    kind: Literal["decisionRequest"]
    request_id: str
    deadline_at: int
    decision_kind: Literal["submitBid", "selectInfoToReveal"]
    common_events: tuple[CommonEvent, ...]
    bot_seat: int
    current_hand_suit_ids: tuple[int, ...]


@dataclass(frozen=True)
class DecisionResponse:
    kind: Literal["decisionResponse"]
    request_id: str
    action_kind: Literal["pass", "submitBid", "selectInfoToReveal"]
    value: int | None = None


Frame: TypeAlias = HeartbeatRequest | HeartbeatResponse | DecisionRequest | DecisionResponse


@dataclass(frozen=True)
class ReconstructedDecisionContext:
    player_count: int
    starting_cash: int
    value_chart: tuple[int, ...]
    objective_ids: tuple[int, ...]
    current_action_id: int | None
    current_resource_ids: tuple[int, int]
    cash_by_seat: tuple[int, ...]
    tiebreak_seat: int
    won_resource_counts_by_seat: tuple[tuple[int, ...], ...]
    revealed_info_counts_by_seat: tuple[tuple[int, ...], ...]
    owned_objective_ids_by_seat: tuple[tuple[int, ...], ...]
    bot_seat: int
    current_hand_suit_ids: tuple[int, ...]
    legal_max_amount: int | None
