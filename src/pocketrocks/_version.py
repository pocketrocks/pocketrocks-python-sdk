"""Single source of truth for the SDK version and the rules revision it implements.

``RULES_VERSION`` increments whenever the canonical game rules change (and the
golden-trace fixtures are regenerated). The update check fetches this file from
the repo's ``develop`` branch to warn stale installs.
"""

__version__ = "0.4.0"
RULES_VERSION = 2
