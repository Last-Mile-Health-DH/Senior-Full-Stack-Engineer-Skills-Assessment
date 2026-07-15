# Frontend

The Next.js app for the Last Mile Health RAG platform. It serves the chat workspace at `/` and the document upload page at `/documents`.

## Chat-surface decision: both, alongside each other

The starter allows Chainlit "in place of or alongside the Next.js frontend". **This build keeps both**, and they are equals:

| Surface | URL | What it is |
|---|---|---|
| Next.js chat | http://localhost:3000/ | Chat workspace with sidebar navigation, a `+` upload button in the composer, and a responsive hamburger drawer |
| Chainlit chat | http://localhost:8000/ | Equivalent chat surface with a `+ Upload PDF` button in its header |
| Upload page | http://localhost:3000/documents | The single ingestion entry point. Both chat surfaces link to it. |

Neither client implements retrieval, generation, or citation logic. Both `POST /api/v1/chat` and render the answer exactly as the backend presented it, plus the same `Sources` list built from the same citation metadata. **A behavioral difference between the two surfaces is a bug, not a feature of one of them.**

Answer presentation lives in the backend (`backend/app/chat/response_presenter.py`) precisely because there are two clients: putting the writing-style and citation rules behind the API is what stops them from drifting apart.

## Reviewer Status

| Area | Status | Notes |
|---|---|---|
| Chat route `/` | Complete | Active nav state, responsive drawer, loading row, duplicate-send prevention, superscripts linked to a `Sources` list, `+` upload button at every viewport. |
| `/documents` route | Complete | Upload with progress, status polling, friendly status labels, optimistic delete with rollback. |
| Helper layer | Verified | `tests/chatCore.test.mjs` and `tests/documentsCore.test.mjs` cover chat POST, answer block parsing, citation-marker splitting, reference lines, upload validation, progress, polling, and delete/rollback. |
| Responsive browser pass | Complete | Real Chromium at 375x812, 768x1024, 1024x768, 1440x900. No overflow, no clipped controls, no overlap. |
| Playwright | Complete for the chat UI | `e2e/chat-ui.spec.ts` -> 16 passed. `e2e/upload-chainlit-citation.spec.ts` still needs a live ingestion round trip. |

## Accessibility

- Sidebar collapses to a hamburger drawer at `<= 1024px`. The toggle carries `aria-expanded` and `aria-controls`, and has a visible focus ring.
- The drawer closes on Escape, on selecting an internal link, and on clicking outside. The click-outside scrim is `aria-hidden` — it is a redundant affordance, and exposing it as a button would put a second control with the same label in the accessibility tree.
- The current page is marked `aria-current="page"`. External services (Chainlit, API docs, health) never claim active state, because this app cannot know whether the user is looking at them.
- The loading row is announced via `role="status"` inside an `aria-live="polite"` log.
- The dot animation is disabled under `prefers-reduced-motion`.

## Answer rendering

Answers are rendered as **inert text**, never as HTML — a malicious PDF cannot inject markup through an answer. `parseAnswerBlocks` recovers only the paragraph/bullet structure the backend emitted, and `splitCitationMarkers` pulls out the superscript runs so each one can be rendered small and linked to its entry in the `Sources` list. An answer with no citations renders no `Sources` heading at all.

## Local Development

```sh
npm install
npm run dev
```

Open http://localhost:3000 for chat and http://localhost:3000/documents to add a PDF.

Point at a non-default backend in `frontend/.env.local`:

```sh
NEXT_PUBLIC_API_BASE_URL=http://localhost:6100/api/v1
```

## Tests

```sh
npm test -- --runInBand          # 21 passed
npx tsc --noEmit                 # typecheck

npm run playwright:install
PLAYWRIGHT_BASE_URL=http://localhost:3000 \
PLAYWRIGHT_CHAINLIT_BASE_URL=http://localhost:8000 \
npm run test:e2e                 # 16 passed
```

Deterministic tests use Node's built-in test runner. Playwright needs the stack running on ports 3000, 8000, and 6100, and browser binaries installed.

## Current Limitations

- `e2e/upload-chainlit-citation.spec.ts` (upload → indexed → cited answer) has not been run in this pass; it needs a live ingestion round trip.
- The chat UI mocks `/api/v1/chat` at the network boundary in `chat-ui.spec.ts` so rendering is deterministic. The real request path is covered by the backend integration suite instead.
