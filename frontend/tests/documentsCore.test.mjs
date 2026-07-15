import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  mergePolledDocument,
  optimisticRemove,
  requestJson,
  rollbackRemove,
  uploadDocumentWithProgress,
  validateUploadFile,
} from "../src/lib/documentsCore.js";

const limits = {
  max_size_mb: 1,
  max_pages: 300,
  allowed_mime_types: ["application/pdf"],
};

test("/documents page contains dropzone and empty state copy", async () => {
  const source = await readFile(new URL("../src/app/documents/page.tsx", import.meta.url), "utf8");
  assert.match(source, /documents-dropzone/);
  assert.match(source, /No documents yet/);
});

test("/documents page always offers a way back to chat", async () => {
  const source = await readFile(new URL("../src/app/documents/page.tsx", import.meta.url), "utf8");
  const css = await readFile(new URL("../src/app/globals.css", import.meta.url), "utf8");

  assert.match(source, /className="back-to-chat"/);
  assert.match(source, /Back to chat/);
  assert.match(source, /<Link href="\/"/);

  // It lives in the page header, not the sidebar, so it survives the hamburger collapse
  // at tablet/mobile widths where the sidebar is hidden behind a menu.
  assert.match(css, /\.back-to-chat \{/);
  assert.doesNotMatch(css, /\.back-to-chat[^{]*\{[^}]*display:\s*none/);
});

test("/documents page states PDF-only support and pops a toast on a rejected upload", async () => {
  const source = await readFile(new URL("../src/app/documents/page.tsx", import.meta.url), "utf8");
  const css = await readFile(new URL("../src/app/globals.css", import.meta.url), "utf8");

  // Friendly, explicit copy that only PDFs are supported.
  assert.match(source, /Only PDF files are supported/);
  // A rejected file surfaces the reason through the dismissible toast, not a silent drop.
  assert.match(source, /setToast\(\{ message: validation\.reason/);
  assert.match(source, /className=\{`upload-toast upload-toast-\$\{toast\.kind\}`\}/);
  assert.match(source, /role="alert"/);
  assert.match(css, /\.upload-toast \{/);
});

test("upload limits drive MIME and size validation before network", () => {
  const wrongMime = { type: "text/plain", size: 1 };
  const oversized = { type: "application/pdf", size: 2 * 1024 * 1024 };
  assert.deepEqual(validateUploadFile(wrongMime, limits), {
    ok: false,
    reason: "Only PDF files can be uploaded.",
  });
  assert.deepEqual(validateUploadFile(oversized, limits), {
    ok: false,
    reason: "File exceeds 1 MB.",
  });
});

test("requestJson calls document endpoints without auth session bootstrap", async () => {
  const originalFetch = global.fetch;
  const calls = [];

  global.fetch = async (url, options = {}) => {
    calls.push({ url: String(url), headers: options.headers || {} });
    return {
      ok: true,
      status: 200,
      json: async () => [{ id: "doc-1", status: "indexed" }],
    };
  };

  try {
    const documents = await requestJson("/documents");
    assert.deepEqual(documents, [{ id: "doc-1", status: "indexed" }]);
    assert.equal(calls.length, 1);
    assert.equal(calls[0].url, "http://localhost:6100/api/v1/documents");
    assert.deepEqual(calls[0].headers, {});
  } finally {
    global.fetch = originalFetch;
  }
});

test("upload progress indicator receives XHR progress events", async () => {
  const progress = [];
  const headers = [];
  class FakeXHR {
    upload = {};
    status = 202;
    responseText = JSON.stringify({ id: "1", status: "processing" });
    open() {}
    setRequestHeader(key, value) {
      headers.push([key, value]);
    }
    send() {
      this.upload.onprogress({ lengthComputable: true, loaded: 50, total: 100 });
      this.onload();
    }
  }
  const result = await uploadDocumentWithProgress(
    new Blob(["%PDF"], { type: "application/pdf" }),
    (value) => progress.push(value),
    () => new FakeXHR(),
  );
  assert.deepEqual(progress, [50]);
  assert.deepEqual(headers, []);
  assert.equal(result.status, "processing");
});

test("processing row transitions to indexed through polling merge", () => {
  const documents = [{ id: "1", filename: "a.pdf", status: "processing" }];
  const updated = { id: "1", filename: "a.pdf", status: "indexed" };
  assert.deepEqual(mergePolledDocument(documents, updated), [updated]);
});

test("failed status remains visible through polling merge", () => {
  const documents = [{ id: "1", filename: "a.pdf", status: "processing" }];
  const updated = { id: "1", filename: "a.pdf", status: "failed" };
  assert.equal(mergePolledDocument(documents, updated)[0].status, "failed");
});

test("delete removes optimistically and rolls back on failure", () => {
  const removed = { id: "1", filename: "a.pdf", uploaded_at: "2026-01-01T00:00:00Z" };
  const remaining = [{ id: "2", filename: "b.pdf", uploaded_at: "2026-01-02T00:00:00Z" }];
  assert.deepEqual(optimisticRemove([removed, ...remaining], "1"), remaining);
  assert.deepEqual(rollbackRemove(remaining, removed).map((row) => row.id), ["2", "1"]);
});
