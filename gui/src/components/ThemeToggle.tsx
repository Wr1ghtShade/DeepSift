import { useScheme } from "../prefs";

export function ThemeToggle() {
  const [scheme, setScheme] = useScheme();
  return (
    <button
      type="button"
      className="button"
      onClick={() => setScheme(scheme === "dark" ? "light" : "dark")}
    >
      {scheme === "dark" ? "Thème clair" : "Thème graphite"}
    </button>
  );
}
