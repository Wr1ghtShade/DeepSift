import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Suspense, lazy, useEffect, useId, useState } from "react";
import { Link, useParams } from "wouter";
import { type Run, api, exportUrl } from "../api";
import { EntityTable } from "../components/EntityTable";
import { Lanes, lanesOf } from "../components/Lanes";
import { RUN_STATUS_LABEL, TYPE_LABEL, formatDate } from "../labels";
import { keys, useInvestigationStream } from "../stream";

const Graph = lazy(() => import("../components/Graph"));

function runLabel(run: Run, index: number, total: number): string {
  const kind = TYPE_LABEL[run.type].toLowerCase();
  return `${total - index}. ${run.selector} (${kind}, ${formatDate(run.created_at)})`;
}

function ExportMenu({ investigationId }: { investigationId: string }) {
  const id = useId();
  return (
    <>
      <button type="button" className="button" popoverTarget={id}>
        Exporter le rapport
      </button>
      <div id={id} popover="auto" className="menu anchored">
        <a href={exportUrl(investigationId, "html")} download>
          Rapport HTML
        </a>
        <a href={exportUrl(investigationId, "csv")} download>
          Tableau CSV
        </a>
        <a href={exportUrl(investigationId, "json")} download>
          Données JSON
        </a>
      </div>
    </>
  );
}

export function ResultsPage() {
  const { id } = useParams<{ id: string }>();
  const client = useQueryClient();
  const stream = useInvestigationStream(id);
  const investigation = useQuery({
    queryKey: keys.investigation(id),
    queryFn: () => api.investigation(id),
  });
  const runs = investigation.data?.runs ?? [];
  const [runId, setRunId] = useState<string | null>(null);
  const currentId = runId ?? runs[0]?.id ?? null;
  // A new run (started from a pivot) becomes the one on screen.
  const newest = runs[0]?.id;
  useEffect(() => setRunId(null), [newest]);

  const run = useQuery({
    queryKey: keys.run(currentId ?? "none"),
    queryFn: () => api.run(currentId!),
    enabled: currentId !== null,
  });
  const entities = useQuery({ queryKey: keys.entities(id), queryFn: () => api.entities(id) });
  const graph = useQuery({ queryKey: keys.graph(id), queryFn: () => api.graph(id) });
  const cancel = useMutation({
    mutationFn: (runToStop: string) => api.cancelRun(runToStop),
    onSettled: () => client.invalidateQueries({ queryKey: keys.investigation(id) }),
  });

  if (investigation.isPending) return <div className="spinner" role="status" aria-label="Chargement" />;
  if (investigation.isError) {
    return (
      <div className="empty">
        <p>Ce dossier est introuvable.</p>
        <Link href="/investigations" className="button">
          Retour aux enquêtes
        </Link>
      </div>
    );
  }

  const current = run.data;
  const lanes = lanesOf(current?.tasks ?? []);
  const finished = lanes.filter((l) => l.finished === l.tasks).length;
  const running = current?.status === "running";
  const first = runs[runs.length - 1];
  const summary = current
    ? running
      ? `${TYPE_LABEL[current.type]} : ${finished} service${finished > 1 ? "s" : ""} terminé${finished > 1 ? "s" : ""} sur ${lanes.length}`
      : `${TYPE_LABEL[current.type]} : recherche ${RUN_STATUS_LABEL[current.status].toLowerCase()}`
    : "Aucun run";

  return (
    <>
      <header className="page-head">
        <div>
          <p className="eyebrow">{investigation.data.name}</p>
          <h1 className="mono wrap-anywhere">{first?.selector ?? investigation.data.name}</h1>
          <p className="lede" role="status">
            {summary}
            {stream === "closed" && " (connexion en direct perdue, nouvelle tentative…)"}
          </p>
        </div>
        <div className="actions">
          {running && current && (
            <button
              type="button"
              className="button danger"
              onClick={() => cancel.mutate(current.id)}
              disabled={cancel.isPending}
            >
              Arrêter
            </button>
          )}
          <ExportMenu investigationId={id} />
        </div>
      </header>

      <section className="stack" aria-labelledby="h-sieve">
        <div className="row-between">
          <h2 id="h-sieve">Le tamis</h2>
          {runs.length > 1 && (
            <div className="field inline-field">
              <label htmlFor="run">Run</label>
              <select
                id="run"
                className="input"
                value={currentId ?? ""}
                onChange={(e) => setRunId(e.target.value)}
              >
                {runs.map((r, index) => (
                  <option key={r.id} value={r.id}>
                    {runLabel(r, index, runs.length)}
                  </option>
                ))}
              </select>
            </div>
          )}
        </div>
        {run.isPending ? (
          <div className="spinner" role="status" aria-label="Chargement du run" />
        ) : (
          <Lanes tasks={current?.tasks ?? []} />
        )}
      </section>

      <div className="split-main">
        <section aria-labelledby="h-findings">
          {entities.data ? (
            <EntityTable entities={entities.data} />
          ) : (
            <div className="spinner" role="status" aria-label="Chargement des résultats" />
          )}
        </section>
        <aside className="stack" aria-labelledby="h-graph">
          <h2 id="h-graph">Graphe des pivots</h2>
          {graph.data && graph.data.nodes.length > 1 ? (
            <Suspense fallback={<div className="graph" aria-busy="true" />}>
              <Graph data={graph.data} />
            </Suspense>
          ) : (
            <p className="empty">Le graphe se dessine dès les premiers résultats.</p>
          )}
          <div className="legend" aria-label="Légende">
            <span>
              <i className="dot-selector" /> Sélecteur
            </span>
            <span>
              <i className="dot-profile" /> Profil
            </span>
            <span>
              <i className="dot-pivot" /> Nouveau sélecteur
            </span>
            <span>
              <i className="dot-group" /> Même avatar
            </span>
          </div>
        </aside>
      </div>
    </>
  );
}
