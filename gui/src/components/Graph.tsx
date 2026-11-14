// Pivot graph (Cytoscape.js), loaded on demand. Colours come from the theme tokens and
// follow theme changes. The findings table is the accessible equivalent.
import cytoscape, { type Core, type ElementDefinition } from "cytoscape";
import { useEffect, useMemo, useRef } from "react";
import { useLocation } from "wouter";
import type { Graph as GraphData } from "../api";
import { shortValue } from "../labels";

export const MAX_NODES = 250;

// Cytoscape injects an inline <style> unless an element with this id exists. The strict
// CSP blocks inline styles, and .graph already sets what it would (position: relative).
const CYTOSCAPE_STYLE_ID = "__________cytoscape_stylesheet";

function claimStylesheetSlot(): void {
  if (document.getElementById(CYTOSCAPE_STYLE_ID)) return;
  const marker = document.createElement("meta");
  marker.id = CYTOSCAPE_STYLE_ID;
  document.head.append(marker);
}

function token(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function elements(data: GraphData): { items: ElementDefinition[]; hidden: number } {
  const ranked = [...data.nodes].sort(
    (a, b) => Number(b.selector) - Number(a.selector) || b.score - a.score,
  );
  const kept = ranked.slice(0, MAX_NODES);
  const ids = new Set(kept.map((n) => n.id));
  const items: ElementDefinition[] = kept.map((node) => ({
    data: {
      id: node.id,
      label: shortValue(node.type, node.value).slice(0, 28),
      kind: node.selector ? "selector" : node.type,
      grouped: node.avatar_group ? "yes" : "no",
    },
  }));
  for (const edge of data.edges) {
    if (ids.has(edge.source) && ids.has(edge.target)) {
      items.push({
        data: { id: `${edge.source}-${edge.rel}-${edge.target}`, ...edge, kind: "link" },
      });
    }
  }
  // Profiles sharing an avatar are tied together, as in the mockup's "Même avatar".
  for (const group of data.avatar_groups) {
    const members = group.profiles.filter((p) => ids.has(p));
    for (let i = 1; i < members.length; i++) {
      items.push({
        data: {
          id: `group-${group.name}-${i}`,
          source: members[0],
          target: members[i],
          kind: "same-avatar",
        },
      });
    }
  }
  return { items, hidden: Math.max(0, data.nodes.length - kept.length) };
}

function style(): cytoscape.StylesheetJson {
  const text = token("--text-2");
  return [
    {
      selector: "node",
      style: {
        "background-color": token("--done-fill"),
        label: "data(label)",
        color: text,
        "font-family": "Schibsted Grotesk, system-ui, sans-serif",
        "font-size": 10,
        "text-valign": "bottom",
        "text-margin-y": 4,
        width: 18,
        height: 18,
      },
    },
    {
      selector: 'node[kind = "selector"]',
      style: {
        "background-color": token("--accent"),
        width: 34,
        height: 34,
        "font-size": 12,
        "font-weight": 600,
        color: token("--text"),
      },
    },
    {
      selector: 'node[kind = "profile"]',
      style: { "background-color": token("--signal"), width: 22, height: 22 },
    },
    { selector: 'node[grouped = "yes"]', style: { "border-width": 3, "border-color": token("--ok") } },
    {
      selector: 'node[kind = "email"], node[kind = "phone"], node[kind = "domain"], node[kind = "username"]',
      style: { "background-color": token("--warn"), shape: "round-rectangle" },
    },
    {
      selector: "edge",
      style: {
        width: 1.2,
        "line-color": token("--line-strong"),
        "curve-style": "bezier",
        "target-arrow-shape": "triangle",
        "target-arrow-color": token("--line-strong"),
        "arrow-scale": 0.7,
      },
    },
    {
      selector: 'edge[kind = "same-avatar"]',
      style: {
        "line-color": token("--ok"),
        "line-style": "dashed",
        width: 2,
        "target-arrow-shape": "none",
      },
    },
    { selector: "node:selected", style: { "border-width": 3, "border-color": token("--accent") } },
  ];
}

export default function Graph({ data }: { data: GraphData }) {
  const container = useRef<HTMLDivElement>(null);
  const cy = useRef<Core | null>(null);
  const layout = useRef<cytoscape.Layouts | null>(null);
  const [, navigate] = useLocation();
  const { items, hidden } = useMemo(() => elements(data), [data]);

  // One Cytoscape instance per mount; live updates only add and remove elements.
  useEffect(() => {
    if (!container.current) return;
    claimStylesheetSlot();
    const instance = cytoscape({
      container: container.current,
      style: style(),
      wheelSensitivity: 0.3,
      minZoom: 0.2,
      maxZoom: 3,
    });
    instance.on("tap", "node", (event) => navigate(`/entities/${event.target.id()}`));
    cy.current = instance;

    // Re-colour when the theme changes.
    const meta = document.querySelector('meta[name="color-scheme"]');
    const observer = new MutationObserver(() => instance.style(style()));
    if (meta) observer.observe(meta, { attributes: true, attributeFilter: ["content"] });
    return () => {
      observer.disconnect();
      layout.current?.stop();
      layout.current = null;
      cy.current = null;
      instance.destroy();
    };
  }, [navigate]);

  useEffect(() => {
    const instance = cy.current;
    if (!instance) return;
    const wanted = new Set(items.map((item) => String(item.data.id)));
    const stale = instance.elements().filter((el) => !wanted.has(el.id()));
    const fresh = items.filter((item) => instance.getElementById(String(item.data.id)).empty());
    if (stale.empty() && fresh.length === 0) return;
    instance.batch(() => {
      stale.remove();
      // Nodes first so new edges find their ends.
      instance.add(fresh.filter((item) => !("source" in item.data)));
      instance.add(fresh.filter((item) => "source" in item.data));
    });
    layout.current?.stop();
    // Computed in one go: an animated cose layout keeps ticking on timers, and a tick
    // that lands after the page is left hits a destroyed instance.
    layout.current = instance.layout({
      name: "cose",
      animate: false,
      padding: 24,
      nodeRepulsion: () => 9000,
    });
    layout.current.run();
  }, [items]);

  const nodes = items.filter((i) => !("source" in i.data)).length;
  return (
    <>
      <div
        ref={container}
        className="graph"
        role="img"
        aria-label={`Graphe des pivots : ${nodes} entités. Le tableau des résultats donne le même contenu.`}
      />
      {hidden > 0 && (
        <p className="muted small-text">
          Les {MAX_NODES} entités les plus sûres sont affichées ; {hidden} autres sont dans le tableau.
        </p>
      )}
    </>
  );
}
