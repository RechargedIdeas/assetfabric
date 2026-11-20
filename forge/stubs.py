"""Clearly-labelled stubs (companion track C9–C12).

A stub is an interface that exists so callers, schemas and the cluster router have a stable contract, **without** an
implementation behind it. Calling one never returns made-up output: it raises `StubError`, whose message always starts with
`[STUB <feature> <milestone>]` and carries a locale-keyed reason (what is missing and what would be needed).
`content/companions/c9_c12.yaml` is the register of every real/stub feature; `forge accept C9`…`C12` checks the register against
the code (each stub must refuse with its declared key, each real feature must import and run).
"""

from __future__ import annotations

from typing import NoReturn

from forge.i18n import t

STUB_TAG = "STUB"


class StubError(NotImplementedError):
    """Raised by every stub. `feature` is the register id, `key` the locale key of the reason."""

    def __init__(self, feature: str, key: str, milestone: str, **kw: object) -> None:
        self.feature, self.key, self.milestone = feature, key, milestone
        super().__init__(f"[{STUB_TAG} {feature} {milestone}] {t(key, **kw)}")


def refuse(feature: str, key: str, milestone: str, **kw: object) -> NoReturn:
    raise StubError(feature, key, milestone, **kw)


def is_stub_message(msg: str) -> bool:
    return msg.startswith(f"[{STUB_TAG} ")
