# gui

DeepSift's web GUI: React 19, Vite, TypeScript, TanStack Query and Table, Cytoscape.js
for the pivot graph. The gateway serves the build (`DEEPSIFT_GUI_DIR`), under a strict CSP.

| Screen | Path |
|---|---|
| Login (API token → session cookie) | shown when no session |
| New investigation | `/` |
| Investigations | `/investigations` |
| Live results: lanes, findings, graph, export | `/investigations/:id` |
| Entity: details, links, pivots, reverse image search | `/entities/:id` |
| Services: registry, on/off, manifest | `/services` |

Themes: graphite (dark, default) and clair ("papier technique", light), as `light-dark()`
token pairs driven by `<meta name="color-scheme">`.

## Develop

```
uv run deepsift-gateway                                     # terminal 1, port 8000
DEEPSIFT_ALLOWED_ORIGINS=http://localhost:5173 uv run deepsift-gateway   # (if you use Vite)
cd gui && npm install && npm run dev                        # terminal 2, port 5173
npm test            # unit tests (Vitest)
npm run build       # type check, then gui/dist
```

To try the build: `npm run build`, then `DEEPSIFT_GUI_DIR=gui/dist uv run deepsift-gateway`.

## Choices

| Topic | Choice |
|---|---|
| Components | Native platform first, per modern-web-guidance: `<dialog>` (modal, focus and Esc handled by the browser), `popover` menus with anchor positioning, native radios as chips, `<progress>`, `<input switch>`. No component kit that injects inline styles, which the CSP forbids |
| Security | No token in JS (HttpOnly cookie), no `innerHTML`, Trusted Types enforced, nonce CSP stamped by the gateway on the tags Vite emits (`html.cspNonce`). Remote images are never loaded: that would tell the target's site who is looking |
| Motion | Same-document view transitions between pages, off with `prefers-reduced-motion` |
| Accessibility | Landmarks, skip link, row headers, `aria-sort`, live status for runs and sorts, tables that turn into cards in narrow containers, text that follows the OS text size |
| Live data | One WebSocket per open investigation; task messages patch the cache, findings refresh at most every 400 ms |
