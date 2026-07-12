from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import replace
from typing import Any

from pocketrocks.internal.bot_wire_v2 import (
    AuctionResolvedEvent,
    CommonEvent,
    DecisionRequest,
    GameSetupEvent,
    InfoRevealedEvent,
    TurnOpenedEvent,
    encode_frame,
)
from pocketrocks.protocol import build_decision_context
from pocketrocks.types import DecisionContext, decisionKind

# A neutral game setup. Callers override what their test cares about; the rest is
# just enough to make a valid, reconstructable request.
_DEFAULT_VALUE_CHART: tuple[int, int, int, int, int, int] = (0, 4, 8, 12, 16, 20)
_DEFAULT_OBJECTIVE_IDS: tuple[int, ...] = (1, 2, 3, 4)
_DEFAULT_REQUEST_ID = "00000000-0000-0000-0000-000000000000"
_DEFAULT_REMAINING_MS = 5_000


def scenario(
    *,
    players: int,
    starting_cash: int,
    value_chart: tuple[int, int, int, int, int, int] = _DEFAULT_VALUE_CHART,
    initial_tiebreak_seat: int = 0,
    objective_ids: tuple[int, ...] = _DEFAULT_OBJECTIVE_IDS,
) -> Scenario:
    """Start narrating a game situation for a test.

    Returns a fluent :class:`Scenario`. Chain ``.turn()`` / ``.auction()`` /
    ``.reveal()`` to describe the history and ``.deciding()`` to frame the pending
    move, then call ``.to_context()`` (or ``.to_bytes()``). Every field a real
    ``DecisionContext`` exposes is *derived* from this narration through the same
    production path the live wire uses — nothing is asserted directly.
    """
    setup = GameSetupEvent(
        kind="gameSetup",
        player_count=players,
        starting_cash=starting_cash,
        value_chart=value_chart,
        initial_tiebreak_seat=initial_tiebreak_seat,
        objective_ids=objective_ids,
    )
    return Scenario(setup)


class Scenario:
    """A narrated game history that derives a ``DecisionContext`` or wire frame.

    Build via :func:`scenario`, not directly. Methods mutate and return ``self`` so
    calls chain. See :func:`scenario` for the intended flow.
    """

    def __init__(self, setup: GameSetupEvent) -> None:
        self._setup = setup
        self._events: list[CommonEvent] = []
        self._bot_seat = 0
        self._hand: tuple[int, ...] = ()
        self._decision_kind: decisionKind = "submitBid"
        self._request_id = _DEFAULT_REQUEST_ID
        self._remaining_ms = _DEFAULT_REMAINING_MS
        self._overrides: dict[str, Any] = {}

    def turn(self, action_id: int, *, resources: tuple[int, int] = (0, 0)) -> Scenario:
        """Open an auction for ``action_id`` (see ``ActionId``); ``resources`` are the
        two offered suit ids (see ``Suit``), zero-padded for non-resource actions."""
        self._events.append(
            TurnOpenedEvent(
                kind="turnOpened",
                action_id=int(action_id),
                resource_ids=(int(resources[0]), int(resources[1])),
            )
        )
        return self

    def auction(self, bids: Mapping[int, int] | Iterable[int]) -> Scenario:
        """Resolve the open auction. ``bids`` is either a ``{seat: amount}`` mapping
        (missing seats bid 0) or a per-seat sequence. The winner is derived exactly
        as the server does (highest bid, ties broken clockwise from the tiebreak
        seat)."""
        self._events.append(
            AuctionResolvedEvent(kind="auctionResolved", bids_by_seat=self._bids_tuple(bids))
        )
        return self

    def reveal(self, suit_id: int) -> Scenario:
        """Reveal one info card of ``suit_id`` (see ``Suit``). The reconstruction
        credits it to the current tiebreak seat, matching the wire semantics."""
        self._events.append(InfoRevealedEvent(kind="infoRevealed", suit_id=int(suit_id)))
        return self

    def deciding(
        self,
        *,
        seat: int,
        hand: Iterable[int],
        kind: decisionKind = "submitBid",
        request_id: str | None = None,
        remaining_ms: int | None = None,
    ) -> Scenario:
        """Frame the pending decision: which ``seat`` the bot occupies, its
        ``hand`` of revealable suit ids, and the decision ``kind``. ``remaining_ms``
        sets how much of the deadline is left when ``to_context()``/``to_bytes()``
        is called."""
        self._bot_seat = seat
        self._hand = tuple(int(suit) for suit in hand)
        self._decision_kind = kind
        if request_id is not None:
            self._request_id = request_id
        if remaining_ms is not None:
            self._remaining_ms = remaining_ms
        return self

    def override(self, **fields: Any) -> Scenario:
        """Pin ``DecisionContext`` fields the narration cannot reach (e.g. an
        arbitrary per-seat matrix, or a deliberately impossible ``legal_max_amount``).

        The escape hatch, not the default: prefer narrating the history. Overrides
        apply only to :meth:`to_context`; :meth:`to_bytes` goes over the wire and
        cannot carry them."""
        self._overrides.update(fields)
        return self

    def to_context(self, *, received_at: int | None = None) -> DecisionContext:
        """Derive the ``DecisionContext`` through the production reconstruct path,
        then apply any :meth:`override` fields."""
        from pocketrocks.runtime import now_ms

        received = now_ms() if received_at is None else received_at
        request = self._build_request(deadline_at=received + self._remaining_ms)
        context = build_decision_context(request, received_at=received)
        if self._overrides:
            context = replace(context, **self._overrides)
        return context

    def to_bytes(self, *, deadline_at: int | None = None) -> bytes:
        """Encode this scenario as a decision-request wire frame for feeding to
        :class:`FakeTransport`. Overrides do not apply on the wire path."""
        from pocketrocks.runtime import now_ms

        deadline = (now_ms() + self._remaining_ms) if deadline_at is None else deadline_at
        return encode_frame(self._build_request(deadline_at=deadline))

    def _build_request(self, *, deadline_at: int) -> DecisionRequest:
        return DecisionRequest(
            kind="decisionRequest",
            request_id=self._request_id,
            deadline_at=deadline_at,
            decision_kind=self._decision_kind,
            common_events=(self._setup, *self._events),
            bot_seat=self._bot_seat,
            current_hand_suit_ids=self._hand,
        )

    def _bids_tuple(self, bids: Mapping[int, int] | Iterable[int]) -> tuple[int, ...]:
        players = self._setup.player_count
        if isinstance(bids, Mapping):
            return tuple(int(bids.get(seat, 0)) for seat in range(players))
        return tuple(int(amount) for amount in bids)
