import { useQuery } from "@tanstack/react-query";
import { type DragEvent, type FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation } from "wouter";
import { ApiError, type EntityType, type ServiceInfo, api } from "../api";
import { Choice } from "../components/Choice";
import { detectType } from "../detect";
import { type Depth, defaultDepth } from "../prefs";
import { SELECTOR_TYPES, SERVICE_STATE_LABEL, TYPE_LABEL, formatRelative } from "../labels";

type TypeChoice = "auto" | EntityType;

const DEPTHS: { value: Depth; label: string }[] = [
  { value: "0", label: "Aucun pivot" },
  { value: "1", label: "1 rebond" },
  { value: "2", label: "2 rebonds" },
  { value: "3", label: "3 rebonds" },
];

const usable = (s: ServiceInfo) => s.state === "ready" || s.state === "busy";

function defaultSelection(services: ServiceInfo[], type: EntityType): Set<string> {
  return new Set(
    services.filter((s) => s.inputs.includes(type) && s.enabled && usable(s)).map((s) => s.name),
  );
}

function serviceNote(service: ServiceInfo): string | null {
  if (service.state === "needs_config") {
    return service.missing.length
      ? `À configurer : ${service.missing.join(", ")}`
      : SERVICE_STATE_LABEL.needs_config;
  }
  if (service.state === "offline") return SERVICE_STATE_LABEL.offline;
  if (!service.enabled) return "Désactivé (opt-in)";
  return service.rate_limit ? `Limite : ${service.rate_limit}` : null;
}

function RecentInvestigations() {
  const investigations = useQuery({ queryKey: ["investigations"], queryFn: api.investigations });
  const recent = investigations.data?.slice(0, 6) ?? [];
  return (
    <div className="stack">
      <h2>Enquêtes récentes</h2>
      {investigations.isPending ? (
        <div className="spinner" role="status" aria-label="Chargement" />
      ) : recent.length === 0 ? (
        <p className="empty">Aucune enquête pour l'instant. La première commence à gauche.</p>
      ) : (
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th scope="col">Dossier</th>
                <th scope="col">Résultats</th>
                <th scope="col">Créé</th>
              </tr>
            </thead>
            <tbody>
              {recent.map((inv) => (
                <tr key={inv.id}>
                  <th scope="row">
                    <Link href={`/investigations/${inv.id}`} className="cell-link">
                      <span className="primary-text">{inv.name}</span>
                    </Link>
                  </th>
                  <td data-label="Résultats">{inv.entities}</td>
                  <td className="muted" data-label="Créé">{formatRelative(inv.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export function NewSearchPage() {
  const [, navigate] = useLocation();
  const services = useQuery({ queryKey: ["services"], queryFn: api.services });
  const [selector, setSelector] = useState("");
  const [choice, setChoice] = useState<TypeChoice>("auto");
  const [depth, setDepth] = useState<Depth>(defaultDepth);
  const [name, setName] = useState("");
  const [picked, setPicked] = useState<Set<string> | null>(null);
  const [image, setImage] = useState<{ selector: string; preview: string; name: string } | null>(
    null,
  );
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  const value = image ? image.selector : selector;
  const detected = detectType(value || "x");
  const type: EntityType = image ? "image" : choice === "auto" ? detected : choice;

  const candidates = useMemo(
    () => (services.data ?? []).filter((s) => s.inputs.includes(type)),
    [services.data, type],
  );
  // The selection follows the type until the person changes it by hand.
  const selected = picked ?? defaultSelection(services.data ?? [], type);
  useEffect(() => setPicked(null), [type]);

  useEffect(() => () => {
    if (image) URL.revokeObjectURL(image.preview);
  }, [image]);

  const toggle = (service: string) => {
    const next = new Set(selected);
    if (next.has(service)) next.delete(service);
    else next.add(service);
    setPicked(next);
  };

  const takeFile = async (file: File | undefined) => {
    if (!file) return;
    if (!file.type.startsWith("image/")) {
      setError("Seules les images PNG, JPEG, GIF et WebP sont acceptées.");
      return;
    }
    setError(null);
    setBusy(true);
    try {
      const stored = await api.uploadImage(file);
      setImage({ selector: stored.selector, preview: URL.createObjectURL(file), name: file.name });
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "L'image n'a pas pu être envoyée.");
    } finally {
      setBusy(false);
    }
  };

  const onDrop = (event: DragEvent) => {
    event.preventDefault();
    setDragging(false);
    void takeFile(event.dataTransfer.files[0]);
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!value.trim()) return;
    if (selected.size === 0) {
      setError("Cochez au moins un service.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const label = image ? image.name : value.trim();
      const investigation = await api.createInvestigation(name.trim() || label);
      const maxDepth = Number(depth);
      await api.startRun(investigation.id, {
        selector: value.trim(),
        type,
        services: [...selected],
        auto_pivot: maxDepth > 0,
        max_depth: maxDepth,
      });
      navigate(`/investigations/${investigation.id}`);
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "La gateway ne répond pas.");
      setBusy(false);
    }
  };

  return (
    <>
      <header className="page-head">
        <div>
          <h1>Que cherchez-vous ?</h1>
          <p className="lede">
            Un pseudo, un e-mail, un numéro de téléphone, un domaine, ou une image déposée ici.
            DeepSift reconnaît le type et lance les services compatibles.
          </p>
        </div>
      </header>

      <form className="stack" onSubmit={submit} noValidate>
        <section className="panel stack" aria-label="Sélecteur">
          <label htmlFor="selector" className="field-label">
            Sélecteur
          </label>
          <div className="row-wrap">
            <div
              className={`selector-box${dragging ? " dragging" : ""}`}
              onDragOver={(e) => {
                e.preventDefault();
                setDragging(true);
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={onDrop}
            >
              {image ? (
                <>
                  <img src={image.preview} alt="" className="thumb" />
                  <span className="mono wrap-anywhere selector-image-name">{image.name}</span>
                  <button type="button" className="button small" onClick={() => setImage(null)}>
                    Retirer
                  </button>
                </>
              ) : (
                <input
                  id="selector"
                  value={selector}
                  onChange={(e) => setSelector(e.target.value)}
                  placeholder="nightowl_77"
                  autoComplete="off"
                  spellCheck={false}
                  autoCapitalize="off"
                  enterKeyHint="search"
                  maxLength={2048}
                  required
                />
              )}
              <span className="detected" aria-live="polite">
                {choice === "auto" && !image
                  ? `${TYPE_LABEL[detected]} détecté`
                  : TYPE_LABEL[type]}
              </span>
            </div>
            <button
              type="submit"
              className="button primary big"
              disabled={busy || !value.trim() || selected.size === 0}
            >
              {busy ? "Lancement…" : "Lancer l'enquête"}
            </button>
          </div>
          <div className="row-wrap">
            <Choice
              legend="Type de sélecteur"
              hideLegend
              value={image ? "image" : choice}
              onChange={(next) => {
                if (next === "image") fileInput.current?.click();
                else {
                  setImage(null);
                  setChoice(next);
                }
              }}
              options={[
                { value: "auto" as TypeChoice, label: "Auto" },
                ...SELECTOR_TYPES.map((t) => ({ value: t as TypeChoice, label: TYPE_LABEL[t] })),
              ]}
            />
            <input
              ref={fileInput}
              type="file"
              accept="image/png,image/jpeg,image/gif,image/webp"
              className="visually-hidden"
              tabIndex={-1}
              aria-hidden="true"
              onChange={(e) => void takeFile(e.target.files?.[0])}
            />
          </div>
          {error && (
            <p className="notice danger" role="alert">
              {error}
            </p>
          )}
        </section>

        <div className="split">
          <section className="stack" aria-labelledby="h-services">
            <div className="row-between">
              <h2 id="h-services">Services qui vont tourner</h2>
              <Choice
                legend="Pivots automatiques"
                hideLegend
                variant="segmented"
                value={depth}
                onChange={setDepth}
                options={DEPTHS}
              />
            </div>
            <p className="muted small-text">
              Les pivots relancent les services sur ce qui est trouvé (un e-mail dans un profil, un
              avatar…), jusqu'au nombre de rebonds choisi.
            </p>
            {services.isPending ? (
              <div className="spinner" role="status" aria-label="Chargement des services" />
            ) : candidates.length === 0 ? (
              <p className="empty">Aucun service installé ne prend un {TYPE_LABEL[type].toLowerCase()}.</p>
            ) : (
              <ul className="list">
                {candidates.map((service) => {
                  const note = serviceNote(service);
                  return (
                    <li key={service.name}>
                      <input
                        type="checkbox"
                        id={`svc-${service.name}`}
                        checked={selected.has(service.name)}
                        onChange={() => toggle(service.name)}
                      />
                      <label htmlFor={`svc-${service.name}`}>
                        <span className="strong">{service.name}</span>
                        <span className="sub">{service.description}</span>
                        {note && <span className="sub note">{note}</span>}
                      </label>
                    </li>
                  );
                })}
              </ul>
            )}
            <div className="field">
              <label htmlFor="dossier">Nom du dossier</label>
              <input
                id="dossier"
                className="input"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder={value ? (image ? image.name : value) : "Par défaut : le sélecteur"}
                maxLength={200}
              />
            </div>
          </section>
          <RecentInvestigations />
        </div>
      </form>
    </>
  );
}
