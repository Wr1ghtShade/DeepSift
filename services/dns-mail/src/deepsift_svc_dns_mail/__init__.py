"""DeepSift service: MX records of an email address or a domain.

Each mail server becomes an ``mx_record`` entity (rel ``mail_server``) with its priority
and, when it can be recognised, the provider that runs it (Google Workspace,
Microsoft 365, Proton…). A domain with no MX record cannot receive mail: that is
reported as a progress message and no entity.

DNS goes through the system resolver, or DNS over HTTPS when ``resolver: doh`` (useful
behind an HTTP proxy, where plain DNS is often unavailable).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import dns.asyncresolver
import dns.exception
import dns.message
import dns.rcode
import dns.rdatatype
import dns.resolver
import httpx
from deepsift_sdk import Entity, EntityType, ErrorCode, Service, ServiceError, Task, TaskContext

__all__ = ["DnsMailService", "provider_of"]

Lookup = Callable[[str], Awaitable[list[tuple[int, str]]]]

#: MX host suffix -> provider. First match wins, so specific entries come first.
PROVIDERS: tuple[tuple[str, str], ...] = (
    ("aspmx.l.google.com", "Google Workspace"),
    ("google.com", "Google Workspace"),
    ("googlemail.com", "Google"),
    ("mail.protection.outlook.com", "Microsoft 365"),
    ("outlook.com", "Microsoft"),
    ("hotmail.com", "Microsoft"),
    ("protonmail.ch", "Proton Mail"),
    ("proton.me", "Proton Mail"),
    ("icloud.com", "Apple iCloud"),
    ("yahoodns.net", "Yahoo"),
    ("zoho.com", "Zoho"),
    ("zoho.eu", "Zoho"),
    ("yandex.net", "Yandex"),
    ("mail.ru", "Mail.ru"),
    ("ovh.net", "OVHcloud"),
    ("gandi.net", "Gandi"),
    ("ionos.fr", "IONOS"),
    ("ionos.com", "IONOS"),
    ("kundenserver.de", "IONOS"),
    ("secureserver.net", "GoDaddy"),
    ("orange.fr", "Orange"),
    ("free.fr", "Free"),
    ("sfr.fr", "SFR"),
    ("laposte.net", "La Poste"),
    ("infomaniak.ch", "Infomaniak"),
    ("fastmail.com", "Fastmail"),
    ("messagingengine.com", "Fastmail"),
    ("mimecast.com", "Mimecast (filtering)"),
    ("pphosted.com", "Proofpoint (filtering)"),
    ("messagelabs.com", "Broadcom Email Security (filtering)"),
    ("barracudanetworks.com", "Barracuda (filtering)"),
    ("iphmx.com", "Cisco Secure Email (filtering)"),
    ("amazonaws.com", "Amazon SES"),
    ("mailgun.org", "Mailgun"),
    ("sendgrid.net", "SendGrid"),
)


def provider_of(host: str) -> str | None:
    host = host.lower().rstrip(".")
    for suffix, provider in PROVIDERS:
        if host == suffix or host.endswith("." + suffix):
            return provider
    return None


class NoSuchDomain(Exception):
    """The domain does not exist (NXDOMAIN)."""


async def system_lookup(domain: str) -> list[tuple[int, str]]:
    try:
        answer = await dns.asyncresolver.resolve(domain, "MX", lifetime=10)
    except dns.resolver.NXDOMAIN as exc:
        raise NoSuchDomain(domain) from exc
    except dns.resolver.NoAnswer:
        return []
    return [(r.preference, r.exchange.to_text()) for r in answer]


def doh_lookup(url: str, transport: httpx.AsyncBaseTransport | None = None) -> Lookup:
    """DNS over HTTPS (RFC 8484) through httpx, so HTTP(S)_PROXY is honoured."""

    async def lookup(domain: str) -> list[tuple[int, str]]:
        query = dns.message.make_query(domain, dns.rdatatype.MX)
        query.id = 0  # RFC 8484: id 0 keeps answers cacheable
        async with httpx.AsyncClient(transport=transport, timeout=10.0) as client:
            response = await client.post(
                url,
                content=query.to_wire(),
                headers={
                    "content-type": "application/dns-message",
                    "accept": "application/dns-message",
                },
            )
        response.raise_for_status()
        answer = dns.message.from_wire(response.content)
        if answer.rcode() == dns.rcode.NXDOMAIN:
            raise NoSuchDomain(domain)
        return [
            (r.preference, r.exchange.to_text())
            for rrset in answer.answer
            if rrset.rdtype == dns.rdatatype.MX
            for r in rrset
        ]

    return lookup


class DnsMailService(Service):
    async def run(self, task: Task, ctx: TaskContext) -> None:
        value = task.input.value
        domain = value.rsplit("@", 1)[1] if task.input.type is EntityType.EMAIL else value
        if not domain or "." not in domain:
            raise ServiceError(ErrorCode.INVALID_INPUT, "no domain to look up")

        lookup = self.lookup_for(str(ctx.option("resolver")), str(ctx.option("doh_url")))
        try:
            records = await lookup(domain)
        except NoSuchDomain:
            await ctx.progress(1, 1, f"{domain} does not exist")
            return
        except (dns.exception.Timeout, httpx.TimeoutException) as exc:
            raise ServiceError(ErrorCode.TIMEOUT, "DNS lookup timed out") from exc
        except Exception as exc:  # noqa: BLE001 - resolver errors vary by transport
            raise ServiceError(
                ErrorCode.UPSTREAM_ERROR, f"DNS lookup failed: {type(exc).__name__}"
            ) from exc

        records = [(p, h.rstrip(".").lower()) for p, h in records if h.rstrip(".")]
        if not records:
            await ctx.progress(1, 1, f"{domain} has no MX record: it cannot receive mail")
            return
        for priority, host in sorted(records):
            attributes = {"domain": domain, "priority": priority}
            provider = provider_of(host)
            if provider:
                attributes["provider"] = provider
            await ctx.found(
                Entity(type=EntityType.MX_RECORD, value=host, attributes=attributes),
                rel="mail_server",
            )

    def lookup_for(self, resolver: str, doh_url: str) -> Lookup:
        return doh_lookup(doh_url) if resolver == "doh" else system_lookup
