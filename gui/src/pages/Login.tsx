import { useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { ApiError, api } from "../api";
import { Logo } from "../components/Logo";
import { ThemeToggle } from "../components/ThemeToggle";

export function LoginPage() {
  const client = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const token = String(new FormData(event.currentTarget).get("token") ?? "").trim();
    if (!token) return;
    setBusy(true);
    setError(null);
    try {
      await api.login(token);
      client.setQueryData(["session"], { authenticated: true });
    } catch (exc) {
      if (exc instanceof ApiError && exc.status === 429) {
        setError("Trop d'essais ratés. Réessayez dans quelques minutes.");
      } else if (exc instanceof ApiError && exc.status === 401) {
        setError("Ce jeton n'est pas le bon. Vérifiez le fichier api-token de la gateway.");
      } else {
        setError("La gateway ne répond pas. Vérifiez qu'elle tourne.");
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="login">
      <form className="panel" onSubmit={submit} aria-describedby={error ? "login-error" : undefined}>
        <div className="brand">
          <Logo size={36} />
          <span>DeepSift</span>
        </div>
        <h1>Connexion</h1>
        <p className="muted">
          Collez le jeton d'API de votre gateway. Il se trouve dans <span className="mono">api-token</span>{" "}
          (dossier de données) ou dans <span className="mono">secrets/api_token.txt</span> avec Docker.
        </p>
        <div className="field">
          <label htmlFor="token">Jeton d'API</label>
          <input
            id="token"
            name="token"
            type="password"
            className="input mono"
            required
            autoComplete="current-password"
            autoFocus
            spellCheck={false}
          />
        </div>
        {error && (
          <p id="login-error" className="notice danger" role="alert">
            {error}
          </p>
        )}
        <button type="submit" className="button primary big" disabled={busy}>
          {busy ? "Connexion…" : "Se connecter"}
        </button>
        <ThemeToggle />
      </form>
    </main>
  );
}
