import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  CHAT_ERROR_MESSAGE,
  EXTERNAL_NAV,
  INTERNAL_NAV,
  isActivePath,
  parseAnswerBlocks,
  postChat,
  referenceLines,
  splitCitationMarkers,
} from "../src/lib/chatCore.js";

test("active state follows the route pathname for internal links only", () => {
  assert.equal(isActivePath("/", "/"), true);
  assert.equal(isActivePath("/documents", "/"), false);
  assert.equal(isActivePath("/documents", "/documents"), true);
  assert.equal(isActivePath("/documents/abc", "/documents"), true);

  // External services are reachable but this app cannot know if the user is on them.
  const externalHrefs = EXTERNAL_NAV.map((item) => item.href);
  for (const href of externalHrefs) {
    assert.equal(isActivePath("/", href), false);
    assert.equal(isActivePath("/documents", href), false);
  }
  assert.deepEqual(
    INTERNAL_NAV.map((item) => item.href),
    ["/", "/documents"],
  );
});

test("chat posts to the backend and returns the presented payload", async () => {
  const calls = [];
  const fakeFetch = async (url, options) => {
    calls.push({ url: String(url), options });
    return {
      ok: true,
      status: 200,
      json: async () => ({ session_id: "s1", answer: "The dose is 5 ml.¹", citations: [] }),
    };
  };

  const result = await postChat("dose?", null, fakeFetch);

  assert.equal(calls[0].url, "http://localhost:6100/api/v1/chat");
  assert.equal(calls[0].options.method, "POST");
  assert.deepEqual(JSON.parse(calls[0].options.body), { message: "dose?" });
  assert.equal(result.answer, "The dose is 5 ml.¹");
});

test("chat forwards the backend session id on later turns", async () => {
  const calls = [];
  const fakeFetch = async (url, options) => {
    calls.push(JSON.parse(options.body));
    return { ok: true, status: 200, json: async () => ({ session_id: "s1", answer: "ok" }) };
  };

  await postChat("second question", "s1", fakeFetch);

  assert.deepEqual(calls[0], { message: "second question", session_id: "s1" });
});

test("a failed chat call surfaces the honest user-facing error", async () => {
  const fakeFetch = async () => ({ ok: false, status: 500, json: async () => ({}) });

  await assert.rejects(() => postChat("dose?", null, fakeFetch), /Chat failed with 500/);
  assert.match(CHAT_ERROR_MESSAGE, /could not reach the chat service/i);
});

test("answers split into paragraphs and bullets without interpreting markup", () => {
  const blocks = parseAnswerBlocks(
    "Doses vary by age.¹\n\n- Children get 5 ml.¹\n- Adults get 10 ml.²",
  );

  assert.deepEqual(blocks, [
    { type: "paragraph", text: "Doses vary by age.¹" },
    { type: "bullets", items: ["Children get 5 ml.¹", "Adults get 10 ml.²"] },
  ]);
});

test("raw html in an answer stays inert text rather than becoming markup", () => {
  const blocks = parseAnswerBlocks("<img src=x onerror=alert(1)>");

  assert.deepEqual(blocks, [{ type: "paragraph", text: "<img src=x onerror=alert(1)>" }]);
});

test("superscript markers are split out so they can be linked to references", () => {
  const segments = splitCitationMarkers("The child dose is 5 ml.¹² Adults differ.³");

  assert.deepEqual(segments, [
    { type: "text", value: "The child dose is 5 ml." },
    { type: "citation", value: "¹²", numbers: [1, 2] },
    { type: "text", value: " Adults differ." },
    { type: "citation", value: "³", numbers: [3] },
  ]);
});

test("an answer with no citations produces no reference list", () => {
  assert.deepEqual(referenceLines([]), []);
  assert.deepEqual(referenceLines(undefined), []);
  assert.deepEqual(
    referenceLines([{ number: 1, reference: "1. Oral Rehydration Protocol, p. 1." }]),
    [{ number: 1, text: "1. Oral Rehydration Protocol, p. 1." }],
  );
});

test("chat page renders a loading row and blocks duplicate sends", async () => {
  const source = await readFile(new URL("../src/app/page.tsx", import.meta.url), "utf8");

  assert.match(source, /ThinkingRow/);
  assert.match(source, /thinking-dots/);
  assert.match(source, /Searching your documents/);
  // The in-flight guard is what prevents a duplicate turn for the same prompt.
  assert.match(source, /if \(!question \|\| isSending\)/);
  assert.match(source, /disabled=\{isSending \|\| !input\.trim\(\)\}/);
});

test("chat page renders a Sources list and never fakes citations", async () => {
  const source = await readFile(new URL("../src/app/page.tsx", import.meta.url), "utf8");

  assert.match(source, /<h3>Sources<\/h3>/);
  assert.match(source, /if \(references\.length === 0\) \{\s*return null;/);
});

test("user-facing copy carries no retrieval jargon", async () => {
  // These words are meaningless to someone who just wants answers from their own files.
  const jargon = /\b(RAG|chunk|chunks|corpus|grounded|grounding|retrieval|reranker|embedding|ingestion|indexed)\b/i;

  const sources = await Promise.all(
    ["../src/lib/chatCore.js", "../src/app/page.tsx", "../src/components/AppShell.tsx"].map((file) =>
      readFile(new URL(file, import.meta.url), "utf8"),
    ),
  );

  for (const source of sources) {
    // Only user-visible strings matter; code identifiers and comments are exempt.
    const visible = [
      ...source.matchAll(/(?:>|"|')([^"'<>{}\n]{12,})(?:<|"|')/g),
    ].map((match) => match[1]);
    for (const text of visible) {
      assert.doesNotMatch(text, jargon, `user-facing copy contains jargon: ${text}`);
    }
  }
});

test("composer keeps a + upload entry point at every viewport", async () => {
  const source = await readFile(new URL("../src/app/page.tsx", import.meta.url), "utf8");
  const css = await readFile(new URL("../src/app/globals.css", import.meta.url), "utf8");

  assert.match(source, /className="composer-upload"/);
  assert.match(source, /href="\/documents"/);
  assert.match(source, /aria-label="Add a document"/);

  // It sits inside the composer frame, in the actions row along the bottom edge, with
  // Send at the far right. Same layout at every breakpoint.
  assert.match(source, /className="composer-actions"/);
  assert.match(css, /\.composer-upload \{/);
  assert.match(css, /\.composer-actions \{[^}]*justify-content: space-between;/s);
});

test("app shell exposes an accessible hamburger menu", async () => {
  const source = await readFile(new URL("../src/components/AppShell.tsx", import.meta.url), "utf8");

  assert.match(source, /aria-expanded=\{menuOpen\}/);
  assert.match(source, /aria-controls=\{MENU_ID\}/);
  assert.match(source, /aria-current=\{active \? "page" : undefined\}/);
  assert.match(source, /event\.key === "Escape"/);
  assert.match(source, /is-active/);
});

test("stylesheet collapses the sidebar into a drawer at the tablet breakpoint", async () => {
  const css = await readFile(new URL("../src/app/globals.css", import.meta.url), "utf8");

  assert.match(css, /@media \(max-width: 1024px\)/);
  assert.match(css, /\.app-sidebar\.is-open/);
  assert.match(css, /translateX\(-102%\)/);
  assert.match(css, /:focus-visible/);
});

test("chat page renders an honest notice when the model is degraded", async () => {
  const source = await readFile(new URL("../src/app/page.tsx", import.meta.url), "utf8");
  const css = await readFile(new URL("../src/app/globals.css", import.meta.url), "utf8");

  // The notice is what keeps a keyless fallback honest instead of silently worse.
  assert.match(source, /model_status\?\.mode === "degraded"/);
  assert.match(source, /className="model-notice"/);
  assert.match(source, /role="status"/);
  assert.match(css, /\.model-notice \{/);
});
