// Client for the gateway API (contract section 7). The browser authenticates with the
// HttpOnly session cookie, so no credential ever lives in JavaScript.

export type EntityType =
  | "username"
  | "email"
  | "phone"
  | "domain"
  | "url"
  | "image"
  | "profile"
  | "account"
  | "identity"
  | "web_page"
  | "phone_meta"
  | "mx_record"
  | "image_hash"
  | "avatar_group";

export type Level = "high" | "medium" | "low";

export interface Source {
  service: string;
  confidence: number;
}

export interface Entity {
  id: string;
  type: EntityType;
  value: string;
  attributes: Record<string, unknown>;
  score: number;
  level: Level;
  selector: boolean;
  avatar_group: string | null;
  first_seen: string;
  sources: Source[];
}

export interface EntityLink {
  direction: "in" | "out";
  rel: string;
  entity: { id: string; type: EntityType; value: string } | null;
}

export interface EntityDetail extends Entity {
  investigation_id: string;
  links: EntityLink[];
  pivots: { service: string; enabled: boolean; state: ServiceState }[];
}

export type TaskStatus = "queued" | "running" | "completed" | "failed" | "cancelled";

export interface Task {
  id: string;
  run_id: string;
  service: string;
  entity_id: string;
  depth: number;
  status: TaskStatus;
  done: number | null;
  total: number | null;
  count: number;
  error: { code: string; message: string; retryable: boolean } | null;
}

export type RunStatus = "running" | "completed" | "cancelled" | "interrupted";

export interface Run {
  id: string;
  investigation_id: string;
  selector: string;
  type: EntityType;
  entity_id: string;
  services: string[];
  max_depth: number;
  status: RunStatus;
  created_at: string;
  finished_at: string | null;
}

export interface RunDetail extends Run {
  tasks: Task[];
}

export interface InvestigationSummary {
  id: string;
  name: string;
  created_at: string;
  entities: number;
}

export interface Investigation {
  id: string;
  name: string;
  created_at: string;
  runs: Run[];
}

export interface Graph {
  nodes: Entity[];
  edges: { source: string; rel: string; target: string }[];
  avatar_groups: { name: string; profiles: string[] }[];
}

export type ServiceState = "ready" | "busy" | "needs_config" | "offline";

export interface OptionSpec {
  type: "enum" | "int" | "bool" | "str";
  values: unknown[] | null;
  default: unknown;
  description: string;
}

export interface ServiceInfo {
  name: string;
  version: string;
  description: string;
  inputs: EntityType[];
  outputs: EntityType[];
  license: string;
  rate_limit: string | null;
  enabled: boolean;
  enabled_by_default: boolean;
  state: ServiceState;
  missing: string[];
  options: Record<string, OptionSpec>;
  instances: { id: string; state: string; running: number }[];
}

export interface StartRun {
  selector: string;
  type?: EntityType;
  services?: string[];
  auto_pivot?: boolean;
  max_depth?: number;
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** Fired when the session expires so the app can show the login screen. */
export const UNAUTHORIZED_EVENT = "deepsift:unauthorized";

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body !== undefined && !(init.body instanceof Blob) && !headers.has("content-type")) {
    headers.set("content-type", "application/json");
  }
  const response = await fetch(`/api/v1${path}`, {
    ...init,
    headers,
    credentials: "same-origin",
  });
  if (response.status === 401 && path !== "/session") {
    window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
  }
  if (!response.ok) {
    let message = response.statusText || `HTTP ${response.status}`;
    try {
      const body = await response.json();
      if (typeof body.detail === "string") message = body.detail;
      else if (Array.isArray(body.detail) && body.detail[0]?.msg) message = body.detail[0].msg;
    } catch {
      // not JSON
    }
    throw new ApiError(response.status, message);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

const json = (body: unknown) => JSON.stringify(body);

export const api = {
  session: () => request<{ authenticated: boolean }>("/session"),
  login: (token: string) => request<void>("/session", { method: "POST", body: json({ token }) }),
  logout: () => request<void>("/session", { method: "DELETE" }),

  investigations: () => request<InvestigationSummary[]>("/investigations"),
  investigation: (id: string) => request<Investigation>(`/investigations/${id}`),
  createInvestigation: (name: string) =>
    request<InvestigationSummary>("/investigations", { method: "POST", body: json({ name }) }),
  deleteInvestigation: (id: string) => request<void>(`/investigations/${id}`, { method: "DELETE" }),

  startRun: (investigationId: string, body: StartRun) =>
    request<Run>(`/investigations/${investigationId}/runs`, { method: "POST", body: json(body) }),
  run: (id: string) => request<RunDetail>(`/runs/${id}`),
  cancelRun: (id: string) => request<{ id: string }>(`/runs/${id}/cancel`, { method: "POST" }),

  entities: (investigationId: string) =>
    request<Entity[]>(`/investigations/${investigationId}/entities?limit=5000`),
  graph: (investigationId: string) => request<Graph>(`/investigations/${investigationId}/graph`),
  entity: (id: string) => request<EntityDetail>(`/entities/${id}`),
  pivot: (id: string, services?: string[]) =>
    request<Run>(`/entities/${id}/pivot`, { method: "POST", body: json({ services }) }),

  services: () => request<ServiceInfo[]>("/services"),
  setServiceEnabled: (name: string, enabled: boolean) =>
    request<{ name: string; enabled: boolean }>(`/services/${name}`, {
      method: "PATCH",
      body: json({ enabled }),
    }),

  uploadImage: (file: Blob) =>
    request<{ sha256: string; selector: string; mime: string }>("/blobs", {
      method: "POST",
      body: file,
      headers: { "content-type": file.type || "application/octet-stream" },
    }),
};

export const exportUrl = (investigationId: string, format: "json" | "csv" | "html") =>
  `/api/v1/investigations/${investigationId}/export?format=${format}`;

export const blobUrl = (value: string) =>
  value.startsWith("blob:") ? `/api/v1/blobs/${value.slice(5)}` : null;

export const streamUrl = (investigationId: string) => {
  const scheme = location.protocol === "https:" ? "wss:" : "ws:";
  return `${scheme}//${location.host}/api/v1/investigations/${investigationId}/stream`;
};
