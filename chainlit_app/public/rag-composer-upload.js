/**
 * Places a "+" upload button INSIDE the Chainlit composer, at its bottom-left corner,
 * matching the Next.js chat surface.
 *
 * Chainlit gives its composer a stable element id (`message-composer`, alongside
 * `chat-input` and `chat-submit`). Those ids are the hook used here — not generated class
 * names, which would break on any Chainlit rebuild. If the id ever disappears the button
 * simply is not mounted; nothing else on the page breaks, and the welcome message still
 * links to the upload page.
 *
 * Chainlit is a single-page app that re-renders its root, so the mount is re-asserted on
 * DOM mutations.
 */
(function mountComposerUploadButton() {
  var BUTTON_ID = "rag-upload-btn";
  var COMPOSER_ID = "message-composer";
  // Overridable for a non-default frontend host.
  var uploadUrl = (window.RAG_DOCUMENTS_URL || "http://localhost:3000/documents").replace(/\/+$/, "");

  function mount() {
    var composer = document.getElementById(COMPOSER_ID);
    if (!composer || document.getElementById(BUTTON_ID)) {
      return;
    }

    var link = document.createElement("a");
    link.id = BUTTON_ID;
    link.href = uploadUrl;
    link.target = "_blank";
    link.rel = "noreferrer";
    link.title = "Add a document";
    link.setAttribute("aria-label", "Add a document");
    link.textContent = "+";

    composer.appendChild(link);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", mount);
  } else {
    mount();
  }

  new MutationObserver(mount).observe(document.documentElement, {
    childList: true,
    subtree: true,
  });
})();
