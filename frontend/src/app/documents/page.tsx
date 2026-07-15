"use client";

import { ChangeEvent, DragEvent, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  mergePolledDocument,
  optimisticRemove,
  requestJson,
  rollbackRemove,
  uploadDocumentWithProgress,
  validateUploadFile,
} from "../../lib/documentsCore";

type UploadLimits = {
  max_size_mb: number;
  max_pages: number;
  allowed_mime_types: string[];
};

type DocumentRow = {
  id: string;
  filename: string;
  status: "processing" | "indexed" | "failed";
  page_count: number | null;
  uploaded_at: string | null;
};

const EMPTY_LIMITS: UploadLimits = {
  max_size_mb: 0,
  max_pages: 0,
  allowed_mime_types: [],
};

const STATUS_LABELS: Record<DocumentRow["status"], string> = {
  processing: "Preparing",
  indexed: "Ready",
  failed: "Failed",
};

type Toast = { message: string; kind: "error" | "info" };

export default function DocumentsPage() {
  const [limits, setLimits] = useState<UploadLimits>(EMPTY_LIMITS);
  const [documents, setDocuments] = useState<DocumentRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<Toast | null>(null);
  const [uploadProgress, setUploadProgress] = useState<number | null>(null);
  const [dragActive, setDragActive] = useState(false);

  // A dismissible popup for upload feedback — friendlier than a static line, and it is where
  // an "only PDF files are supported" message lands when someone drops the wrong file type.
  useEffect(() => {
    if (!toast) {
      return;
    }
    const timer = window.setTimeout(() => setToast(null), 6000);
    return () => window.clearTimeout(timer);
  }, [toast]);

  const processingIds = useMemo(
    () => documents.filter((document) => document.status === "processing").map((document) => document.id),
    [documents],
  );

  useEffect(() => {
    requestJson("/config/upload-limits")
      .then((data) => setLimits(data as UploadLimits))
      .catch(() => setError("Could not load upload limits."));
    requestJson("/documents")
      .then((data) => setDocuments(data as DocumentRow[]))
      .catch(() => setError("Could not load documents."));
  }, []);

  useEffect(() => {
    if (processingIds.length === 0) {
      return;
    }
    const timer = window.setInterval(() => {
      processingIds.forEach((id) => {
        requestJson(`/documents/${id}`)
          .then((updated) => setDocuments((current) => mergePolledDocument(current, updated as DocumentRow)))
          .catch(() => setError("Could not refresh document status."));
      });
    }, 2000);
    return () => window.clearInterval(timer);
  }, [processingIds]);

  function handleFile(file: File | null) {
    if (!file) {
      return;
    }
    const validation = validateUploadFile(file, limits);
    if (!validation.ok) {
      // Pop a friendly notice (e.g. "Only PDF files can be uploaded.") rather than silently
      // ignoring a wrong-type or oversize file.
      setToast({ message: validation.reason ?? "That file can't be uploaded.", kind: "error" });
      return;
    }
    setError(null);
    setUploadProgress(0);
    uploadDocumentWithProgress(file, setUploadProgress)
      .then((created) => {
        setDocuments((current) => [created as DocumentRow, ...current]);
        setUploadProgress(null);
        setToast({ message: `"${(created as DocumentRow).filename}" added. Preparing it for chat…`, kind: "info" });
      })
      .catch(() => {
        setToast({
          message: "Upload failed. Please check the file is a PDF within the size and page limits, then try again.",
          kind: "error",
        });
        setUploadProgress(null);
      });
  }

  function onDrop(event: DragEvent<HTMLLabelElement>) {
    event.preventDefault();
    setDragActive(false);
    handleFile(event.dataTransfer.files.item(0));
  }

  function onFileChange(event: ChangeEvent<HTMLInputElement>) {
    handleFile(event.target.files?.item(0) ?? null);
    event.target.value = "";
  }

  function deleteDocument(document: DocumentRow) {
    if (!window.confirm(`Delete ${document.filename}?`)) {
      return;
    }
    setDocuments((current) => optimisticRemove(current, document.id));
    requestJson(`/documents/${document.id}`, { method: "DELETE" }).catch(() => {
      setDocuments((current) => rollbackRemove(current, document));
      setError("Delete failed.");
    });
  }

  return (
    <section className="documents-shell" aria-label="Document manager">
      <header className="documents-header">
        {/* Always visible, at every viewport: on tablet/mobile the sidebar is behind a
            hamburger, so without this the way back to chat is hidden behind a menu. */}
        <Link href="/" className="back-to-chat">
          <span aria-hidden="true">←</span> Back to chat
        </Link>
        <h1>My documents</h1>
        <p>Add a PDF here, then ask questions about it in chat. Only PDF files are supported.</p>
      </header>

      <label
        className={`documents-dropzone${dragActive ? " is-active" : ""}`}
        onDragOver={(event) => {
          event.preventDefault();
          setDragActive(true);
        }}
        onDragLeave={() => setDragActive(false)}
        onDrop={onDrop}
      >
        <input aria-label="Upload PDF" type="file" accept="application/pdf" onChange={onFileChange} />
        <span>Drop a PDF here or choose a file</span>
        <small>
          Only PDF files are supported, up to {limits.max_size_mb || "..."} MB and {limits.max_pages || "..."} pages
        </small>
      </label>

      {toast ? (
        <div className={`upload-toast upload-toast-${toast.kind}`} role="alert" aria-live="assertive">
          <span>{toast.message}</span>
          <button type="button" aria-label="Dismiss notification" onClick={() => setToast(null)}>
            ×
          </button>
        </div>
      ) : null}

      {uploadProgress !== null ? (
        <div className="upload-progress" aria-label="Upload progress">
          <span style={{ width: `${uploadProgress}%` }} />
          <strong>{uploadProgress}%</strong>
        </div>
      ) : null}

      {error ? <p className="documents-error">{error}</p> : null}

      <section className="documents-table-band">
        {documents.length === 0 ? (
          <div className="documents-empty">
            <h2>No documents yet</h2>
            <p>Add a PDF above to start asking questions about it.</p>
          </div>
        ) : (
          <table className="documents-table">
            <thead>
              <tr>
                <th>Filename</th>
                <th>Uploaded</th>
                <th>Pages</th>
                <th>Status</th>
                <th aria-label="Actions" />
              </tr>
            </thead>
            <tbody>
              {documents.map((document) => (
                <tr key={document.id} className={document.status === "failed" ? "is-failed" : ""}>
                  <td>{document.filename}</td>
                  <td>{document.uploaded_at ? new Date(document.uploaded_at).toLocaleString() : "Pending"}</td>
                  <td>{document.page_count ?? "..."}</td>
                  <td>
                    {/* The API status values are technical; the user sees plain words. */}
                    <span className={`status-pill status-${document.status}`}>
                      {STATUS_LABELS[document.status]}
                    </span>
                  </td>
                  <td>
                    <button type="button" onClick={() => deleteDocument(document)}>
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </section>
  );
}
