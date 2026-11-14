// Redis Streams worker (contract sections 4 and 5), same streams and keys as the Python SDK.

import { hostname } from "node:os";

import { createClient } from "redis";

import { newId } from "./contract.js";
import { manifest } from "./manifest.js";

const HEARTBEAT_EVERY_MS = 15_000;
const HEARTBEAT_TTL_S = 45;
const EVENTS_MAXLEN = 100_000;

/**
 * @param {{url: string, prefix?: string, isReady: () => boolean, handle: (task, emit) => Promise<void>,
 *          signal?: AbortSignal, log?: (msg: string) => void}} options
 */
export async function serve({ url, prefix = "deepsift", isReady, handle, signal, log = () => {} }) {
  const client = createClient({ url });
  await client.connect();
  const name = manifest.name;
  const instance = `${hostname()}-${newId().slice(-6).toLowerCase()}`;
  const tasks = `${prefix}:tasks:${name}`;
  let running = 0;

  try {
    await client.xGroupCreate(tasks, name, "0", { MKSTREAM: true });
  } catch (error) {
    if (!String(error.message).includes("BUSYGROUP")) throw error;
  }

  const state = () => (running ? "busy" : isReady() ? "ready" : "needs_config");
  await client.xAdd(`${prefix}:registry`, "*", {
    event: "register",
    service: name,
    instance,
    state: state(),
    manifest: JSON.stringify(manifest),
  });
  log(`${name} ${manifest.version} registered as ${instance} (${state()})`);

  const beat = async () => {
    await client.set(
      `${prefix}:heartbeat:${name}:${instance}`,
      JSON.stringify({
        state: state(),
        running,
        missing: isReady() ? [] : ["link the account: deepsift-whatsapp link"],
      }),
      { EX: HEARTBEAT_TTL_S },
    );
  };
  await beat();
  const timer = setInterval(() => beat().catch((e) => log(`heartbeat failed: ${e.message}`)), HEARTBEAT_EVERY_MS);

  const emit = async (event) => {
    await client.xAdd(
      `${prefix}:events`,
      "*",
      { data: JSON.stringify(event) },
      { TRIM: { strategy: "MAXLEN", strategyModifier: "~", threshold: EVENTS_MAXLEN } },
    );
  };

  try {
    while (!signal?.aborted) {
      if (!isReady()) {
        await new Promise((resolve) => setTimeout(resolve, 5_000));
        continue;
      }
      const reply = await client.xReadGroup(name, instance, { key: tasks, id: ">" }, { COUNT: 1, BLOCK: 5_000 });
      for (const stream of reply ?? []) {
        for (const { id, message } of stream.messages) {
          running += 1;
          try {
            await handle(JSON.parse(message.data), emit);
          } finally {
            running -= 1;
            await client.xAck(tasks, name, id);
          }
        }
      }
    }
  } finally {
    clearInterval(timer);
    await client.xAdd(`${prefix}:registry`, "*", { event: "deregister", service: name, instance });
    await client.quit();
  }
}
