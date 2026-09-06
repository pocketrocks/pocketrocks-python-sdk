"""The ruleset seam: everything a bot's model of the game depends on, as data.

``Ruleset`` mirrors the server's ruleset fields in snake_case and is the one
object the batch engine, the scalar engine, ``LocalGame`` and ``run_games``
read. Two pure functions front the parts of it that used to be hardcoded:

- ``resolve_chart`` turns a fixed key (``"A"``-``"E"``) or an inline 6-tuple
  into cells, validating inline cells against the constraint envelope. Nothing
  downstream of it ever sees a key.
- ``compute_paid`` prices an auction from the effective bids under a payment
  rule. Winner selection is not its job; the winner is whoever bid highest,
  under either rule.

The envelope constants mirror ``packages/shared/src/chartGenerator.ts`` in the
main repo and are a research contract (calibrated by the #524 ablation): do not
tune them here without a matching lab run and a server change. Both sides
assert the same accept/reject table (``tests/fixtures/chart_envelope.json``).
"""

from __future__ import annotations

import numbers
from collections.abc import Sequence
from dataclasses import dataclass
from typing import get_args

import numpy as np
from numpy.typing import NDArray

from pocketrocks.types import PaymentRule as PaymentRule  # explicit re-export for mypy

from .constants import VALUE_CHARTS

# ``PaymentRule`` is defined once, on the public ``pocketrocks.types`` module (the
# live ``DecisionContext`` carries it), and re-exported here so ``pocketrocks.sim``
# and ``pocketrocks.types`` name the same Literal.
PAYMENT_RULES: tuple[PaymentRule, ...] = get_args(PaymentRule)

#: Number of cells in a value chart (index = cards of one suit held, 0-5).
CHART_CELLS = 6
#: Every cell lies in ``[-CHART_CELL_CAP, CHART_CELL_CAP]``.
CHART_CELL_CAP = 20
#: Monotone and hump charts must total at least this. Fixed chart E sums to
#: exactly 38, which is why the floor is 38 and not 40: E is the minimum any
#: chart can total.
SUM_FLOOR = 38
#: Valleys (fall then rise) need far more total to stay fair...
VALLEY_SUM_FLOOR = 75
#: ...and a shallow trough.
VALLEY_MIN_CELL = 2
#: More than one direction reversal is unreliable.
MAX_TURNS = 1

_KEY_FIX = "pass a fixed chart key A-E or an inline chart of 6 integers"


def count_turns(values: Sequence[int]) -> int:
    """Number of direction reversals over consecutive non-equal neighbours."""
    signs = [
        1 if values[index + 1] > values[index] else -1
        for index in range(len(values) - 1)
        if values[index + 1] != values[index]
    ]
    return sum(1 for index in range(1, len(signs)) if signs[index] != signs[index - 1])


def is_valley_chart(values: Sequence[int]) -> bool:
    """A single-turn chart whose first move is downward (an interior trough)."""
    if count_turns(values) != 1:
        return False
    for index in range(len(values) - 1):
        if values[index + 1] != values[index]:
            return values[index + 1] < values[index]
    return False


def _validate_inline_chart(values: Sequence[object]) -> tuple[int, ...]:
    if len(values) != CHART_CELLS:
        raise ValueError(
            f"a value chart has exactly {CHART_CELLS} cells, got {len(values)}; {_KEY_FIX}"
        )
    cells: list[int] = []
    for cell in values:
        # bool is an int subclass; a chart of Trues is a bug, not a chart.
        if isinstance(cell, bool) or not isinstance(cell, numbers.Integral):
            raise ValueError(f"value chart cells must be integers, got {cell!r}; {_KEY_FIX}")
        cells.append(int(cell))
    chart = tuple(cells)
    if any(abs(cell) > CHART_CELL_CAP for cell in chart):
        raise ValueError(
            f"value chart {chart} breaks the cell cap: every cell must be within "
            f"+/-{CHART_CELL_CAP}"
        )
    turns = count_turns(chart)
    if turns > MAX_TURNS:
        raise ValueError(
            f"value chart {chart} has {turns} turning points; the envelope allows at most "
            f"{MAX_TURNS} turning point"
        )
    total = sum(chart)
    if is_valley_chart(chart):
        violations: list[str] = []
        if total < VALLEY_SUM_FLOOR:
            violations.append(f"the valley sum floor (sum {total} < {VALLEY_SUM_FLOOR})")
        if min(chart) < VALLEY_MIN_CELL:
            violations.append(f"the valley min cell (min {min(chart)} < {VALLEY_MIN_CELL})")
        if violations:
            raise ValueError(
                f"value chart {chart} is a valley that breaks {' and '.join(violations)}"
            )
    elif total < SUM_FLOOR:
        raise ValueError(f"value chart {chart} breaks the sum floor (sum {total} < {SUM_FLOOR})")
    return chart


def resolve_chart(selection: str | Sequence[int] | NDArray[np.integer]) -> tuple[int, ...]:
    """Turn a chart selection into cells.

    A ``str`` is a fixed chart key (``"A"``-``"E"``, case-insensitive). Anything
    else is an inline chart: exactly 6 integers validated against the constraint
    envelope. The error message names the violated constraint.
    """
    if isinstance(selection, str):
        key = selection.upper()
        if key not in VALUE_CHARTS:
            raise ValueError(f"unknown value chart {selection!r}; {_KEY_FIX}")
        return VALUE_CHARTS[key]
    return _validate_inline_chart(tuple(selection))


def _check_payment_rule(rule: str) -> PaymentRule:
    if rule not in PAYMENT_RULES:
        raise ValueError(f"unknown payment rule {rule!r}; choose one of {PAYMENT_RULES}")
    return rule


def compute_paid(rule: PaymentRule, bids: Sequence[int]) -> int:
    """Price an auction from its effective bids. Mirrors ``computePaid`` in
    ``packages/shared``.

    ``first-price``: the winner pays the top bid (their own). ``second-price``:
    the winner pays the runner-up bid, so a single positive bid pays 0. Ties pay
    the tied amount under both rules. Who wins is decided elsewhere.
    """
    _check_payment_rule(rule)
    ordered = sorted(bids, reverse=True)
    if rule == "second-price":
        return ordered[1] if len(ordered) > 1 else 0
    return ordered[0] if ordered else 0


def compute_paid_batch(
    second_price: NDArray[np.bool_],
    bids: NDArray[np.integer],
) -> NDArray[np.int16]:
    """Vectorised ``compute_paid``: row ``i`` is priced second-price when
    ``second_price[i]`` and first-price otherwise. ``bids`` is ``(batch, seats)``."""
    if bids.ndim != 2 or bids.shape[1] < 2:
        raise ValueError("bids must be a (batch, seats) array with at least two seats")
    top_two = -np.partition(-bids.astype(np.int16, copy=False), 1, axis=1)[:, :2]
    return np.where(second_price, top_two[:, 1], top_two[:, 0]).astype(np.int16, copy=False)


@dataclass(frozen=True)
class Ruleset:
    """The game-defining settings, mirroring the server's ruleset in snake_case.

    :param player_count: 3-5.
    :param value_chart: a fixed chart key ``"A"``-``"E"`` or an inline chart of
        6 integers inside the constraint envelope (cells may be negative).
    :param payment_rule: ``"first-price"`` (the winner pays their bid) or
        ``"second-price"`` (the winner pays the runner-up bid). The rule flips
        optimal bidding: shade under first-price, bid truthfully under
        second-price.
    :param objectives_enabled: whether the four objective cards are in play.
    """

    player_count: int
    value_chart: str | tuple[int, ...] = "A"
    payment_rule: PaymentRule = "first-price"
    objectives_enabled: bool = True

    def __post_init__(self) -> None:
        if not 3 <= self.player_count <= 5:
            raise ValueError("PocketRocks supports 3-5 players")
        chart = resolve_chart(self.value_chart)
        # Normalise so equal selections compare (and hash) equal: keys upper-case,
        # inline cells as a tuple of plain ints.
        normalised: str | tuple[int, ...] = (
            self.value_chart.upper() if isinstance(self.value_chart, str) else chart
        )
        object.__setattr__(self, "value_chart", normalised)
        _check_payment_rule(self.payment_rule)
        object.__setattr__(self, "objectives_enabled", bool(self.objectives_enabled))

    @property
    def chart(self) -> tuple[int, ...]:
        """The resolved cells. Bots and the engine only ever see these."""
        return resolve_chart(self.value_chart)

    @property
    def chart_label(self) -> str:
        """``"A"``-``"E"`` for fixed charts, ``custom(...)`` with the cells inline
        otherwise; suitable for naming runs and grouping results."""
        if isinstance(self.value_chart, str):
            return self.value_chart
        return "custom(" + ",".join(str(cell) for cell in self.value_chart) + ")"


def coerce_ruleset(
    *,
    player_count: int,
    ruleset: Ruleset | None,
    value_chart: str | Sequence[int] = "A",
    payment_rule: PaymentRule = "first-price",
    objectives_enabled: bool = True,
) -> Ruleset:
    """Fold an entry point's loose keyword arguments into one ``Ruleset``.

    The loose keywords are a convenience over the dataclass, not a second seam:
    when ``ruleset`` is given they must be left at their defaults, and its
    ``player_count`` must match the one implied by the call (the number of
    bots, or the batch's player count).
    """
    if ruleset is None:
        chart_selection: str | tuple[int, ...] = (
            value_chart if isinstance(value_chart, str) else tuple(int(c) for c in value_chart)
        )
        return Ruleset(
            player_count=player_count,
            value_chart=chart_selection,
            payment_rule=payment_rule,
            objectives_enabled=objectives_enabled,
        )
    loose_defaults = (
        value_chart == "A" and payment_rule == "first-price" and objectives_enabled is True
    )
    if not loose_defaults:
        raise ValueError(
            "pass either ruleset= or the loose value_chart/payment_rule/objectives_enabled "
            "keywords, not both"
        )
    if ruleset.player_count != player_count:
        raise ValueError(
            f"ruleset.player_count is {ruleset.player_count} but this call implies "
            f"{player_count} players"
        )
    return ruleset
