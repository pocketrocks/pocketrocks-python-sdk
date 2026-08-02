from typing import cast

from .constants import bot_wire_action_ids, bot_wire_objective_definitions
from .types import DecisionRequest, GameSetupEvent, ReconstructedDecisionContext


def _winning_seat(bids: tuple[int, ...], tiebreak_seat: int) -> int:
    highest = max(bids)
    for offset in range(1, len(bids) + 1):
        seat = (tiebreak_seat + offset) % len(bids)
        if bids[seat] == highest:
            return seat
    return 0


def _objective_is_met(objective_id: int, counts: list[int]) -> bool:
    definition = bot_wire_objective_definitions[str(objective_id)]
    pattern = definition.get("pattern")
    if pattern == "same2":
        return any(count >= 2 for count in counts)
    if pattern == "same3":
        return any(count >= 3 for count in counts)
    if pattern == "different3":
        return sum(count > 0 for count in counts) >= 3
    if pattern == "different4":
        return sum(count > 0 for count in counts) >= 4
    if pattern == "twoPairs4":
        return sum(count >= 2 for count in counts) >= 2
    requirement = cast(list[int], definition["requirement"])
    return all(counts[index] >= required for index, required in enumerate(requirement))


def reconstruct_decision_context(request: DecisionRequest) -> ReconstructedDecisionContext:
    setup = request.common_events[0]
    if not isinstance(setup, GameSetupEvent):
        raise ValueError("game setup must be first")
    cash = [setup.starting_cash] * setup.player_count
    won = [[0] * 5 for _ in range(setup.player_count)]
    revealed = [[0] * 5 for _ in range(setup.player_count)]
    owned: list[list[int]] = [[] for _ in range(setup.player_count)]
    tiebreak = setup.initial_tiebreak_seat
    action_id = None
    resources = (0, 0)
    for event in request.common_events[1:]:
        if event.kind == "turnOpened":
            action_id = event.action_id
            resources = event.resource_ids
        elif event.kind == "auctionResolved":
            winner = _winning_seat(event.bids_by_seat, tiebreak)
            cash[winner] -= event.bids_by_seat[winner]
            if action_id == bot_wire_action_ids["Loan10"]:
                cash[winner] += 10
            elif action_id == bot_wire_action_ids["Loan20"]:
                cash[winner] += 20
            if action_id in (bot_wire_action_ids["Auction1"], bot_wire_action_ids["Auction2"]):
                resource_count = 1 if action_id == bot_wire_action_ids["Auction1"] else 2
                for suit_id in resources[:resource_count]:
                    if suit_id:
                        won[winner][suit_id - 1] += 1
                for objective_id in setup.objective_ids:
                    if not any(objective_id in ids for ids in owned) and _objective_is_met(
                        objective_id, won[winner]
                    ):
                        owned[winner].append(objective_id)
            tiebreak = winner
        elif event.kind == "infoRevealed":
            revealed[tiebreak][event.suit_id - 1] += 1
    legal_max = None
    if request.decision_kind == "submitBid":
        legal_max = cash[request.bot_seat]
        if action_id == bot_wire_action_ids["Loan10"]:
            legal_max += 10
        elif action_id == bot_wire_action_ids["Loan20"]:
            legal_max += 20
    return ReconstructedDecisionContext(
        setup.player_count,
        setup.starting_cash,
        setup.value_chart,
        setup.objective_ids,
        action_id,
        resources,
        tuple(cash),
        tiebreak,
        tuple(tuple(row) for row in won),
        tuple(tuple(row) for row in revealed),
        tuple(tuple(row) for row in owned),
        request.bot_seat,
        request.current_hand_suit_ids,
        legal_max,
    )
