import { Link } from "wouter";

export function NotFoundPage() {
  return (
    <div className="empty">
      <h1>Page introuvable</h1>
      <p>Cette adresse ne mène à rien dans DeepSift.</p>
      <Link href="/" className="button primary">
        Lancer une enquête
      </Link>
    </div>
  );
}
