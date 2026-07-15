const DEFAULT_API_BASE_URL = "http://localhost:6100/api/v1";

export function getApiBaseUrl() {
  return process.env.NEXT_PUBLIC_API_BASE_URL || DEFAULT_API_BASE_URL;
}

export function validateUploadFile(file, limits) {
  if (!limits.allowed_mime_types.length || !limits.max_size_mb) {
    return { ok: false, reason: "Upload limits are still loading." };
  }
  if (!limits.allowed_mime_types.includes(file.type)) {
    return { ok: false, reason: "Only PDF files can be uploaded." };
  }
  const maxBytes = limits.max_size_mb * 1024 * 1024;
  if (file.size > maxBytes) {
    return { ok: false, reason: `File exceeds ${limits.max_size_mb} MB.` };
  }
  return { ok: true, reason: null };
}

export async function requestJson(path, options = {}) {
  const response = await fetch(`${getApiBaseUrl()}${path}`, {
    ...options,
    headers: options.headers || {},
  });
  return parseJsonResponse(response);
}

async function parseJsonResponse(response) {
  if (!response.ok) {
    throw new Error(`Request failed with ${response.status}`);
  }
  if (response.status === 204) {
    return null;
  }
  return response.json();
}

export function uploadDocumentWithProgress(file, onProgress, xhrFactory = () => new XMLHttpRequest()) {
  return new Promise((resolve, reject) => {
    const xhr = xhrFactory();
    const form = new FormData();
    form.append("file", file);
    xhr.open("POST", `${getApiBaseUrl()}/documents`);
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) {
        onProgress(Math.round((event.loaded / event.total) * 100));
      }
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(JSON.parse(xhr.responseText));
      } else {
        reject(new Error(`Upload failed with ${xhr.status}`));
      }
    };
    xhr.onerror = () => reject(new Error("Upload failed"));
    xhr.send(form);
  });
}

export function mergePolledDocument(documents, updated) {
  return documents.map((document) => (document.id === updated.id ? updated : document));
}

export function optimisticRemove(documents, documentId) {
  return documents.filter((document) => document.id !== documentId);
}

export function rollbackRemove(documents, removed) {
  return [removed, ...documents].sort((a, b) => String(b.uploaded_at || "").localeCompare(String(a.uploaded_at || "")));
}
