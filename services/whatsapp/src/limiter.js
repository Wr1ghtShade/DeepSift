// Protects the linked WhatsApp account: a minimum gap between lookups and a daily cap.
// State lives in a small JSON file so the CLI and the worker share the same budget.
// A lock file serialises concurrent processes on one machine.

import { mkdir, open, readFile, rename, rm, stat, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";

import { ErrorCode, ServiceError } from "./contract.js";

const LOCK_STALE_MS = 120_000;

export class Limiter {
  /**
   * @param {string} dir folder for state and lock files
   * @param {{minInterval: number, dailyLimit: number}} limits seconds, lookups per UTC day
   * @param {{now?: () => number, sleep?: (ms: number) => Promise<void>}} clock for tests
   */
  constructor(dir, limits, clock = {}) {
    this.stateFile = join(dir, "limiter.json");
    this.lockFile = join(dir, "limiter.lock");
    this.minIntervalMs = Math.max(0, Number(limits.minInterval)) * 1000;
    this.dailyLimit = Math.max(1, Number(limits.dailyLimit));
    this.now = clock.now ?? Date.now;
    this.sleep = clock.sleep ?? ((ms) => new Promise((resolve) => setTimeout(resolve, ms)));
  }

  /** Waits for the next allowed slot and records it. Throws when today's cap is spent. */
  async acquire() {
    await mkdir(dirname(this.stateFile), { recursive: true });
    await this.#lock();
    try {
      const state = await this.#read();
      const today = new Date(this.now()).toISOString().slice(0, 10);
      if (state.day !== today) Object.assign(state, { day: today, count: 0 });
      if (state.count >= this.dailyLimit) {
        throw new ServiceError(
          ErrorCode.RATE_LIMITED,
          `daily limit of ${this.dailyLimit} WhatsApp lookups reached; it resets at 00:00 UTC`,
          false,
        );
      }
      const wait = (state.last ?? 0) + this.minIntervalMs - this.now();
      if (wait > 0) await this.sleep(wait);
      state.last = this.now();
      state.count += 1;
      await this.#write(state);
      return { remaining: this.dailyLimit - state.count };
    } finally {
      await rm(this.lockFile, { force: true });
    }
  }

  async #read() {
    try {
      return JSON.parse(await readFile(this.stateFile, "utf8"));
    } catch {
      return { day: null, count: 0, last: 0 };
    }
  }

  async #write(state) {
    const tmp = `${this.stateFile}.tmp`;
    await writeFile(tmp, JSON.stringify(state));
    await rename(tmp, this.stateFile);
  }

  async #lock() {
    for (;;) {
      try {
        const handle = await open(this.lockFile, "wx");
        await handle.close();
        return;
      } catch (error) {
        if (error.code !== "EEXIST") throw error;
        const info = await stat(this.lockFile).catch(() => null);
        if (info && this.now() - info.mtimeMs > LOCK_STALE_MS) {
          await rm(this.lockFile, { force: true });
          continue;
        }
        await new Promise((resolve) => setTimeout(resolve, 200));
      }
    }
  }
}
