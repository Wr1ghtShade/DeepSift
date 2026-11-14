export function GraphLegend() {
  return (
    <div className="legend" aria-label="Légende">
      <span>
        <i className="dot-selector" /> Sélecteur
      </span>
      <span>
        <i className="dot-profile" /> Profil
      </span>
      <span>
        <i className="dot-pivot" /> Nouveau sélecteur
      </span>
      <span>
        <i className="dot-group" /> Même avatar
      </span>
    </div>
  );
}
