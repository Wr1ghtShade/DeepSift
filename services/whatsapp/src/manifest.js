import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import yaml from "js-yaml";

const HERE = dirname(fileURLToPath(import.meta.url));

export const MANIFEST_PATH = join(HERE, "..", "manifest.yaml");

export const manifest = yaml.load(readFileSync(MANIFEST_PATH, "utf8"));

/** The task's value for an option, else the manifest default. */
export function option(task, name) {
  if (task.options && Object.hasOwn(task.options, name)) return task.options[name];
  return manifest.options?.[name]?.default;
}

/** Where linked-session files and limiter state live. */
export function dataDir(env = process.env) {
  const base =
    env.DEEPSIFT_DATA_DIR || join(env.HOME || "/tmp", ".local", "share", "deepsift");
  return join(base, "whatsapp");
}
