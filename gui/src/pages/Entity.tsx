import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useLocation, useParams } from "wouter";
import { ApiError, type EntityDetail, type EntityType, api, blobUrl } from "../api";
import { LEVEL_LABEL, SERVICE_STATE_LABEL, TYPE_LABEL, percent, shortValue } from "../labels";
import { keys } from "../stream";

const ATTRIBUTE_LABEL: Record<string, string> = {
  site: "Site",
  username: "Pseudo",
  display_name: "Nom affiché",
  fullname: "Nom",
  name: "Nom",
  bio: "Bio",
  location: "Localisation",
  country: "Pays (code)",
  country_name: "Pays",
  carrier: "Opérateur",
  line_type: "Type de ligne",
  international: "Format international",
  national: "Format national",
  e164: "E.164",
  time_zones: "Fuseaux horaires",
  valid: "Numéro valide",
  possible: "Numéro possible",
  created_at: "Compte créé",
  phash: "pHash",
  sha256: "SHA-256",
  mime: "Type MIME",
  width: "Largeur",
  height: "Hauteur",
  trivial: "Image triviale",
  priority: "Priorité",
  title: "Titre",
  snippet: "Extrait",
  engine: "Moteur",
};

const REL_LABEL: Record<string, string> = {
  found_on: "trouvé à partir de",
  avatar: "avatar",
  hash: "empreinte",
  mentions: "mentionné par",
  registered: "compte enregistré",
  mx: "serveur de mail",
  same_as: "même identité",
};

const URLISH: EntityType[] = ["profile", "url", "web_page"];

function show(value: unknown): string {
  if (typeof value === "boolean") return value ? "Oui" : "Non";
  if (Array.isArray(value)) return value.map(show).join(", ");
  if (value && typeof value === "object") return JSON.stringify(value);
  return String(value ?? "");
}

function externalHref(value: string): string | null {
  try {
    const url = new URL(value);
    return url.protocol === "https:" || url.protocol === "http:" ? url.href : null;
  } catch {
    return null;
  }
}

/** Reverse image search engines, opened with the image URL already filled in. */
function reverseSearch(imageUrl: string): { name: string; href: string }[] {
  const u = encodeURIComponent(imageUrl);
  return [
    { name: "TinEye", href: `https://tineye.com/search?url=${u}` },
    { name: "Google Lens", href: `https://lens.google.com/uploadbyurl?url=${u}` },
    { name: "Yandex", href: `https://yandex.com/images/search?rpt=imageview&url=${u}` },
    { name: "Bing", href: `https://www.bing.com/images/search?view=detailv2&iss=sbi&q=imgurl:${u}` },
  ];
}

function sourcesText(entity: EntityDetail): string {
  const names = entity.sources.map((s) => s.service);
  if (names.length === 0) return "Sélecteur saisi";
  if (names.length === 1) return `Trouvé par ${names[0]}`;
  return `Trouvé par ${names.slice(0, -1).join(", ")} et ${names[names.length - 1]}`;
}

function ImageAside({ entity }: { entity: EntityDetail }) {
  const avatar = entity.type === "image" ? entity : null;
  const linkedImage = entity.links.find((l) => l.rel === "avatar" && l.direction === "out")?.entity;
  const image = avatar ? { value: avatar.value } : linkedImage ? { value: linkedImage.value } : null;
  const groupMates = useQuery({
    queryKey: keys.entities(entity.investigation_id),
    queryFn: () => api.entities(entity.investigation_id),
    enabled: entity.avatar_group !== null,
    select: (all) => all.filter((e) => e.avatar_group === entity.avatar_group && e.id !== entity.id),
  });
  if (!image && !entity.avatar_group) return null;
  const local = image ? blobUrl(image.value) : null;
  const remote = image ? externalHref(image.value) : null;

  return (
    <aside className="panel stack" aria-labelledby="h-image">
      <h2 id="h-image">{entity.type === "image" ? "Image" : "Avatar"}</h2>
      {local && <img src={local} alt="Image importée" className="preview" />}
      {remote && (
        <p className="small-text muted">
          L'image distante n'est pas chargée ici, pour ne rien révéler au site qui l'héberge.{" "}
          <a href={remote} target="_blank" rel="noopener noreferrer">
            Ouvrir l'image
          </a>
        </p>
      )}
      {entity.avatar_group && (
        <div className="stack">
          <h3>Même avatar ailleurs (groupe {entity.avatar_group})</h3>
          {groupMates.data?.length ? (
            <ul className="plain-list">
              {groupMates.data.map((mate) => (
                <li key={mate.id}>
                  <Link href={`/entities/${mate.id}`}>{shortValue(mate.type, mate.value)}</Link>
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted small-text">Chargement…</p>
          )}
        </div>
      )}
      {remote && (
        <div className="stack">
          <h3>Recherche inversée</h3>
          <p className="muted small-text">Ouvre le moteur avec l'image déjà chargée, dans un nouvel onglet.</p>
          <div className="actions">
            {reverseSearch(remote).map((engine) => (
              <a
                key={engine.name}
                className="button small"
                href={engine.href}
                target="_blank"
                rel="noopener noreferrer"
              >
                {engine.name}
                <span className="visually-hidden"> (nouvel onglet)</span>
              </a>
            ))}
          </div>
        </div>
      )}
    </aside>
  );
}

export function EntityPage() {
  const { id } = useParams<{ id: string }>();
  const [, navigate] = useLocation();
  const [error, setError] = useState<string | null>(null);
  const entity = useQuery({ queryKey: ["entity", id], queryFn: () => api.entity(id) });
  const pivot = useMutation({
    mutationFn: (services: string[]) => api.pivot(id, services),
    onSuccess: (run) => navigate(`/investigations/${run.investigation_id}`),
    onError: (exc) => setError(exc instanceof ApiError ? exc.message : "Le pivot n'a pas démarré."),
  });

  if (entity.isPending) return <div className="spinner" role="status" aria-label="Chargement" />;
  if (entity.isError) {
    return (
      <div className="empty">
        <p>Cette entité est introuvable.</p>
        <Link href="/investigations" className="button">
          Retour aux enquêtes
        </Link>
      </div>
    );
  }

  const e = entity.data;
  const href = URLISH.includes(e.type) ? externalHref(e.value) : null;
  const attributes = Object.entries(e.attributes).filter(([, v]) => v !== null && v !== "");
  const usable = e.pivots.filter((p) => p.state === "ready" || p.state === "busy");

  return (
    <>
      <Link href={`/investigations/${e.investigation_id}`} className="back-link">
        ← Retour aux résultats
      </Link>
      <header className="entity-head">
        <div className="entity-mark" aria-hidden="true">
          {shortValue(e.type, e.value).charAt(0).toUpperCase()}
        </div>
        <div className="stack">
          <p className="eyebrow muted">{TYPE_LABEL[e.type]}</p>
          <h1 className="wrap-anywhere">{shortValue(e.type, e.value)}</h1>
          {href ? (
            <a href={href} target="_blank" rel="noopener noreferrer" className="mono wrap-anywhere">
              {e.value}
              <span className="visually-hidden"> (nouvel onglet)</span>
            </a>
          ) : shortValue(e.type, e.value) !== e.value ? (
            <p className="mono wrap-anywhere">{e.value}</p>
          ) : null}
          <div className="chips">
            {!e.selector && (
              <span className={`badge ${e.level}`}>
                Confiance {LEVEL_LABEL[e.level].toLowerCase()} ({percent(e.score)})
              </span>
            )}
            {e.avatar_group && <span className="badge group">Avatar du groupe {e.avatar_group}</span>}
            <span className="badge">{sourcesText(e)}</span>
          </div>
        </div>
      </header>

      <div className="split-main">
        <div className="stack gap-lg">
          <section className="panel stack" aria-labelledby="h-info">
            <h2 id="h-info">Informations</h2>
            {attributes.length ? (
              <dl className="facts">
                {attributes.map(([key, value]) => (
                  <div key={key} className="contents">
                    <dt>{ATTRIBUTE_LABEL[key] ?? key}</dt>
                    <dd>{show(value)}</dd>
                  </div>
                ))}
              </dl>
            ) : (
              <p className="muted">Aucun détail de plus pour cette entité.</p>
            )}
            {e.sources.length > 0 && (
              <p className="muted small-text">
                Confiance par source :{" "}
                {e.sources.map((s) => `${s.service} ${percent(s.confidence)}`).join(", ")}.
              </p>
            )}
          </section>

          <section className="panel stack" aria-labelledby="h-pivots">
            <div className="row-between">
              <h2 id="h-pivots">Pivots proposés</h2>
              {usable.length > 1 && (
                <button
                  type="button"
                  className="button small"
                  disabled={pivot.isPending}
                  onClick={() => pivot.mutate(usable.filter((p) => p.enabled).map((p) => p.service))}
                >
                  Tout lancer
                </button>
              )}
            </div>
            {e.pivots.length === 0 ? (
              <p className="muted">Aucun service ne prend ce type d'entité.</p>
            ) : (
              <ul className="list">
                {e.pivots.map((p) => (
                  <li key={p.service}>
                    <div className="grow stack-tight">
                      <span className="strong">{p.service}</span>
                      <span className="sub">
                        {SERVICE_STATE_LABEL[p.state]}
                        {!p.enabled && ", désactivé"}
                      </span>
                    </div>
                    <button
                      type="button"
                      className="button small"
                      disabled={pivot.isPending || p.state === "offline"}
                      onClick={() => pivot.mutate([p.service])}
                    >
                      Lancer<span className="visually-hidden"> {p.service}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {error && (
              <p className="notice danger" role="alert">
                {error}
              </p>
            )}
          </section>

          {e.links.length > 0 && (
            <section className="panel stack" aria-labelledby="h-links">
              <h2 id="h-links">Liens</h2>
              <ul className="list">
                {e.links.map((link, index) =>
                  link.entity ? (
                    <li key={`${link.rel}-${link.entity.id}-${index}`}>
                      <span className="badge">
                        {link.direction === "out" ? "→" : "←"} {REL_LABEL[link.rel] ?? link.rel}
                      </span>
                      <Link href={`/entities/${link.entity.id}`} className="grow wrap-anywhere">
                        {shortValue(link.entity.type, link.entity.value)}
                      </Link>
                      <span className="sub">{TYPE_LABEL[link.entity.type]}</span>
                    </li>
                  ) : null,
                )}
              </ul>
            </section>
          )}
        </div>
        <ImageAside entity={e} />
      </div>
    </>
  );
}
