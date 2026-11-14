// DeepSift service contract v1 (docs/specs/service-contract.md), for JavaScript services.
// Field names match the Python SDK exactly: task_id, event, link.from, error.retryable…

import { randomBytes } from "node:crypto";

export const CONTRACT_VERSION = 1;

export const ErrorCode = Object.freeze({
  INVALID_INPUT: "invalid_input",
  NEEDS_CONFIG: "needs_config",
  RATE_LIMITED: "rate_limited",
  UPSTREAM_ERROR: "upstream_error",
  TIMEOUT: "timeout",
  INTERNAL: "internal",
});

const RETRYABLE = new Set([ErrorCode.RATE_LIMITED, ErrorCode.UPSTREAM_ERROR, ErrorCode.TIMEOUT]);

export class ServiceError extends Error {
  constructor(code, message, retryable = RETRYABLE.has(code)) {
    super(message);
    this.code = code;
    this.retryable = retryable;
  }
}

const ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";

/** A ULID: 48 bits of milliseconds then 80 random bits, Crockford base32. */
export function newId(now = Date.now()) {
  let value = (BigInt(now) << 80n) | BigInt("0x" + randomBytes(10).toString("hex"));
  let out = "";
  for (let i = 0; i < 26; i++) {
    out = ALPHABET[Number(value & 31n)] + out;
    value >>= 5n;
  }
  return out;
}

export function entity(type, value, attributes = {}, confidence = 1.0) {
  return { id: `ent_${newId()}`, type, value, attributes, confidence };
}

/** Builds events for one task, addressed to one service. */
export function events(task, service) {
  const base = (event, fields = {}) => ({
    contract: CONTRACT_VERSION,
    task_id: task.task_id,
    service,
    event,
    ...fields,
  });
  return {
    started: () => base("started"),
    progress: (done, total, message) =>
      base("progress", message ? { done, total, message } : { done, total }),
    entity: (ent, from, rel) => base("entity", { entity: ent, link: { from, rel } }),
    completed: (count) => base("completed", { count }),
    failed: (error) =>
      base("failed", {
        error: {
          code: error.code ?? ErrorCode.INTERNAL,
          message: error.message ?? String(error),
          retryable: error.retryable ?? false,
        },
      }),
  };
}

/** Validates the parts of a task this service relies on. */
export function checkTask(task) {
  if (!task || typeof task !== "object" || !task.task_id || !task.input) {
    throw new ServiceError(ErrorCode.INVALID_INPUT, "malformed task");
  }
  if (task.contract !== undefined && task.contract !== CONTRACT_VERSION) {
    throw new ServiceError(ErrorCode.INVALID_INPUT, `unsupported contract ${task.contract}`);
  }
  return task;
}
