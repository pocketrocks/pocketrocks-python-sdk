"""Build live-identical ``DecisionContext``s from sim state.

The sim builds the same ``DecisionRequest`` the live server would send, but
shapes its ``DecisionContext`` directly from the canonical ``SimEngine`` state.
This avoids replaying an ever-growing event history for every seat and decision.
Parity tests compare the direct path with production wire reconstruction through
complete games.

Determinism contract: every *game-state* field of a simulated context is a pure
function of the seed and the bots' decisions. The wall-clock fields
(``deadline_at``, ``received_at``, and the derived ``remaining_deadline_ms``)
are intentionally real: they model the live time budget and are stamped from
the current clock, so a bot that branches on them is excluded from the
same-seed reproducibility guarantee. Strategy should read game state; deadline
fields are for budget management only.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Sequence

from pocketrocks.internal.bot_wire import DecisionRequest
from pocketrocks.types import DecisionContext, decisionKind

from .constants import ACTION_WIRE_IDS, LOAN_PRINCIPAL, STARTING_CASH
from .engine import SimEngine

_SIM_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "pocketrocks-sim")


def _counts_by_suit(suits: Sequence[int]) -> tuple[int, ...]:
    return tuple(suits.count(suit_id) for suit_id in range(1, 6))


def _latest_action_and_resources(
    engine: SimEngine,
) -> tuple[str | None, tuple[int, int]]:
    resources: Sequence[int]
    if engine.current_action is not None:
        action = engine.current_action
        resources = engine.upcoming
    elif engine.history:
        action = engine.history[-1].action
        resources = engine.history[-1].upcoming_before
    else:
        action = None
        resources = ()
    return action, (
        resources[0] if len(resources) > 0 else 0,
        resources[1] if len(resources) > 1 else 0,
    )


def build_sim_request(
    engine: SimEngine,
    seat: int,
    kind: decisionKind,
    *,
    budget_ms: int,
    turn_index: int | None = None,
) -> DecisionRequest:
    now = int(time.time() * 1000)
    effective_turn_index = engine.turn_index if turn_index is None else turn_index
    request_id = str(
        uuid.uuid5(_SIM_NAMESPACE, f"{engine.seed}:{effective_turn_index}:{seat}:{kind}")
    )
    return DecisionRequest(
        kind="decisionRequest",
        request_id=request_id,
        deadline_at=now + budget_ms,
        decision_kind=kind,
        common_events=tuple(engine.events),
        bot_seat=seat,
        current_hand_suit_ids=tuple(engine.players[seat].hand_suits),
    )


def build_sim_request_and_context(
    engine: SimEngine,
    seat: int,
    kind: decisionKind,
    *,
    budget_ms: int,
    turn_index: int | None = None,
) -> tuple[DecisionRequest, DecisionContext]:
    """Build the wire request and its derived context together.

    ``LocalGame`` needs both: the context for ``choose_decision`` and the raw
    request frame for bots that override the ``choose_raw_decision`` escape
    hatch (mirroring the live runtime's dispatch).
    """
    request = build_sim_request(engine, seat, kind, budget_ms=budget_ms, turn_index=turn_index)
    action, resources = _latest_action_and_resources(engine)
    legal_max = None
    if kind == "submitBid":
        legal_max = engine.players[seat].cash
        if action is not None:
            legal_max += LOAN_PRINCIPAL.get(action, 0)
    context = DecisionContext(
        request_id=request.request_id,
        deadline_at=request.deadline_at,
        received_at=int(time.time() * 1000),
        decision_kind=kind,
        player_count=len(engine.players),
        starting_cash=STARTING_CASH[len(engine.players)],
        value_chart=engine.value_chart,
        objective_ids=tuple(objective_id for objective_id, _seat in engine.active_objectives),
        current_action_id=ACTION_WIRE_IDS[action] if action is not None else None,
        current_resource_ids=resources,
        cash_by_seat=tuple(player.cash for player in engine.players),
        tiebreak_seat=engine.tiebreak_seat,
        won_resource_counts_by_seat=tuple(
            _counts_by_suit(player.won_suits) for player in engine.players
        ),
        revealed_info_counts_by_seat=tuple(
            _counts_by_suit(player.revealed_suits) for player in engine.players
        ),
        owned_objective_ids_by_seat=tuple(
            tuple(player.objective_wire_ids) for player in engine.players
        ),
        bot_seat=seat,
        current_hand_suit_ids=tuple(engine.players[seat].hand_suits),
        legal_max_amount=legal_max,
        revealable_count=len(engine.players[seat].hand_suits),
        metadata={},
    )
    return request, context


def build_sim_context(
    engine: SimEngine,
    seat: int,
    kind: decisionKind,
    *,
    budget_ms: int,
    turn_index: int | None = None,
) -> DecisionContext:
    _request, context = build_sim_request_and_context(
        engine, seat, kind, budget_ms=budget_ms, turn_index=turn_index
    )
    return context
