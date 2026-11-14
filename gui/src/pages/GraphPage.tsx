import { useQuery } from "@tanstack/react-query";
import { Suspense, lazy, useState } from "react";
import { Link, useParams } from "wouter";
import { api } from "../api";
import { Choice } from "../components/Choice";
import type { GraphLayout } from "../components/Graph";
import { GraphLegend } from "../components/GraphLegend";
import { LEVEL_LABEL, TYPE_LABEL, percent, shortValue } from "../labels";
import { keys, useInvestigationStream } from "../stream";

const Graph = lazy(() => import("../components/Graph"));

const LAYOUTS: { value: GraphLayout; label: string }[] = [
  { value: "cose", label: "Organique" },
  { value: "concentric", label: "Par confiance" },
  { value: "breadthfirst", label: "Arbre des pivots" },
  { value: "circle", label: "Cercle" },
];

function Selected({ id }: { id: string }) {
  const entity = useQuery({ queryKey: ["entity", id], queryFn: () => api.entity(id) });
  if (!entity.data) return <div className="spinner" role="status" aria-label="Chargement" />;
  const e = entity.data;
  return (
    <div className="stack">
      <p className="eyebrow muted">{TYPE_LABEL[e.type]}</p>
      <h2 className="wrap-anywhere">{shortValue(e.type, e.value)}</h2>
      <p className="mono small-text wrap-anywhere">{e.value}</p>
      <div className="chips">
        {!e.selector && (
          <span className={`badge ${e.level}`}>
            {LEVEL_LABEL[e.level]} ({percent(e.score)})
          </span>
        )}
        {e.avatar_group && <span className="badge group">Avatar {e.avatar_group}</span>}
      </div>
      {e.sources.length > 0 && (
        <p className="muted small-text">Trouvé par {e.sources.map((s) => s.service).join(", ")}</p>
      )}
      <p className="muted small-text">
        {e.links.length} lien{e.links.length > 1 ? "s" : ""}
      </p>
      <Link href={`/entities/${e.id}`} className="button primary">
        Ouvrir la fiche et les pivots
      </Link>
    </div>
  );
}

export function GraphPage() {
  const { id } = useParams<{ id: string }>();
  useInvestigationStream(id);
  const investigation = useQuery({
    queryKey: keys.investigation(id),
    queryFn: () => api.investigation(id),
  });
  const graph = useQuery({ queryKey: keys.graph(id), queryFn: () => api.graph(id) });
  const [layout, setLayout] = useState<GraphLayout>("cose");
  const [query, setQuery] = useState("");
  const [fitKey, setFitKey] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);

  const nodes = graph.data?.nodes.length ?? 0;
  const edges = graph.data?.edges.length ?? 0;

  return (
    <>
      <Link href={`/investigations/${id}`} className="back-link">
        ← Retour aux résultats
      </Link>
      <header className="page-head compact">
        <div>
          <p className="eyebrow">{investigation.data?.name ?? ""}</p>
          <h1>Graphe des pivots</h1>
          <p className="lede">
            {nodes} entités, {edges} liens. Cliquez sur un nœud pour le détail ; la molette
            zoome.
          </p>
        </div>
      </header>

      <div className="graph-toolbar">
        <div className="field inline-field">
          <label htmlFor="graph-search">Rechercher</label>
          <input
            id="graph-search"
            type="search"
            className="input"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="github, @gmail…"
          />
        </div>
        <Choice
          legend="Disposition"
          hideLegend
          variant="segmented"
          value={layout}
          onChange={setLayout}
          options={LAYOUTS}
        />
        <button type="button" className="button small" onClick={() => setFitKey((k) => k + 1)}>
          Recentrer
        </button>
        <GraphLegend />
      </div>

      <div className="graph-layout">
        {graph.data && nodes > 1 ? (
          <Suspense fallback={<div className="graph graph-full" aria-busy="true" />}>
            <div className="stack">
              <Graph
                data={graph.data}
                full
                layout={layout}
                query={query}
                fitKey={fitKey}
                onSelect={setSelected}
              />
            </div>
          </Suspense>
        ) : graph.isPending ? (
          <div className="graph graph-full" aria-busy="true" />
        ) : (
          <p className="empty">Le graphe se dessine dès les premiers résultats.</p>
        )}
        <aside className="panel graph-side" aria-label="Entité sélectionnée">
          {selected ? (
            <Selected id={selected} />
          ) : (
            <p className="muted">Cliquez sur un nœud pour afficher son détail ici.</p>
          )}
        </aside>
      </div>
    </>
  );
}
