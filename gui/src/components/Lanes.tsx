// "Le tamis": one lane per service in a run, filled as its tasks report progress.
import type { Task } from "../api";
import { ERROR_LABEL } from "../labels";

export interface Lane {
  service: string;
  tasks: number;
  finished: number;
  failed: number;
  running: number;
  hits: number;
  done: number | null;
  total: number | null;
  error: string | null;
}

export function lanesOf(tasks: Task[]): Lane[] {
  const lanes = new Map<string, Lane>();
  for (const task of tasks) {
    const lane = lanes.get(task.service) ?? {
      service: task.service,
      tasks: 0,
      finished: 0,
      failed: 0,
      running: 0,
      hits: 0,
      done: null,
      total: null,
      error: null,
    };
    lane.tasks += 1;
    lane.hits += task.count;
    if (task.status === "completed" || task.status === "cancelled") lane.finished += 1;
    if (task.status === "failed") {
      lane.finished += 1;
      lane.failed += 1;
      lane.error = task.error ? (ERROR_LABEL[task.error.code] ?? task.error.code) : null;
    }
    if (task.status === "running") lane.running += 1;
    // A single task with its own progress drives the bar precisely.
    lane.done = lane.tasks === 1 ? task.done : null;
    lane.total = lane.tasks === 1 ? task.total : null;
    lanes.set(task.service, lane);
  }
  return [...lanes.values()];
}

function laneStatus(lane: Lane): { label: string; tone: string } {
  if (lane.finished < lane.tasks) {
    return lane.running > 0
      ? { label: "En cours", tone: "running" }
      : { label: "En attente", tone: "queued" };
  }
  if (lane.failed === lane.tasks) return { label: lane.error ?? "Échec", tone: "failed" };
  if (lane.failed > 0) return { label: `Terminé, ${lane.failed} en échec`, tone: "needs_config" };
  return { label: "Terminé", tone: "completed" };
}

function LaneRow({ lane }: { lane: Lane }) {
  const status = laneStatus(lane);
  const finished = lane.finished === lane.tasks;
  let value: number | undefined;
  let max = 1;
  if (finished) value = 1;
  else if (lane.done !== null && lane.total) {
    value = lane.done;
    max = lane.total;
  } else if (lane.tasks > 1) {
    value = lane.finished;
    max = lane.tasks;
  }
  // value undefined: an indeterminate bar while the service has not said how far it is.
  const tone = finished ? (lane.failed === lane.tasks ? "failed" : "done") : "";
  return (
    <div className="lane">
      <div className="name">
        <strong>{lane.service}</strong>
        <span className={`badge ${status.tone}`}>{status.label}</span>
      </div>
      <progress
        className={tone}
        aria-label={`Progression de ${lane.service}`}
        max={max}
        value={value}
      />
      <span className="hits">
        <strong>{lane.hits}</strong> trouvé{lane.hits > 1 ? "s" : ""}
      </span>
      <span className="muted">
        {lane.tasks > 1 ? `${lane.finished}/${lane.tasks} tâches` : finished ? "" : "…"}
      </span>
    </div>
  );
}

export function Lanes({ tasks }: { tasks: Task[] }) {
  const lanes = lanesOf(tasks);
  if (lanes.length === 0) return <p className="muted">Aucun service n'a tourné pour ce run.</p>;
  return (
    <div className="lanes">
      {lanes.map((lane) => (
        <LaneRow key={lane.service} lane={lane} />
      ))}
    </div>
  );
}
