// French interface copy, in one place.
import type { EntityType, Level, RunStatus, ServiceState, TaskStatus } from "./api";

export const TYPE_LABEL: Record<EntityType, string> = {
  username: "Pseudo",
  email: "E-mail",
  phone: "Téléphone",
  domain: "Domaine",
  url: "URL",
  image: "Image",
  profile: "Profil",
  account: "Compte",
  identity: "Identité",
  web_page: "Page web",
  phone_meta: "Infos du numéro",
  mx_record: "Serveur de mail",
  image_hash: "Empreinte d'image",
  avatar_group: "Groupe d'avatars",
};

/** Types a person can type in as a selector, in the order of the mockup. */
export const SELECTOR_TYPES: EntityType[] = ["username", "email", "phone", "domain", "image"];

export const LEVEL_LABEL: Record<Level, string> = {
  high: "Élevée",
  medium: "Moyenne",
  low: "Faible",
};

export const SERVICE_STATE_LABEL: Record<ServiceState, string> = {
  ready: "En ligne",
  busy: "Occupé",
  needs_config: "Configuration requise",
  offline: "Hors ligne",
};

export const TASK_STATUS_LABEL: Record<TaskStatus, string> = {
  queued: "En attente",
  running: "En cours",
  completed: "Terminé",
  failed: "Échec",
  cancelled: "Arrêté",
};

export const RUN_STATUS_LABEL: Record<RunStatus, string> = {
  running: "En cours",
  completed: "Terminée",
  cancelled: "Arrêtée",
  interrupted: "Interrompue",
};

export const ERROR_LABEL: Record<string, string> = {
  invalid_input: "Entrée refusée",
  needs_config: "Configuration manquante",
  rate_limited: "Limite de débit atteinte",
  upstream_error: "Le site a répondu en erreur",
  timeout: "Délai dépassé",
  internal: "Erreur interne",
};

const dateFormat = new Intl.DateTimeFormat("fr-FR", { dateStyle: "medium", timeStyle: "short" });
const relative = new Intl.RelativeTimeFormat("fr-FR", { numeric: "auto" });

export function formatDate(iso: string): string {
  return dateFormat.format(new Date(iso));
}

export function formatRelative(iso: string, now = Date.now()): string {
  const seconds = Math.round((new Date(iso).getTime() - now) / 1000);
  const steps: [Intl.RelativeTimeFormatUnit, number][] = [
    ["day", 86400],
    ["hour", 3600],
    ["minute", 60],
  ];
  for (const [unit, size] of steps) {
    if (Math.abs(seconds) >= size) return relative.format(Math.round(seconds / size), unit);
  }
  return "à l'instant";
}

export const percent = (score: number) => `${Math.round(score * 100)} %`;

/** Short display name for an entity value: the host for URLs, the value otherwise. */
export function shortValue(type: EntityType, value: string): string {
  if (["profile", "url", "web_page"].includes(type)) {
    try {
      const url = new URL(value);
      return url.hostname.replace(/^www\./, "");
    } catch {
      return value;
    }
  }
  if (type === "image" && value.startsWith("blob:")) return "Image importée";
  return value;
}
