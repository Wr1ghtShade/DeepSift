"""Unit tests: DNS answers are faked, nothing leaves the machine."""

from __future__ import annotations

import deepsift_svc_dns_mail as svc
import dns.exception
import pytest
from deepsift_sdk import Entity, EntityType, ErrorCode, EventKind, Task, execute


async def run_task(monkeypatch, entity_type, value, answer=None, error=None, **options):
    asked = []

    async def lookup(domain):
        asked.append(domain)
        if error:
            raise error
        return answer or []

    monkeypatch.setattr(svc.DnsMailService, "lookup_for", lambda self, r, u: lookup)
    task = Task(service="dns-mail", input=Entity(type=entity_type, value=value), options=options)
    events = []

    async def sink(event):
        events.append(event)

    final = await execute(svc.DnsMailService(), task, sink)
    return events, final, asked


@pytest.mark.parametrize(
    ("host", "provider"),
    [
        ("aspmx.l.google.com.", "Google Workspace"),
        ("example-org.mail.protection.outlook.com", "Microsoft 365"),
        ("mail.protonmail.ch", "Proton Mail"),
        ("mx1.mail.ovh.net", "OVHcloud"),
        ("mx.example.org", None),
        ("notgoogle.com", None),
    ],
)
def test_provider_of(host, provider):
    assert svc.provider_of(host) == provider


async def test_email_reports_sorted_mx_with_providers(monkeypatch):
    answer = [(10, "alt1.aspmx.l.google.com."), (1, "aspmx.l.google.com.")]
    events, final, asked = await run_task(
        monkeypatch, EntityType.EMAIL, "night.owl@Example.org", answer
    )
    assert asked == ["example.org"]
    found = [e.entity for e in events if e.event is EventKind.ENTITY]
    assert [(m.value, m.attributes["priority"]) for m in found] == [
        ("aspmx.l.google.com", 1),
        ("alt1.aspmx.l.google.com", 10),
    ]
    assert {m.attributes["provider"] for m in found} == {"Google Workspace"}
    assert final.count == 2


async def test_domain_input(monkeypatch):
    _, _, asked = await run_task(
        monkeypatch, EntityType.DOMAIN, "example.fr", [(5, "mx.example.fr")]
    )
    assert asked == ["example.fr"]


async def test_no_mx_is_a_message_not_an_error(monkeypatch):
    events, final, _ = await run_task(monkeypatch, EntityType.DOMAIN, "example.org", [])
    assert final.event is EventKind.COMPLETED
    assert any("cannot receive mail" in (e.message or "") for e in events)


@pytest.mark.parametrize(
    ("error", "code"),
    [(dns.exception.Timeout(), ErrorCode.TIMEOUT), (OSError("no route"), ErrorCode.UPSTREAM_ERROR)],
)
async def test_resolver_errors(monkeypatch, error, code):
    _, final, _ = await run_task(monkeypatch, EntityType.DOMAIN, "example.org", error=error)
    assert final.error.code is code


async def test_missing_domain_is_a_message(monkeypatch):
    events, final, _ = await run_task(
        monkeypatch, EntityType.DOMAIN, "nope.example", error=svc.NoSuchDomain("nope.example")
    )
    assert final.event is EventKind.COMPLETED
    assert any("does not exist" in (e.message or "") for e in events)


async def test_doh_lookup_speaks_rfc8484():
    import dns.message
    import dns.rdatatype
    import dns.rrset
    import httpx

    seen = []

    def handler(request):
        seen.append(request)
        query = dns.message.from_wire(request.content)
        reply = dns.message.make_response(query)
        reply.answer.append(
            dns.rrset.from_text(query.question[0].name, 300, "IN", "MX", "10 mx.example.org.")
        )
        return httpx.Response(200, content=reply.to_wire())

    lookup = svc.doh_lookup("https://doh.example/dns-query", httpx.MockTransport(handler))
    assert await lookup("example.org") == [(10, "mx.example.org.")]
    assert seen[0].headers["content-type"] == "application/dns-message"
    assert dns.message.from_wire(seen[0].content).question[0].rdtype == dns.rdatatype.MX


async def test_doh_nxdomain():
    import dns.message
    import dns.rcode
    import httpx

    def handler(request):
        reply = dns.message.make_response(dns.message.from_wire(request.content))
        reply.set_rcode(dns.rcode.NXDOMAIN)
        return httpx.Response(200, content=reply.to_wire())

    lookup = svc.doh_lookup("https://doh.example/dns-query", httpx.MockTransport(handler))
    with pytest.raises(svc.NoSuchDomain):
        await lookup("nope.example")


def test_resolver_choice():
    service = svc.DnsMailService()
    assert service.lookup_for("system", "") is svc.system_lookup
    assert service.lookup_for("doh", "https://dns.example/dns-query") is not svc.system_lookup
