// Pivot graph (Cytoscape.js), loaded on demand. Colours come from the theme tokens and
// follow theme changes. The findings table is the accessible equivalent.
import cytoscape, { type Core, type ElementDefinition } from "cytoscape";
import { useEffect, useMemo, useRef } from "react";
import { useLocation } from "wouter";
import type { Graph as GraphData } from "../api";
import { shortValue } from "../labels";

export const PREVIEW_NODES = 250;
export const FULL_NODES = 1500;

export type GraphLayout = "cose" | "concentric" | "breadthfirst" | "circle";

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

export function elements(
  data: GraphData,
  maxNodes: number,
): { items: ElementDefinition[]; hidden: number } {
  const ranked = [...data.nodes].sort(
    (a, b) => Number(b.selector) - Number(a.selector) || b.score - a.score,
  );
  const kept = ranked.slice(0, maxNodes);
  const ids = new Set(kept.map((n) => n.id));
  const items: ElementDefinition[] = kept.map((node) => ({
    data: {
      id: node.id,
      label: shortValue(node.type, node.value).slice(0, 32),
      search: `${node.value} ${shortValue(node.type, node.value)}`.toLowerCase(),
      kind: node.selector ? "selector" : node.type,
      grouped: node.avatar_group ? "yes" : "no",
      weight: node.selector ? 1 : node.score,
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

function style(full: boolean): cytoscape.StylesheetJson {
  const scale = full ? 1.4 : 1;
  return [
    {
      selector: "node",
      style: {
        "background-color": token("--done-fill"),
        label: "data(label)",
        color: token("--text-2"),
        "font-family": "Schibsted Grotesk, system-ui, sans-serif",
        "font-size": 10 * scale,
        "text-valign": "bottom",
        "text-margin-y": 4,
        "text-background-color": token("--panel"),
        "text-background-opacity": full ? 0.75 : 0,
        "text-background-padding": "2px",
        "min-zoomed-font-size": full ? 7 : 0,
        width: 18 * scale,
        height: 18 * scale,
      },
    },
    {
      selector: 'node[kind = "selector"]',
      style: {
        "background-color": token("--accent"),
        width: 36 * scale,
        height: 36 * scale,
        "font-size": 13 * scale,
        "font-weight": 600,
        color: token("--text"),
      },
    },
    {
      selector: 'node[kind = "profile"]',
      style: { "background-color": token("--signal"), width: 22 * scale, height: 22 * scale },
    },
    {
      selector: 'node[grouped = "yes"]',
      style: { "border-width": 3, "border-color": token("--ok") },
    },
    {
      selector:
        'node[kind = "email"], node[kind = "phone"], node[kind = "domain"], node[kind = "username"]',
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
    { selector: ".faded", style: { opacity: 0.12 } },
    {
      selector: "node.match, node:selected",
      style: { "border-width": 4, "border-color": token("--accent"), "z-index": 10 },
    },
  ];
}

const LAYOUTS: Record<GraphLayout, cytoscape.LayoutOptions> = {
  cose: { name: "cose", animate: false, padding: 32, nodeRepulsion: () => 12000 },
  concentric: {
    name: "concentric",
    animate: false,
    padding: 32,
    concentric: (node) => Number(node.data("weight")) * 10,
    levelWidth: () => 2,
    minNodeSpacing: 18,
  },
  breadthfirst: {
    name: "breadthfirst",
    animate: false,
    padding: 32,
    directed: true,
    spacingFactor: 1.2,
  },
  circle: { name: "circle", animate: false, padding: 32 },
};

export interface GraphProps {
  data: GraphData;
  /** Bigger nodes and labels, more nodes, a taller canvas. */
  full?: boolean;
  layout?: GraphLayout;
  /** Highlight nodes whose value contains this text and their neighbours; dim the rest. */
  query?: string;
  /** Changes to this number re-fit the view. */
  fitKey?: number;
  /** Called on node tap (null on the background); by default a tap opens the entity. */
  onSelect?: (id: string | null) => void;
}

export default function Graph({
  data,
  full = false,
  layout = "cose",
  query = "",
  fitKey = 0,
  onSelect,
}: GraphProps) {
  const container = useRef<HTMLDivElement>(null);
  const cy = useRef<Core | null>(null);
  const running = useRef<cytoscape.Layouts | null>(null);
  const layoutRef = useRef(layout);
  layoutRef.current = layout;
  const select = useRef(onSelect);
  select.current = onSelect;
  const [, navigate] = useLocation();
  const { items, hidden } = useMemo(
    () => elements(data, full ? FULL_NODES : PREVIEW_NODES),
    [data, full],
  );

  const relayout = (instance: Core) => {
    // Computed in one go: an animated layout keeps ticking on timers, and a tick that
    // lands after the page is left hits a destroyed instance.
    running.current?.stop();
    running.current = instance.layout(LAYOUTS[layoutRef.current]);
    running.current.run();
  };

  // One Cytoscape instance per mount; live updates only add and remove elements.
  useEffect(() => {
    if (!container.current) return;
    claimStylesheetSlot();
    const instance = cytoscape({
      container: container.current,
      style: style(full),
      wheelSensitivity: 0.3,
      minZoom: 0.1,
      maxZoom: 4,
    });
    instance.on("tap", "node", (event) => {
      if (select.current) select.current(event.target.id());
      else navigate(`/entities/${event.target.id()}`);
    });
    instance.on("tap", (event) => {
      if (event.target === instance) select.current?.(null);
    });
    cy.current = instance;

    // Re-colour when the theme changes.
    const meta = document.querySelector('meta[name="color-scheme"]');
    const observer = new MutationObserver(() => instance.style(style(full)));
    if (meta) observer.observe(meta, { attributes: true, attributeFilter: ["content"] });
    return () => {
      observer.disconnect();
      running.current?.stop();
      running.current = null;
      cy.current = null;
      instance.destroy();
    };
  }, [navigate, full]);

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
    relayout(instance);
  }, [items]);

  useEffect(() => {
    if (cy.current) relayout(cy.current);
  }, [layout]);

  useEffect(() => {
    if (cy.current && fitKey > 0) cy.current.fit(undefined, 32);
  }, [fitKey]);

  useEffect(() => {
    const instance = cy.current;
    if (!instance) return;
    const needle = query.trim().toLowerCase();
    instance.batch(() => {
      instance.elements().removeClass("faded match");
      if (!needle) return;
      const matches = instance.nodes().filter((n) => String(n.data("search")).includes(needle));
      instance.elements().not(matches.closedNeighborhood()).addClass("faded");
      matches.addClass("match");
    });
  }, [query, items]);

  const nodes = items.filter((i) => !("source" in i.data)).length;
  return (
    <>
      <div
        ref={container}
        className={full ? "graph graph-full" : "graph"}
        role="img"
        aria-label={`Graphe des pivots : ${nodes} entités. Le tableau des résultats donne le même contenu.`}
      />
      {hidden > 0 && (
        <p className="muted small-text">
          Les {full ? FULL_NODES : PREVIEW_NODES} entités les plus sûres sont affichées ;{" "}
          {hidden} autres sont dans le tableau.
        </p>
      )}
    </>
  );
}
