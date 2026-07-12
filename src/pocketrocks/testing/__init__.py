"""Test kit for bots built on the SDK.

Opt-in, import-when-you-test tooling — kept out of the top-level ``pocketrocks``
namespace so the authoring surface stays tiny. Narrate a game situation with
:func:`scenario` to derive a realistic ``DecisionContext`` for a ``choose_decision``
test, or feed :func:`Scenario.to_bytes` through :class:`FakeTransport` to drive a
bot end-to-end.
"""

from pocketrocks.testing.scenario import Scenario, scenario
from pocketrocks.testing.transport import FakeTransport, decode_frames, heartbeat_bytes

__all__ = [
    "scenario",
    "Scenario",
    "FakeTransport",
    "decode_frames",
    "heartbeat_bytes",
]
