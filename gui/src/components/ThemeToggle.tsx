// Graphite (dark) is the default; "clair" is the light alternative. The choice is
// reflected in <meta name="color-scheme">, which the CSS maps to color-scheme, so
// every light-dark() token follows. index.html applies the stored value before paint.
import { useEffect, useState } from "react";

type Scheme = "dark" | "light";
const KEY = "color-scheme";

function meta(): HTMLMetaElement | null {
  return document.querySelector('meta[name="color-scheme"]');
}

function current(): Scheme {
  return meta()?.content === "light" ? "light" : "dark";
}

function apply(scheme: Scheme): void {
  const element = meta();
  if (element) element.content = scheme;
}

export function ThemeToggle() {
  const [scheme, setScheme] = useState<Scheme>(current);

  useEffect(() => {
    // Another tab changed the theme.
    const onStorage = (event: StorageEvent) => {
      if (event.key !== KEY) return;
      const next: Scheme = event.newValue === "light" ? "light" : "dark";
      apply(next);
      setScheme(next);
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  const toggle = () => {
    const next: Scheme = scheme === "dark" ? "light" : "dark";
    apply(next);
    setScheme(next);
    try {
      if (next === "dark") localStorage.removeItem(KEY);
      else localStorage.setItem(KEY, next);
    } catch {
      // storage blocked: the theme still applies for this page
    }
  };

  return (
    <button type="button" className="button" onClick={toggle}>
      {scheme === "dark" ? "Thème clair" : "Thème graphite"}
    </button>
  );
}
