// The round sieve mark (logo A), drawn in currentColor.
const DOTS: [number, number][] = [
  [16, 24], [16, 32], [16, 40],
  [24, 16], [24, 24], [24, 32], [24, 40], [24, 48],
  [32, 16], [32, 24], [32, 32], [32, 40], [32, 48],
  [40, 16], [40, 24], [40, 32], [40, 48],
  [48, 24], [48, 32], [48, 40],
];

export function Logo({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" aria-hidden="true">
      <circle cx="32" cy="32" r="27" fill="none" stroke="currentColor" strokeWidth="4" />
      {DOTS.map(([cx, cy]) => (
        <circle key={`${cx}-${cy}`} cx={cx} cy={cy} r="2.2" fill="currentColor" fillOpacity="0.45" />
      ))}
      <circle cx="40" cy="40" r="4.2" fill="currentColor" />
    </svg>
  );
}
