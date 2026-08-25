from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from hansard.domain.errors import DeliveryError
from hansard.domain.meeting import DeliveryChannel, DeliveryTarget
from hansard.ports.delivery import MinutesPublisher, Payload


def address_scheme(address: str) -> str:
    text = address.strip()
    scheme, separator, _ = text.partition(":")
    if not separator:
        return ""
    normalised = scheme.strip().lower()
    return "https" if normalised in {"http", "https"} else normalised


@dataclass(frozen=True, slots=True)
class AddressRoutedPublisher:
    routed_channel: DeliveryChannel
    routes: Mapping[str, MinutesPublisher]
    guidance: str = ""

    @property
    def channel(self) -> DeliveryChannel:
        return self.routed_channel

    def route_for(self, address: str) -> MinutesPublisher:
        scheme = address_scheme(address)
        publisher = self.routes.get(scheme)
        if publisher is None:
            known = ", ".join(f"{name}:" for name in sorted(self.routes)) or "none"
            raise DeliveryError(
                f"no delivery route for address '{address}' on channel {self.routed_channel}; "
                f"available address schemes: {known}. {self.guidance}".strip()
            )
        return publisher

    async def publish(self, target: DeliveryTarget, payload: Payload) -> None:
        await self.route_for(target.address).publish(target, payload)
