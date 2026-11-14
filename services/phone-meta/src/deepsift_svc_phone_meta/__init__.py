"""DeepSift service: what a phone number says about itself, offline.

Uses Google's libphonenumber data (``phonenumbers``, Apache-2.0): no request leaves the
machine, so nothing can alert the owner. Reports one ``phone_meta`` entity (rel
``metadata``) holding the E.164 form, the country, the geographic area when the
numbering plan has one, the carrier the number was first allocated to (numbers can be
ported since), the line type and the time zones.
"""

from __future__ import annotations

from typing import Any

import phonenumbers
from deepsift_sdk import Entity, EntityType, ErrorCode, Service, ServiceError, Task, TaskContext
from phonenumbers import PhoneNumberFormat, PhoneNumberType, carrier, geocoder, timezone

__all__ = ["PhoneMetaService", "describe", "parse"]

LINE_TYPES = {
    PhoneNumberType.FIXED_LINE: "fixed_line",
    PhoneNumberType.MOBILE: "mobile",
    PhoneNumberType.FIXED_LINE_OR_MOBILE: "fixed_line_or_mobile",
    PhoneNumberType.TOLL_FREE: "toll_free",
    PhoneNumberType.PREMIUM_RATE: "premium_rate",
    PhoneNumberType.SHARED_COST: "shared_cost",
    PhoneNumberType.VOIP: "voip",
    PhoneNumberType.PERSONAL_NUMBER: "personal_number",
    PhoneNumberType.PAGER: "pager",
    PhoneNumberType.UAN: "uan",
    PhoneNumberType.VOICEMAIL: "voicemail",
}


def parse(value: str, default_region: str = "") -> phonenumbers.PhoneNumber:
    """Parse a number; without +country code, ``default_region`` is required."""
    region = default_region.upper() or None
    if not value.startswith("+") and region is None:
        raise ServiceError(
            ErrorCode.INVALID_INPUT,
            "number has no country code: write it as +33… or set the default_region option",
        )
    try:
        return phonenumbers.parse(value, region)
    except phonenumbers.NumberParseException as exc:
        raise ServiceError(ErrorCode.INVALID_INPUT, f"not a phone number: {exc}") from exc


def describe(number: phonenumbers.PhoneNumber, lang: str = "en") -> dict[str, Any]:
    region = phonenumbers.region_code_for_number(number)
    country_name = geocoder.country_name_for_number(number, lang)
    area = geocoder.description_for_number(number, lang)
    attributes: dict[str, Any] = {
        "e164": phonenumbers.format_number(number, PhoneNumberFormat.E164),
        "international": phonenumbers.format_number(number, PhoneNumberFormat.INTERNATIONAL),
        "national": phonenumbers.format_number(number, PhoneNumberFormat.NATIONAL),
        "country_code": number.country_code,
        "country": region,
        "country_name": country_name or None,
        "area": area if area and area != country_name else None,
        "carrier": carrier.name_for_number(number, lang) or None,
        "line_type": LINE_TYPES.get(phonenumbers.number_type(number), "unknown"),
        "valid": phonenumbers.is_valid_number(number),
        "possible": phonenumbers.is_possible_number(number),
        "time_zones": [tz for tz in timezone.time_zones_for_number(number) if tz != "Etc/Unknown"],
    }
    return {k: v for k, v in attributes.items() if v not in (None, [])}


class PhoneMetaService(Service):
    async def run(self, task: Task, ctx: TaskContext) -> None:
        number = parse(task.input.value, str(ctx.option("default_region") or ""))
        attributes = describe(number, str(ctx.option("lang") or "en"))
        if not attributes["valid"]:
            await ctx.progress(1, 1, "not a valid number for its country's numbering plan")
        await ctx.found(
            Entity(type=EntityType.PHONE_META, value=attributes["e164"], attributes=attributes),
            rel="metadata",
        )
