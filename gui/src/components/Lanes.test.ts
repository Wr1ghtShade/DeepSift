import { describe, expect, it } from "vitest";
import type { Task } from "../api";
import { lanesOf } from "./Lanes";

const task = (service: string, status: Task["status"], count = 0, extra: Partial<Task> = {}): Task => ({
  id: `${service}-${Math.random()}`,
  run_id: "run",
  service,
  entity_id: "e",
  depth: 0,
  status,
  done: null,
  total: null,
  count,
  error: null,
  ...extra,
});

describe("lanesOf", () => {
  it("groups tasks per service and sums findings", () => {
    const lanes = lanesOf([
      task("sherlock", "completed", 4),
      task("avatar-hash", "completed", 1),
      task("avatar-hash", "running", 0),
      task("avatar-hash", "failed", 0, { error: { code: "timeout", message: "", retryable: true } }),
    ]);
    expect(lanes.map((l) => l.service)).toEqual(["sherlock", "avatar-hash"]);
    const hash = lanes[1];
    expect(hash).toMatchObject({ tasks: 3, finished: 2, failed: 1, running: 1, hits: 1, error: "Délai dépassé" });
  });

  it("keeps the progress of a single task", () => {
    const [lane] = lanesOf([task("maigret", "running", 3, { done: 120, total: 500 })]);
    expect(lane.done).toBe(120);
    expect(lane.total).toBe(500);
  });
});
