import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Link, useLocation } from "wouter";
import { api } from "../api";
import { Logo } from "./Logo";
import { ThemeToggle } from "./ThemeToggle";

const LINKS: { href: string; label: string; match: (path: string) => boolean }[] = [
  { href: "/", label: "Nouvelle enquête", match: (p) => p === "/" },
  {
    href: "/investigations",
    label: "Enquêtes",
    match: (p) => p.startsWith("/investigations") || p.startsWith("/entities"),
  },
  { href: "/services", label: "Services", match: (p) => p.startsWith("/services") },
  { href: "/settings", label: "Réglages", match: (p) => p.startsWith("/settings") },
];

function ServicesStatus() {
  const services = useQuery({ queryKey: ["services"], queryFn: api.services });
  if (!services.data) return null;
  const online = services.data.filter((s) => s.state === "ready" || s.state === "busy").length;
  const needs = services.data.filter((s) => s.state === "needs_config").length;
  const offline = services.data.filter((s) => s.state === "offline").length;
  return (
    <div className="status-card">
      <strong>
        {online} service{online > 1 ? "s" : ""} en ligne
      </strong>
      {needs > 0 && (
        <span>
          {needs} attend{needs > 1 ? "ent" : ""} une configuration
        </span>
      )}
      {offline > 0 && <span>{offline} hors ligne</span>}
      <Link href="/services">Voir les services</Link>
    </div>
  );
}

export function Shell({ children }: { children: ReactNode }) {
  const [location] = useLocation();
  const client = useQueryClient();

  const logout = async () => {
    try {
      await api.logout();
    } finally {
      client.clear();
      client.setQueryData(["session"], { authenticated: false });
    }
  };

  return (
    <div className="app">
      <a className="skip-link" href="#content">
        Aller au contenu
      </a>
      <nav className="sidebar" aria-label="Navigation principale">
        <Link href="/" className="brand">
          <Logo />
          <span>DeepSift</span>
        </Link>
        <div className="nav-links">
          {LINKS.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              aria-current={link.match(location) ? "page" : undefined}
            >
              {link.label}
            </Link>
          ))}
        </div>
        <div className="sidebar-foot">
          <ServicesStatus />
          <ThemeToggle />
          <button type="button" className="button" onClick={logout}>
            Se déconnecter
          </button>
        </div>
      </nav>
      <main id="content" className="page" tabIndex={-1}>
        {children}
      </main>
    </div>
  );
}
