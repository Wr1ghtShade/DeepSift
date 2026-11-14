#!/usr/bin/env node
// deepsift-whatsapp: link a dedicated account, then serve lookups (stdio or Redis).

import { createInterface } from "node:readline";
import { rm } from "node:fs/promises";

import qrcode from "qrcode-terminal";

import { ErrorCode, ServiceError, events } from "./contract.js";
import { Limiter } from "./limiter.js";
import { dataDir, manifest } from "./manifest.js";
import { runTask } from "./runtask.js";
import { authDirOf, close, connect, isLinked } from "./session.js";
import { serve } from "./worker.js";

const DATA = dataDir();
const say = (msg) => process.stderr.write(`${msg}\n`);

function sessionProvider() {
  let sock;
  return {
    async get() {
      if (!isLinked(DATA)) {
        throw new ServiceError(
          ErrorCode.NEEDS_CONFIG,
          'no WhatsApp account is linked: run "deepsift-whatsapp link" with a dedicated account',
        );
      }
      if (!sock) {
        sock = await connect(DATA);
        sock.ev.on("connection.update", ({ connection }) => {
          if (connection === "close") sock = undefined;
        });
      }
      return sock;
    },
    async close() {
      await close(sock);
      sock = undefined;
    },
  };
}

const limiterFor = (limits) => new Limiter(DATA, limits);

async function readTask() {
  const lines = createInterface({ input: process.stdin });
  for await (const line of lines) {
    if (line.trim()) return JSON.parse(line);
  }
  throw new Error("no task on stdin");
}

const commands = {
  async link(args) {
    const i = args.indexOf("--phone");
    const pairingPhone = i >= 0 ? args[i + 1] : undefined;
    say("Use a DEDICATED WhatsApp account, never your personal or work number.");
    say(
      pairingPhone
        ? "WhatsApp > Linked devices > Link with phone number, then type this code:"
        : "WhatsApp > Linked devices > Link a device, then scan:",
    );
    const sock = await connect(DATA, {
      pairingPhone,
      timeoutMs: 180_000,
      onQr: ({ qr, pairingCode }) => {
        if (pairingCode) say(`\n    ${pairingCode}\n`);
        if (qr) qrcode.generate(qr, { small: true }, (art) => say(art));
      },
    });
    say(`Linked as ${sock.user?.id ?? "unknown"}. Session kept in ${authDirOf(DATA)}`);
    await new Promise((resolve) => setTimeout(resolve, 3_000)); // let creds flush
    await close(sock);
  },

  async status() {
    say(isLinked(DATA) ? `linked (${authDirOf(DATA)})` : "not linked");
    process.exitCode = isLinked(DATA) ? 0 : 1;
  },

  async unlink() {
    await rm(authDirOf(DATA), { recursive: true, force: true });
    say("Local session removed. Also remove the device in WhatsApp > Linked devices.");
  },

  // One task as a JSON line on stdin, events as JSON lines on stdout (local mode).
  async stdio() {
    const session = sessionProvider();
    let task;
    try {
      task = await readTask();
    } catch (error) {
      const ev = events({ task_id: "unknown" }, manifest.name);
      process.stdout.write(`${JSON.stringify(ev.failed({ code: ErrorCode.INVALID_INPUT, message: error.message }))}\n`);
      return;
    }
    try {
      await runTask(task, {
        getSock: () => session.get(),
        limiterFor,
        emit: async (event) => {
          process.stdout.write(`${JSON.stringify(event)}\n`);
        },
      });
    } finally {
      await session.close();
    }
  },

  async check([number]) {
    if (!number) throw new Error("usage: deepsift-whatsapp check +33612345678");
    const task = { contract: 1, task_id: "cli", service: "whatsapp", input: { id: "cli", type: "phone", value: number } };
    const session = sessionProvider();
    try {
      await runTask(task, {
        getSock: () => session.get(),
        limiterFor,
        emit: async (event) => {
          if (event.event === "entity") say(`${event.link.rel}: ${event.entity.value} ${JSON.stringify(event.entity.attributes)}`);
          if (event.event === "progress" && event.message) say(event.message);
          if (event.event === "failed") say(`failed: ${event.error.code}: ${event.error.message}`);
        },
      });
    } finally {
      await session.close();
    }
  },

  async worker() {
    const session = sessionProvider();
    const controller = new AbortController();
    for (const sig of ["SIGINT", "SIGTERM"]) process.on(sig, () => controller.abort());
    if (!isLinked(DATA)) say('Not linked yet: run "deepsift-whatsapp link". Waiting…');
    try {
      await serve({
        url: process.env.REDIS_URL ?? "redis://localhost:6379/0",
        isReady: () => isLinked(DATA),
        signal: controller.signal,
        log: say,
        handle: (task, emit) => runTask(task, { getSock: () => session.get(), limiterFor, emit }),
      });
    } finally {
      await session.close();
    }
  },
};

const [name, ...args] = process.argv.slice(2);
if (!commands[name]) {
  say("usage: deepsift-whatsapp link [--phone +33…] | status | unlink | check <number> | stdio | worker");
  process.exit(2);
}
try {
  await commands[name](args);
  process.exit(process.exitCode ?? 0);
} catch (error) {
  say(`error: ${error.message}`);
  process.exit(1);
}
