"""Event-bus subscriptions that live exactly as long as a Qt object.

The bus delivers through the event loop, so an event published just before a
widget is destroyed can arrive after it: the callback would touch a deleted
C++ object. ``subscribe_while_alive`` skips delivery to a deleted owner and
unsubscribes when the owner is destroyed.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from functools import partial
from typing import Any

import shiboken6
from karcytics_sdk.plugin import CentralEventBus
from PySide6.QtCore import QObject


def subscribe_while_alive(owner: QObject, handlers: Mapping[str, Callable[[Any], None]]) -> None:
    """Subscribe each ``topic: handler`` until ``owner`` is destroyed."""
    subscribed = []
    for topic, handler in handlers.items():
        deliver = partial(_deliver_if_alive, owner, handler)
        CentralEventBus.subscribe(topic, deliver)
        subscribed.append((topic, deliver))

    def unsubscribe(*_args: Any) -> None:
        for topic, deliver in subscribed:
            CentralEventBus.unsubscribe(topic, deliver)

    owner.destroyed.connect(unsubscribe)


def _deliver_if_alive(owner: QObject, handler: Callable[[Any], None], data: Any) -> None:
    if shiboken6.isValid(owner):
        handler(data)
