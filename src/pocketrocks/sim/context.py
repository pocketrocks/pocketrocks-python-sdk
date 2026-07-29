"""Build live-identical ``DecisionContext``s from sim state.

The sim never assembles contexts by hand: it builds the same ``DecisionRequest``
the live server would send (the engine's accumulated wire events + the seat's
private hand) and hands it to the SDK's production ``build_decision_context``.
Whatever the live wire derives, the sim derives — by construction.
"""

from __future__ import annotations

import time
import uuid

from pocketrocks.internal.bot_wire_v2 import DecisionRequest
from pocketrocks.protocol import build_decision_context
from pocketrocks.types import DecisionContext, decisionKind

from .engine import SimEngine

_SIM_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "pocketrocks-sim")


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


def build_sim_context(
    engine: SimEngine,
    seat: int,
    kind: decisionKind,
    *,
    budget_ms: int,
    turn_index: int | None = None,
) -> DecisionContext:
    request = build_sim_request(
        engine, seat, kind, budget_ms=budget_ms, turn_index=turn_index
    )
    return build_decision_context(request, received_at=int(time.time() * 1000))
