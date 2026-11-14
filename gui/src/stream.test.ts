import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import type { RunDetail, Task } from "./api";
import { applyMessage, keys } from "./stream";

const task: Task = {
  id: "t1", run_id: "r1", service: "sherlock", entity_id: "e", depth: 0,
  status: "queued", done: null, total: null, count: 0, error: null,
};

function setup() {
  const client = new QueryClient();
  client.setQueryData<RunDetail>(keys.run("r1"), {
    id: "r1", investigation_id: "i1", selector: "alice", type: "username", entity_id: "e",
    services: ["sherlock"], max_depth: 0, status: "running", created_at: "", finished_at: null,
    tasks: [],
  });
  return client;
}

describe("applyMessage", () => {
  it("moves a task through its life", () => {
    const client = setup();
    const refresh = vi.fn();
    applyMessage(client, "i1", { type: "task.queued", task }, refresh);
    applyMessage(client, "i1", { type: "task.started", run_id: "r1", task_id: "t1" }, refresh);
    applyMessage(client, "i1", { type: "task.progress", run_id: "r1", task_id: "t1", done: 2, total: 9 }, refresh);
    applyMessage(client, "i1", { type: "task.entity", run_id: "r1", task_id: "t1" }, refresh);
    let run = client.getQueryData<RunDetail>(keys.run("r1"))!;
    expect(run.tasks[0]).toMatchObject({ status: "running", done: 2, total: 9, count: 1 });
    expect(refresh).toHaveBeenCalledOnce();

    applyMessage(client, "i1", { type: "task.completed", run_id: "r1", task: { ...task, status: "completed", count: 1 } }, refresh);
    run = client.getQueryData<RunDetail>(keys.run("r1"))!;
    expect(run.tasks[0].status).toBe("completed");
  });

  it("does not add a queued task twice", () => {
    const client = setup();
    applyMessage(client, "i1", { type: "task.queued", task }, () => {});
    applyMessage(client, "i1", { type: "task.queued", task }, () => {});
    expect(client.getQueryData<RunDetail>(keys.run("r1"))!.tasks).toHaveLength(1);
  });
});
