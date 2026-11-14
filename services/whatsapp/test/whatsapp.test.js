import assert from "node:assert/strict";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, it } from "node:test";

import { ErrorCode, ServiceError, newId } from "../src/contract.js";
import { Limiter } from "../src/limiter.js";
import { lookup, toE164 } from "../src/lookup.js";
import { manifest } from "../src/manifest.js";
import { runTask } from "../src/runtask.js";

const JID = "33612345678@s.whatsapp.net";

function fakeSock({ exists = true, picture, about, business, pictureError } = {}) {
  const calls = [];
  return {
    calls,
    async onWhatsApp(phone) {
      calls.push(["onWhatsApp", phone]);
      return exists ? [{ jid: JID, exists: true }] : [];
    },
    async profilePictureUrl(jid, type) {
      calls.push(["profilePictureUrl", jid, type]);
      if (pictureError) throw pictureError;
      return picture;
    },
    async fetchStatus(jid) {
      calls.push(["fetchStatus", jid]);
      return about === undefined ? [] : [{ id: jid, status: about }];
    },
    async getBusinessProfile(jid) {
      calls.push(["getBusinessProfile", jid]);
      return business;
    },
  };
}

const task = (value = "+33612345678", options = {}) => ({
  contract: 1,
  task_id: newId(),
  service: "whatsapp",
  input: { id: "ent_input", type: "phone", value },
  options: { min_interval: 0, ...options },
});

const noLimit = () => ({ acquire: async () => ({ remaining: 49 }) });

async function run(t, sock, limiterFor = noLimit) {
  const out = [];
  await runTask(t, { getSock: async () => sock, limiterFor, emit: async (e) => out.push(e) });
  return out;
}

describe("contract", () => {
  it("makes sortable 26-character ULIDs", () => {
    const a = newId(1_700_000_000_000);
    const b = newId(1_700_000_000_001);
    assert.equal(a.length, 26);
    assert.ok(a.slice(0, 10) < b.slice(0, 10));
  });

  it("ships a manifest the Python SDK accepts", () => {
    assert.equal(manifest.name, "whatsapp");
    assert.deepEqual(manifest.inputs, ["phone"]);
    assert.equal(manifest.enabled_by_default, false);
    assert.equal(manifest.concurrency, 1);
  });
});

describe("toE164", () => {
  it("accepts international numbers only", () => {
    assert.equal(toE164("+33 6 12-34.56(78)"), "+33612345678");
    assert.equal(toE164("0612345678"), null);
    assert.equal(toE164("+0612"), null);
  });
});

describe("lookup", () => {
  it("returns only that the number is not registered", async () => {
    const sock = fakeSock({ exists: false });
    assert.deepEqual(await lookup(sock, "+33612345678", { picture: true, about: true, business: true }), {
      exists: false,
    });
    assert.deepEqual(sock.calls, [["onWhatsApp", "33612345678"]]);
  });

  it("collects what the privacy settings show", async () => {
    const sock = fakeSock({
      picture: "https://pps.whatsapp.net/v/p.jpg",
      about: { status: "Hey there", setAt: new Date("2025-01-02T03:04:05Z") },
      business: { email: "Shop@Example.org", category: "Shop", website: ["https://shop.example"] },
    });
    const found = await lookup(sock, "+33612345678", { picture: true, about: true, business: true });
    assert.equal(found.jid, JID);
    assert.equal(found.picture, "https://pps.whatsapp.net/v/p.jpg");
    assert.equal(found.about, "Hey there");
    assert.equal(found.aboutSetAt, "2025-01-02T03:04:05.000Z");
    assert.equal(found.business.category, "Shop");
  });

  it("treats a hidden picture as absent", async () => {
    const sock = fakeSock({ pictureError: Object.assign(new Error("not-authorized"), { data: 401 }) });
    const found = await lookup(sock, "+33612345678", { picture: true, about: false, business: false });
    assert.equal(found.exists, true);
    assert.equal(found.picture, undefined);
  });

  it("skips what was not asked for", async () => {
    const sock = fakeSock({ picture: "x" });
    await lookup(sock, "+33612345678", { picture: false, about: false, business: false });
    assert.deepEqual(sock.calls.map((c) => c[0]), ["onWhatsApp"]);
  });
});

describe("runTask", () => {
  it("emits profile, avatar and business email linked together", async () => {
    const sock = fakeSock({
      picture: "https://pps.whatsapp.net/v/p.jpg",
      about: { status: "Busy", setAt: new Date(0) },
      business: { email: "Shop@Example.org", category: "Shop" },
    });
    const t = task();
    const out = await run(t, sock);
    assert.deepEqual(out.map((e) => e.event), ["started", "entity", "entity", "entity", "progress", "completed"]);
    for (const e of out) {
      assert.equal(e.contract, 1);
      assert.equal(e.task_id, t.task_id);
      assert.equal(e.service, "whatsapp");
    }
    const [profile, image, email] = out.filter((e) => e.event === "entity");
    assert.equal(profile.entity.type, "profile");
    assert.equal(profile.entity.value, "https://wa.me/33612345678");
    assert.deepEqual(profile.link, { from: "ent_input", rel: "found_on" });
    assert.equal(profile.entity.attributes.about, "Busy");
    assert.equal(profile.entity.attributes.about_set_at, undefined);
    assert.equal(profile.entity.attributes.business, true);
    assert.deepEqual(image.link, { from: profile.entity.id, rel: "avatar" });
    assert.equal(email.entity.value, "shop@example.org");
    assert.equal(email.link.rel, "business_email");
    assert.equal(out.at(-1).count, 3);
  });

  it("reports an unregistered number as a message, not an error", async () => {
    const out = await run(task(), fakeSock({ exists: false }));
    assert.deepEqual(out.map((e) => e.event), ["started", "progress", "completed"]);
    assert.match(out[1].message, /no WhatsApp account/);
  });

  it("rejects local numbers and other entity types", async () => {
    let out = await run(task("0612345678"), fakeSock());
    assert.equal(out.at(-1).error.code, ErrorCode.INVALID_INPUT);
    const t = task();
    t.input.type = "email";
    out = await run(t, fakeSock());
    assert.equal(out.at(-1).error.code, ErrorCode.INVALID_INPUT);
  });

  it("does not touch WhatsApp when the daily cap is spent", async () => {
    const sock = fakeSock();
    const capped = () => ({
      acquire: async () => {
        throw new ServiceError(ErrorCode.RATE_LIMITED, "daily limit", false);
      },
    });
    const out = await run(task(), sock, capped);
    assert.deepEqual(out.at(-1).error, { code: "rate_limited", message: "daily limit", retryable: false });
    assert.equal(sock.calls.length, 0);
  });

  it("does not spend the quota when no account is linked", async () => {
    let acquired = false;
    const out = [];
    await runTask(task(), {
      getSock: async () => {
        throw new ServiceError(ErrorCode.NEEDS_CONFIG, "not linked");
      },
      limiterFor: () => ({ acquire: async () => (acquired = true) }),
      emit: async (e) => out.push(e),
    });
    assert.equal(out.at(-1).error.code, ErrorCode.NEEDS_CONFIG);
    assert.equal(acquired, false);
  });

  it("passes task options to the limiter", async () => {
    let seen;
    const spy = (limits) => {
      seen = limits;
      return { acquire: async () => ({ remaining: 1 }) };
    };
    await run(task("+33612345678", { min_interval: 30, daily_limit: 5 }), fakeSock(), spy);
    assert.deepEqual(seen, { minInterval: 30, dailyLimit: 5 });
  });

  it("turns unexpected errors into retryable upstream errors", async () => {
    const sock = fakeSock();
    sock.onWhatsApp = async () => {
      throw new Error("socket hang up");
    };
    const out = await run(task(), sock);
    assert.equal(out.at(-1).error.code, ErrorCode.UPSTREAM_ERROR);
    assert.equal(out.at(-1).error.retryable, true);
  });
});

describe("Limiter", () => {
  async function limiter(limits) {
    const dir = await mkdtemp(join(tmpdir(), "wa-limiter-"));
    let now = Date.parse("2026-11-14T10:00:00Z");
    const slept = [];
    const clock = {
      now: () => now,
      sleep: async (ms) => {
        slept.push(ms);
        now += ms;
      },
    };
    return { make: () => new Limiter(dir, limits, clock), slept, advance: (ms) => (now += ms) };
  }

  it("spaces lookups by min_interval", async () => {
    const { make, slept, advance } = await limiter({ minInterval: 10, dailyLimit: 50 });
    await make().acquire();
    advance(3_000);
    await make().acquire(); // another process, same state file
    assert.deepEqual(slept, [7_000]);
  });

  it("enforces the daily cap and resets the next UTC day", async () => {
    const { make, advance } = await limiter({ minInterval: 0, dailyLimit: 2 });
    assert.equal((await make().acquire()).remaining, 1);
    assert.equal((await make().acquire()).remaining, 0);
    await assert.rejects(make().acquire(), (error) => error.code === ErrorCode.RATE_LIMITED && !error.retryable);
    advance(24 * 3600 * 1000);
    assert.equal((await make().acquire()).remaining, 1);
  });
});
