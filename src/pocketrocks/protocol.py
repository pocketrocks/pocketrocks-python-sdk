from __future__ import annotations

from urllib.parse import urlencode

from pocketrocks.constants import connect_path
from pocketrocks.internal.bot_wire_v2 import (
    DecisionRequest,
    DecisionResponse,
    reconstruct_decision_context,
)
from pocketrocks.types import BotDecision, DecisionContext


def build_connection_url(server_url: str, bot_id: str, protocol_version: int, capacity: int) -> str:
    base_url = server_url.rstrip("/")
    query = urlencode(
        {
            "botId": bot_id,
            "protocolVersion": protocol_version,
            "capacity": capacity,
        }
    )
    return f"{base_url}{connect_path}?{query}"


def build_decision_context(request: DecisionRequest, *, received_at: int) -> DecisionContext:
    reconstructed = reconstruct_decision_context(request)
    return DecisionContext(
        request_id=request.request_id,
        deadline_at=request.deadline_at,
        received_at=received_at,
        decision_kind=request.decision_kind,
        player_count=reconstructed.player_count,
        starting_cash=reconstructed.starting_cash,
        value_chart=reconstructed.value_chart,
        objective_ids=reconstructed.objective_ids,
        current_action_id=reconstructed.current_action_id,
        current_resource_ids=reconstructed.current_resource_ids,
        cash_by_seat=reconstructed.cash_by_seat,
        tiebreak_seat=reconstructed.tiebreak_seat,
        won_resource_counts_by_seat=reconstructed.won_resource_counts_by_seat,
        revealed_info_counts_by_seat=reconstructed.revealed_info_counts_by_seat,
        owned_objective_ids_by_seat=reconstructed.owned_objective_ids_by_seat,
        bot_seat=reconstructed.bot_seat,
        current_hand_suit_ids=reconstructed.current_hand_suit_ids,
        legal_max_amount=reconstructed.legal_max_amount,
        revealable_count=len(reconstructed.current_hand_suit_ids),
        metadata={},
    )


def decision_to_protocol_response(request_id: str, decision: BotDecision) -> DecisionResponse:
    return DecisionResponse(
        kind="decisionResponse",
        request_id=request_id,
        action_kind=decision.action_kind,
        value=decision.value,
    )
