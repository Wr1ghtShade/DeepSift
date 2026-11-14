// Findings of an investigation: sortable, filterable, paged by "show more".
import {
  type ColumnDef,
  type SortingState,
  getCoreRowModel,
  getFilteredRowModel,
  getSortedRowModel,
  useReactTable,
} from "@tanstack/react-table";
import { useMemo, useState } from "react";
import { Link } from "wouter";
import type { Entity, EntityType } from "../api";
import { LEVEL_LABEL, TYPE_LABEL, percent, shortValue } from "../labels";
import { Choice } from "./Choice";

const PAGE = 200;

const COLUMNS: ColumnDef<Entity>[] = [
  {
    id: "entity",
    header: "Entité",
    accessorFn: (e) => e.value,
    cell: ({ row }) => {
      const e = row.original;
      const short = shortValue(e.type, e.value);
      return (
        <>
          <Link href={`/entities/${e.id}`} className="cell-link">
            <span className="primary-text">{short}</span>
            {short !== e.value && <span className="secondary-text">{e.value}</span>}
          </Link>
          {e.avatar_group && <span className="badge group">Avatar {e.avatar_group}</span>}
        </>
      );
    },
  },
  {
    id: "type",
    header: "Type",
    accessorFn: (e) => TYPE_LABEL[e.type],
  },
  {
    id: "sources",
    header: "Trouvé par",
    accessorFn: (e) => e.sources.map((s) => s.service).join(", "),
    sortingFn: (a, b) => a.original.sources.length - b.original.sources.length,
  },
  {
    id: "score",
    header: "Confiance",
    accessorFn: (e) => e.score,
    cell: ({ row }) => (
      <span className="score">
        <span className={`badge ${row.original.level}`}>{LEVEL_LABEL[row.original.level]}</span>
        <span className="mono muted">{percent(row.original.score)}</span>
      </span>
    ),
  },
];

const SORT_LABEL: Record<string, string> = {
  entity: "entité",
  type: "type",
  sources: "nombre de sources",
  score: "confiance",
};

export function EntityTable({ entities }: { entities: Entity[] }) {
  const [sorting, setSorting] = useState<SortingState>([{ id: "score", desc: true }]);
  const [filter, setFilter] = useState("");
  const [type, setType] = useState<"all" | EntityType>("all");
  const [shown, setShown] = useState(PAGE);

  const findings = useMemo(() => entities.filter((e) => !e.selector), [entities]);
  const counts = useMemo(() => {
    const map = new Map<EntityType, number>();
    for (const e of findings) map.set(e.type, (map.get(e.type) ?? 0) + 1);
    return [...map.entries()].sort((a, b) => b[1] - a[1]);
  }, [findings]);
  const data = useMemo(
    () => (type === "all" ? findings : findings.filter((e) => e.type === type)),
    [findings, type],
  );

  const table = useReactTable({
    data,
    columns: COLUMNS,
    state: { sorting, globalFilter: filter },
    onSortingChange: setSorting,
    onGlobalFilterChange: setFilter,
    globalFilterFn: "includesString",
    getRowId: (row) => row.id,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
  });

  const rows = table.getRowModel().rows;
  const sort = sorting[0];

  return (
    <div className="stack">
      <div className="row-between">
        <h2 id="h-findings">Résultats</h2>
        <div className="field inline-field">
          <label htmlFor="filter">Filtrer</label>
          <input
            id="filter"
            type="search"
            className="input"
            value={filter}
            onChange={(e) => {
              setFilter(e.target.value);
              setShown(PAGE);
            }}
            placeholder="github, maigret…"
          />
        </div>
      </div>
      {counts.length > 1 && (
        <Choice
          legend="Type d'entité"
          hideLegend
          value={type}
          onChange={(next) => {
            setType(next);
            setShown(PAGE);
          }}
          options={[
            { value: "all" as const, label: `Tout (${findings.length})` },
            ...counts.map(([t, n]) => ({ value: t, label: `${TYPE_LABEL[t]} (${n})` })),
          ]}
        />
      )}
      <p role="status" className="visually-hidden">
        {sort
          ? `Trié par ${SORT_LABEL[sort.id]}, ordre ${sort.desc ? "décroissant" : "croissant"}. `
          : ""}
        {rows.length} résultat{rows.length > 1 ? "s" : ""}.
      </p>
      {findings.length === 0 ? (
        <p className="empty">Rien pour l'instant. Les résultats apparaissent ici dès qu'un service trouve quelque chose.</p>
      ) : (
        <div className="table-wrap">
          <table className="data" aria-labelledby="h-findings">
            <thead>
              {table.getHeaderGroups().map((group) => (
                <tr key={group.id}>
                  {group.headers.map((header) => {
                    const dir = header.column.getIsSorted();
                    return (
                      <th
                        key={header.id}
                        scope="col"
                        aria-sort={
                          dir === "asc" ? "ascending" : dir === "desc" ? "descending" : undefined
                        }
                      >
                        <button type="button" onClick={header.column.getToggleSortingHandler()}>
                          {String(header.column.columnDef.header)}
                        </button>
                      </th>
                    );
                  })}
                </tr>
              ))}
            </thead>
            <tbody>
              {rows.slice(0, shown).map((row) => (
                <tr key={row.id}>
                  {row.getVisibleCells().map((cell, index) => {
                    const render = cell.column.columnDef.cell;
                    const content =
                      typeof render === "function"
                        ? render(cell.getContext())
                        : String(cell.getValue() ?? "");
                    return index === 0 ? (
                      <th key={cell.id} scope="row">
                        {content}
                      </th>
                    ) : (
                      <td key={cell.id} data-label={String(cell.column.columnDef.header)}>
                        {content}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {rows.length > shown && (
        <button type="button" className="button" onClick={() => setShown(shown + PAGE)}>
          Afficher {Math.min(PAGE, rows.length - shown)} de plus ({rows.length - shown} restants)
        </button>
      )}
    </div>
  );
}
