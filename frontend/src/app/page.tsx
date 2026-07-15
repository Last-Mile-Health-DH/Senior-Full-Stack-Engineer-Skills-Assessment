"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  CHAT_ERROR_MESSAGE,
  WELCOME_MESSAGE,
  parseAnswerBlocks,
  postChat,
  referenceLines,
  splitCitationMarkers,
} from "../lib/chatCore";

type Citation = {
  number: number;
  document_title: string;
  page_number: number | null;
  section_path: string | null;
  reference: string;
};

type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations: Citation[];
  isError?: boolean;
};

type ModelStatus = {
  mode: "full" | "degraded";
  provider: string | null;
  model: string | null;
  notice: string | null;
};

type ChatResponse = {
  session_id: string;
  answer: string;
  citations?: Citation[];
  references_heading?: string;
  cache_status: string;
  output_filter_status: string;
  model_status?: ModelStatus;
};

const sampleQuestions = [
  "What dose is recommended for a child?",
  "Summarize the main recommendation.",
  "What does my document say about follow-up?",
];

export default function ChatPage() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isSending, setIsSending] = useState(false);
  // When no model key is configured the answer is extracted from the documents rather than
  // written. Saying so is the difference between an honest fallback and a product that
  // looks like it works but quietly answers worse.
  const [notice, setNotice] = useState<string | null>(null);
  const transcriptEndRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    transcriptEndRef.current?.scrollIntoView({ block: "end" });
  }, [messages, isSending]);

  async function submitQuestion(event?: FormEvent<HTMLFormElement>, presetQuestion?: string) {
    event?.preventDefault();
    const question = (presetQuestion ?? input).trim();
    // The in-flight guard is what stops a double-send from creating a duplicate turn.
    if (!question || isSending) {
      return;
    }

    setInput("");
    setIsSending(true);
    setMessages((current) => [
      ...current,
      { id: crypto.randomUUID(), role: "user", content: question, citations: [] },
    ]);

    try {
      const response: ChatResponse = await postChat(question, sessionId);
      setSessionId(response.session_id);
      setNotice(
        response.model_status?.mode === "degraded"
          ? response.model_status.notice ?? null
          : null,
      );
      setMessages((current) => [
        ...current,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          content: response.answer,
          citations: response.citations ?? [],
        },
      ]);
    } catch {
      setMessages((current) => [
        ...current,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          content: CHAT_ERROR_MESSAGE,
          citations: [],
          isError: true,
        },
      ]);
    } finally {
      setIsSending(false);
    }
  }

  return (
    <section className="chat-surface" aria-label="Chat with your documents">
      {notice ? (
        <p className="model-notice" role="status">
          <span aria-hidden="true">⚠</span> {notice}
        </p>
      ) : null}

      <div className="chat-transcript" role="log" aria-live="polite">
        {messages.length === 0 ? (
          <div className="chat-welcome">
            <h2>Ask your documents</h2>
            <p>{WELCOME_MESSAGE}</p>
            <p className="chat-welcome-hint">
              No documents yet? Use <strong>+</strong> to add one.
            </p>
          </div>
        ) : null}

        {messages.map((message) => (
          <article key={message.id} className={`chat-message message-${message.role}`}>
            <p className="message-label">{message.role === "user" ? "You" : "Assistant"}</p>
            {message.role === "user" ? (
              <p className="message-body">{message.content}</p>
            ) : (
              <AnswerBody content={message.content} isError={message.isError} />
            )}
            <ReferenceList citations={message.citations} />
          </article>
        ))}

        {isSending ? <ThinkingRow /> : null}
        <div ref={transcriptEndRef} />
      </div>

      {messages.length === 0 ? (
        <div className="prompt-row" aria-label="Suggested questions">
          {sampleQuestions.map((question) => (
            <button
              key={question}
              type="button"
              disabled={isSending}
              onClick={() => submitQuestion(undefined, question)}
            >
              {question}
            </button>
          ))}
        </div>
      ) : null}

      {/* The composer is one framed surface: the textarea sits on top, and the controls
          sit inside that same frame along its bottom edge — "+" at the left, Send at the
          right. The textarea itself is borderless so the frame reads as the input. */}
      <form className="chat-composer" onSubmit={submitQuestion}>
        <label htmlFor="chat-input">Ask a question about your documents</label>
        <textarea
          id="chat-input"
          value={input}
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              void submitQuestion();
            }
          }}
          placeholder="Ask a question about your documents..."
          rows={2}
        />
        <div className="composer-actions">
          <Link
            href="/documents"
            className="composer-upload"
            title="Add a document"
            aria-label="Add a document"
          >
            <span aria-hidden="true">+</span>
          </Link>
          <button type="submit" disabled={isSending || !input.trim()}>
            {isSending ? "Sending…" : "Send"}
          </button>
        </div>
      </form>
    </section>
  );
}

/** The assistant row shown from the moment Send is pressed until the answer lands. */
function ThinkingRow() {
  return (
    <article className="chat-message message-assistant is-thinking" aria-label="Assistant is working">
      <p className="message-label">Assistant</p>
      <p className="thinking-body">
        <span className="thinking-dots" aria-hidden="true">
          <span />
          <span />
          <span />
        </span>
        <span role="status">Searching your documents…</span>
      </p>
    </article>
  );
}

function AnswerBody({ content, isError }: { content: string; isError?: boolean }) {
  const blocks = parseAnswerBlocks(content);
  return (
    <div className={`message-body${isError ? " is-error" : ""}`}>
      {blocks.map((block, index) =>
        block.type === "bullets" ? (
          <ul key={index}>
            {block.items.map((item: string, itemIndex: number) => (
              <li key={itemIndex}>
                <CitedText text={item} />
              </li>
            ))}
          </ul>
        ) : (
          <p key={index}>
            <CitedText text={block.text} />
          </p>
        ),
      )}
    </div>
  );
}

type Segment = { type: "text" | "citation"; value: string; numbers?: number[] };
type ReferenceLine = { number: number; text: string };

/** Renders superscript citation markers small and linked to their reference entry. */
function CitedText({ text }: { text: string }) {
  const segments: Segment[] = splitCitationMarkers(text);
  return (
    <>
      {segments.map((segment, index) =>
        segment.type === "citation" ? (
          <sup key={index} className="citation-marker">
            {(segment.numbers ?? []).map((number, markerIndex) => (
              <a key={markerIndex} href={`#reference-${number}`}>
                {number}
              </a>
            ))}
          </sup>
        ) : (
          <span key={index}>{segment.value}</span>
        ),
      )}
    </>
  );
}

function ReferenceList({ citations }: { citations: Citation[] }) {
  const references: ReferenceLine[] = referenceLines(citations);
  // A refusal or no-answer has no citations, and must not render an empty list.
  if (references.length === 0) {
    return null;
  }
  return (
    <div className="reference-block">
      <h3>Sources</h3>
      <ol>
        {references.map((reference) => (
          <li key={reference.number} id={`reference-${reference.number}`}>
            {reference.text.replace(/^\d+\.\s*/, "")}
          </li>
        ))}
      </ol>
    </div>
  );
}
