// Per-browser preferences. They live in localStorage, which can be blocked or
// cleared: every read has a default and every write may silently fail.
import { useEffect, useState } from "react";

export type Scheme = "dark" | "light";
const SCHEME_KEY = "color-scheme";
const DEPTH_KEY = "deepsift:default-depth";

function read(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function write(key: string, value: string | null): void {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch {
    // storage blocked: the choice still applies to this page
  }
}

function meta(): HTMLMetaElement | null {
  return document.querySelector('meta[name="color-scheme"]');
}

function currentScheme(): Scheme {
  return meta()?.content === "light" ? "light" : "dark";
}

/** Graphite (dark) is the default; the light theme is stored as an override. The
 * <meta name="color-scheme"> drives the CSS; index.html applies it before paint. */
export function useScheme(): [Scheme, (scheme: Scheme) => void] {
  const [scheme, setScheme] = useState<Scheme>(currentScheme);

  useEffect(() => {
    const sync = () => setScheme(currentScheme());
    const onStorage = (event: StorageEvent) => {
      if (event.key !== SCHEME_KEY) return;
      const element = meta();
      if (element) element.content = event.newValue === "light" ? "light" : "dark";
      sync();
    };
    // Other components (the sidebar button, the settings page) change it too.
    const observer = new MutationObserver(sync);
    const element = meta();
    if (element) observer.observe(element, { attributes: true, attributeFilter: ["content"] });
    window.addEventListener("storage", onStorage);
    return () => {
      observer.disconnect();
      window.removeEventListener("storage", onStorage);
    };
  }, []);

  const change = (next: Scheme) => {
    const element = meta();
    if (element) element.content = next;
    write(SCHEME_KEY, next === "dark" ? null : next);
    setScheme(next);
  };
  return [scheme, change];
}

export type Depth = "0" | "1" | "2" | "3";

export function defaultDepth(): Depth {
  const value = read(DEPTH_KEY);
  return value === "0" || value === "2" || value === "3" ? value : "1";
}

export function setDefaultDepth(depth: Depth): void {
  write(DEPTH_KEY, depth === "1" ? null : depth);
}
