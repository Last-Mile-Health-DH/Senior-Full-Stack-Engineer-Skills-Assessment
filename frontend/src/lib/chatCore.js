// Explicit extension: this module is also loaded directly by the Node test runner,
// which does not resolve extensionless ESM specifiers the way the bundler does.
import { getApiBaseUrl } from "./documentsCore.js";

// All user-facing copy lives here. It is read by people who simply want answers from
// their own documents, so it never mentions retrieval, chunks, indexing, or grounding.
export const CHAT_ERROR_MESSAGE =
  "I could not reach the chat service. Please check that it is running, then try again. " +
  "If you just ran the test suite, ask the developer to restore the database tables that pytest may have dropped " +
  "(run `alembic upgrade head` and restart the backend).";

export const WELCOME_MESSAGE =
  "Ask a question about the documents you have uploaded. Every answer comes from those documents, and shows you the page each fact came from.";

// Internal routes own active state. External services are reachable but this app
// cannot know whether the user is currently on them, so they never claim active.
export const INTERNAL_NAV = [
  { href: "/", label: "Chat" },
  { href: "/documents", label: "My documents" },
];

export const EXTERNAL_NAV = [
  { href: "http://localhost:8000", label: "Chainlit chat" },
  { href: "http://localhost:6100/docs", label: "API docs" },
  { href: "http://localhost:6100/health", label: "Service health" },
];

const SUPERSCRIPTS = "⁰¹²³⁴⁵⁶⁷⁸⁹";
const SUPERSCRIPT_RUN = new RegExp(`[${SUPERSCRIPTS}]+`, "g");

export function isActivePath(pathname, href) {
  if (typeof pathname !== "string" || !pathname) {
    return false;
  }
  if (href === "/") {
    return pathname === "/";
  }
  return pathname === href || pathname.startsWith(`${href}/`);
}

export async function postChat(message, sessionId, fetchImpl = fetch) {
  const response = await fetchImpl(`${getApiBaseUrl()}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      message,
      ...(sessionId ? { session_id: sessionId } : {}),
    }),
  });
  if (!response.ok) {
    throw new Error(`Chat failed with ${response.status}`);
  }
  return response.json();
}

/**
 * Split a presented answer into paragraph and bullet blocks.
 *
 * The backend already applied every writing-style rule, so this only recovers the
 * structure it emitted. It never interprets HTML, so a document cannot inject markup
 * through an answer.
 */
export function parseAnswerBlocks(answer) {
  const blocks = [];
  let paragraph = [];
  let bullets = [];

  const flushParagraph = () => {
    if (paragraph.length) {
      blocks.push({ type: "paragraph", text: paragraph.join(" ") });
      paragraph = [];
    }
  };
  const flushBullets = () => {
    if (bullets.length) {
      blocks.push({ type: "bullets", items: bullets });
      bullets = [];
    }
  };

  for (const rawLine of String(answer || "").split("\n")) {
    const line = rawLine.trim();
    if (!line) {
      flushBullets();
      flushParagraph();
      continue;
    }
    const bullet = line.match(/^(?:[-*•]\s+|\d+[.)]\s+)(.*)$/);
    if (bullet) {
      flushParagraph();
      bullets.push(bullet[1]);
      continue;
    }
    flushBullets();
    paragraph.push(line);
  }
  flushBullets();
  flushParagraph();
  return blocks;
}

/**
 * Split text into plain runs and superscript citation runs so the UI can render the
 * markers small and link them to their reference entries.
 *
 * @typedef {{ type: "text" | "citation", value: string, numbers?: number[] }} AnswerSegment
 * @param {string} text
 * @returns {AnswerSegment[]}
 */
export function splitCitationMarkers(text) {
  /** @type {AnswerSegment[]} */
  const segments = [];
  let cursor = 0;
  const source = String(text || "");

  for (const match of source.matchAll(SUPERSCRIPT_RUN)) {
    if (match.index > cursor) {
      segments.push({ type: "text", value: source.slice(cursor, match.index) });
    }
    segments.push({
      type: "citation",
      value: match[0],
      numbers: [...match[0]].map((character) => SUPERSCRIPTS.indexOf(character)),
    });
    cursor = match.index + match[0].length;
  }
  if (cursor < source.length) {
    segments.push({ type: "text", value: source.slice(cursor) });
  }
  return segments;
}

/**
 * An answer with no citations must not render an empty reference list.
 *
 * @param {Array<{number: number, reference?: string}> | undefined | null} citations
 * @returns {Array<{ number: number, text: string }>}
 */
export function referenceLines(citations) {
  return (citations || [])
    .filter((citation) => citation && citation.reference)
    .map((citation) => ({ number: citation.number, text: citation.reference }));
}
