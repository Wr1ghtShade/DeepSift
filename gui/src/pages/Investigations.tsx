import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "wouter";
import { type InvestigationSummary, api } from "../api";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { formatDate } from "../labels";

export function InvestigationsPage() {
  const client = useQueryClient();
  const investigations = useQuery({ queryKey: ["investigations"], queryFn: api.investigations });
  const [doomed, setDoomed] = useState<InvestigationSummary | null>(null);
  const remove = useMutation({
    mutationFn: (id: string) => api.deleteInvestigation(id),
    onSettled: () => client.invalidateQueries({ queryKey: ["investigations"] }),
  });

  return (
    <>
      <header className="page-head">
        <div>
          <h1>Enquêtes</h1>
          <p className="lede">Chaque dossier garde ses résultats fusionnés, ses pivots et ses exports.</p>
        </div>
        <div className="actions">
          <Link href="/" className="button primary">
            Nouvelle enquête
          </Link>
        </div>
      </header>

      {investigations.isPending ? (
        <div className="spinner" role="status" aria-label="Chargement" />
      ) : investigations.isError ? (
        <p className="notice danger" role="alert">
          Impossible de charger les enquêtes : {investigations.error.message}
        </p>
      ) : investigations.data.length === 0 ? (
        <div className="empty">
          <p>Aucune enquête pour l'instant.</p>
          <Link href="/" className="button primary">
            Lancer la première
          </Link>
        </div>
      ) : (
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th scope="col">Dossier</th>
                <th scope="col">Résultats</th>
                <th scope="col">Créé le</th>
                <th scope="col">
                  <span className="visually-hidden">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {investigations.data.map((inv) => (
                <tr key={inv.id}>
                  <th scope="row">
                    <Link href={`/investigations/${inv.id}`} className="cell-link">
                      <span className="primary-text">{inv.name}</span>
                    </Link>
                  </th>
                  <td data-label="Résultats">{inv.entities}</td>
                  <td className="muted" data-label="Créé le">{formatDate(inv.created_at)}</td>
                  <td className="cell-actions">
                    <button
                      type="button"
                      className="button small danger"
                      onClick={() => setDoomed(inv)}
                    >
                      Supprimer<span className="visually-hidden"> {inv.name}</span>
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <ConfirmDialog
        open={doomed !== null}
        title="Supprimer ce dossier ?"
        confirmLabel="Supprimer"
        onConfirm={() => doomed && remove.mutate(doomed.id)}
        onClose={() => setDoomed(null)}
      >
        <p>
          « {doomed?.name} » et ses {doomed?.entities} résultats seront effacés. Les runs en cours
          sont arrêtés. Cette action est définitive.
        </p>
      </ConfirmDialog>
    </>
  );
}
