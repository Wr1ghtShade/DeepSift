// Live updates for one investigation over the gateway's WebSocket.
// Task messages patch the cached run directly (the lanes move at once); entity
// messages refresh the table and graph at most a few times per second.
import { type QueryClient, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { type RunDetail, type Task, streamUrl } from "./api";

export type StreamState = "connecting" | "open" | "closed";

type Message =
  | { type: "run.started"; run: { id: string } }
  | { type: "run.completed"; run_id: string; status: string }
  | { type: "task.queued"; task: Task }
  | { type: "task.started"; run_id: string; task_id: string }
  | {
      type: "task.progress";
      run_id: string;
      task_id: string;
      done: number | null;
      total: number | null;
    }
  | { type: "task.entity" | "entity.merged"; run_id: string; task_id: string }
  | { type: "task.completed" | "task.failed"; run_id: string; task: Task }
  | { type: "stream.lagged" };

export const keys = {
  investigation: (id: string) => ["investigation", id] as const,
  run: (id: string) => ["run", id] as const,
  entities: (id: string) => ["entities", id] as const,
  graph: (id: string) => ["graph", id] as const,
};

function patchTask(
  client: QueryClient,
  runId: string,
  taskId: string,
  patch: (task: Task) => Task,
): void {
  client.setQueryData<RunDetail>(keys.run(runId), (run) =>
    run ? { ...run, tasks: run.tasks.map((t) => (t.id === taskId ? patch(t) : t)) } : run,
  );
}

export function applyMessage(
  client: QueryClient,
  investigationId: string,
  message: Message,
  refreshFindings: () => void,
): void {
  switch (message.type) {
    case "run.started":
    case "run.completed":
      void client.invalidateQueries({ queryKey: keys.investigation(investigationId) });
      void client.invalidateQueries({
        queryKey: keys.run(message.type === "run.started" ? message.run.id : message.run_id),
      });
      refreshFindings();
      break;
    case "task.queued":
      client.setQueryData<RunDetail>(keys.run(message.task.run_id), (run) =>
        run && !run.tasks.some((t) => t.id === message.task.id)
          ? { ...run, tasks: [...run.tasks, message.task] }
          : run,
      );
      break;
    case "task.started":
      patchTask(client, message.run_id, message.task_id, (t) => ({ ...t, status: "running" }));
      break;
    case "task.progress":
      patchTask(client, message.run_id, message.task_id, (t) => ({
        ...t,
        done: message.done,
        total: message.total,
      }));
      break;
    case "task.entity":
    case "entity.merged":
      patchTask(client, message.run_id, message.task_id, (t) => ({ ...t, count: t.count + 1 }));
      refreshFindings();
      break;
    case "task.completed":
    case "task.failed":
      patchTask(client, message.run_id, message.task.id, () => message.task);
      break;
    case "stream.lagged":
      void client.invalidateQueries();
      break;
  }
}

/** Keep the investigation's queries live while the page is open. */
export function useInvestigationStream(investigationId: string): StreamState {
  const client = useQueryClient();
  const [state, setState] = useState<StreamState>("connecting");

  useEffect(() => {
    let socket: WebSocket | null = null;
    let retry: number | undefined;
    let refresh: number | undefined;
    let attempts = 0;
    let stopped = false;

    const refreshFindings = () => {
      if (refresh !== undefined) return;
      refresh = window.setTimeout(() => {
        refresh = undefined;
        void client.invalidateQueries({ queryKey: keys.entities(investigationId) });
        void client.invalidateQueries({ queryKey: keys.graph(investigationId) });
      }, 400);
    };

    const connect = () => {
      setState("connecting");
      socket = new WebSocket(streamUrl(investigationId));
      socket.addEventListener("open", () => {
        attempts = 0;
        setState("open");
        // Catch up on anything that happened while we were away.
        void client.invalidateQueries({ queryKey: keys.investigation(investigationId) });
        refreshFindings();
      });
      socket.addEventListener("message", (event) => {
        try {
          applyMessage(client, investigationId, JSON.parse(event.data) as Message, refreshFindings);
        } catch {
          // ignore malformed messages
        }
      });
      socket.addEventListener("close", () => {
        setState("closed");
        if (stopped) return;
        attempts += 1;
        retry = window.setTimeout(connect, Math.min(15000, 500 * 2 ** attempts));
      });
    };

    connect();
    return () => {
      stopped = true;
      window.clearTimeout(retry);
      window.clearTimeout(refresh);
      socket?.close();
    };
  }, [client, investigationId]);

  return state;
}
