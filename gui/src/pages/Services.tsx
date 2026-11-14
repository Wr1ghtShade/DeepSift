import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { type EntityType, type ServiceInfo, api } from "../api";
import { Choice } from "../components/Choice";
import { SELECTOR_TYPES, SERVICE_STATE_LABEL, TYPE_LABEL } from "../labels";

function manifestText(service: ServiceInfo): string {
  const lines = [
    `name: ${service.name}`,
    `version: ${service.version}`,
    `license: ${service.license}`,
    `inputs: [${service.inputs.join(", ")}]`,
    `outputs: [${service.outputs.join(", ")}]`,
  ];
  if (service.rate_limit) lines.push(`rate_limit: ${service.rate_limit}`);
  lines.push(`enabled_by_default: ${service.enabled_by_default}`);
  const options = Object.entries(service.options);
  if (options.length) {
    lines.push("options:");
    for (const [name, spec] of options) {
      const values = spec.values ? ` [${spec.values.join(", ")}]` : "";
      lines.push(`  ${name}: ${spec.type}${values}, default ${String(spec.default)}`);
    }
  }
  if (service.missing.length) lines.push(`missing: [${service.missing.join(", ")}]`);
  lines.push("instances:");
  if (service.instances.length === 0) lines.push("  (none)");
  for (const instance of service.instances) {
    lines.push(`  - ${instance.id}: ${instance.state}, ${instance.running} running`);
  }
  return lines.join("\n");
}

export function ServicesPage() {
  const client = useQueryClient();
  const services = useQuery({ queryKey: ["services"], queryFn: api.services });
  const [filter, setFilter] = useState<"all" | EntityType>("all");
  const [selected, setSelected] = useState<string | null>(null);
  const toggle = useMutation({
    mutationFn: ({ name, enabled }: { name: string; enabled: boolean }) =>
      api.setServiceEnabled(name, enabled),
    onSettled: () => client.invalidateQueries({ queryKey: ["services"] }),
  });

  const list = (services.data ?? []).filter((s) => filter === "all" || s.inputs.includes(filter));
  const current =
    services.data?.find((s) => s.name === selected) ?? list[0] ?? services.data?.[0] ?? null;

  return (
    <>
      <header className="page-head">
        <div>
          <h1>Services</h1>
          <p className="lede">
            Chaque capacité tourne dans son propre service. Un nouveau service s'enregistre au
            démarrage et apparaît ici, prêt à servir dans les enquêtes.
          </p>
        </div>
        <div className="actions">
          <button
            type="button"
            className="button"
            onClick={() => void client.invalidateQueries({ queryKey: ["services"] })}
            disabled={services.isFetching}
          >
            {services.isFetching ? "Rechargement…" : "Recharger le registre"}
          </button>
        </div>
      </header>

      <Choice
        legend="Filtrer par type d'entrée"
        hideLegend
        value={filter}
        onChange={setFilter}
        options={[
          { value: "all" as const, label: "Tous" },
          ...SELECTOR_TYPES.map((t) => ({ value: t, label: TYPE_LABEL[t] })),
        ]}
      />

      {services.isPending ? (
        <div className="spinner" role="status" aria-label="Chargement" />
      ) : services.isError ? (
        <p className="notice danger" role="alert">
          Impossible de lire le registre : {services.error.message}
        </p>
      ) : (
        <div className="split-main split-services">
          <div className="table-wrap">
            <table className="data">
              <caption className="visually-hidden">Services enregistrés</caption>
              <thead>
                <tr>
                  <th scope="col">Service</th>
                  <th scope="col">Entrée</th>
                  <th scope="col">Sortie</th>
                  <th scope="col">État</th>
                  <th scope="col">Activé</th>
                </tr>
              </thead>
              <tbody>
                {list.map((service) => (
                  <tr key={service.name} className={current?.name === service.name ? "selected" : ""}>
                    <th scope="row">
                      <button
                        type="button"
                        className="link-button"
                        aria-pressed={current?.name === service.name}
                        onClick={() => setSelected(service.name)}
                      >
                        <span className="strong">{service.name}</span>
                        <span className="description">{service.description}</span>
                      </button>
                    </th>
                    <td data-label="Entrée">{service.inputs.map((t) => TYPE_LABEL[t]).join(", ")}</td>
                    <td data-label="Sortie">{service.outputs.map((t) => TYPE_LABEL[t]).join(", ")}</td>
                    <td data-label="État">
                      <span className={`badge ${service.state}`}>
                        {SERVICE_STATE_LABEL[service.state]}
                      </span>
                    </td>
                    <td data-label="Activé">
                      <input
                        type="checkbox"
                        {...({ switch: "" } as object)}
                        aria-label={`Activer ${service.name}`}
                        checked={service.enabled}
                        disabled={toggle.isPending}
                        onChange={(e) => toggle.mutate({ name: service.name, enabled: e.target.checked })}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {current && (
            <aside className="panel stack" aria-labelledby="h-manifest">
              <h2 id="h-manifest">Manifeste de {current.name}</h2>
              <p className="muted small-text">Le contrat que ce service publie à la gateway.</p>
              <pre className="manifest">{manifestText(current)}</pre>
              {current.missing.length > 0 && (
                <p className="notice">
                  Variables à définir pour ce service : {current.missing.join(", ")}.
                </p>
              )}
            </aside>
          )}
        </div>
      )}
    </>
  );
}
