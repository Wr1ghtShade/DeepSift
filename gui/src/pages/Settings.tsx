import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api";
import { Choice } from "../components/Choice";
import { type Depth, type Scheme, defaultDepth, setDefaultDepth, useScheme } from "../prefs";

const DEPTHS: { value: Depth; label: string }[] = [
  { value: "0", label: "Aucun pivot" },
  { value: "1", label: "1 rebond" },
  { value: "2", label: "2 rebonds" },
  { value: "3", label: "3 rebonds" },
];

const DATABASE: Record<string, string> = { sqlite: "SQLite (fichier local)", postgresql: "PostgreSQL" };

export function SettingsPage() {
  const client = useQueryClient();
  const [scheme, setScheme] = useScheme();
  const [depth, setDepth] = useState<Depth>(defaultDepth);
  const info = useQuery({ queryKey: ["info"], queryFn: api.info });

  const logout = async () => {
    try {
      await api.logout();
    } finally {
      client.clear();
      client.setQueryData(["session"], { authenticated: false });
    }
  };

  return (
    <>
      <header className="page-head">
        <div>
          <h1>Réglages</h1>
          <p className="lede">Les préférences d'affichage restent dans ce navigateur.</p>
        </div>
      </header>

      <div className="split">
        <div className="stack gap-lg">
          <section className="panel stack" aria-labelledby="h-look">
            <h2 id="h-look">Apparence</h2>
            <Choice
              legend="Thème"
              value={scheme}
              onChange={(next: Scheme) => setScheme(next)}
              options={[
                { value: "dark" as Scheme, label: "Graphite" },
                { value: "light" as Scheme, label: "Clair (papier technique)" },
              ]}
            />
          </section>

          <section className="panel stack" aria-labelledby="h-search">
            <h2 id="h-search">Recherche</h2>
            <Choice
              legend="Pivots automatiques par défaut"
              value={depth}
              onChange={(next) => {
                setDepth(next);
                setDefaultDepth(next);
              }}
              options={DEPTHS}
            />
            <p className="muted small-text">
              Chaque rebond relance les services sur ce qui vient d'être trouvé. Trois rebonds
              peuvent lancer des centaines de tâches et solliciter beaucoup de sites.
            </p>
          </section>
        </div>

        <div className="stack gap-lg">
          <section className="panel stack" aria-labelledby="h-gateway">
            <h2 id="h-gateway">Gateway</h2>
            {info.data ? (
              <dl className="facts">
                <dt>Version</dt>
                <dd className="mono">
                  {info.data.version} (contrat v{info.data.contract})
                </dd>
                <dt>Exécution</dt>
                <dd>
                  {info.data.executor === "redis"
                    ? "Workers Docker, via Redis"
                    : "Dans la gateway (mode local)"}
                </dd>
                <dt>Base de données</dt>
                <dd>{DATABASE[info.data.database] ?? info.data.database}</dd>
                <dt>Services</dt>
                <dd>
                  {info.data.services_online} en ligne sur {info.data.services}
                </dd>
                <dt>Enquêtes</dt>
                <dd>{info.data.investigations}</dd>
              </dl>
            ) : info.isError ? (
              <p className="notice danger" role="alert">
                La gateway ne répond pas : {info.error.message}
              </p>
            ) : (
              <div className="spinner" role="status" aria-label="Chargement" />
            )}
          </section>

          <section className="panel stack" aria-labelledby="h-session">
            <h2 id="h-session">Session</h2>
            <p className="muted small-text">
              {info.data
                ? `Une session dure ${Math.round(info.data.session_ttl / 3600)} h. `
                : ""}
              Pour changer le jeton d'API, remplacez <span className="mono">DEEPSIFT_API_TOKEN</span>{" "}
              (ou supprimez le fichier <span className="mono">api-token</span>) puis redémarrez la
              gateway.
            </p>
            <div className="actions">
              <button type="button" className="button danger" onClick={logout}>
                Se déconnecter
              </button>
            </div>
          </section>
        </div>
      </div>
    </>
  );
}
