import { Page, expect, test } from "@playwright/test";

const chainlitBaseURL = process.env.PLAYWRIGHT_CHAINLIT_BASE_URL ?? "http://localhost:8000";

const VIEWPORTS = [
  { name: "mobile", width: 375, height: 812 },
  { name: "tablet-portrait", width: 768, height: 1024 },
  { name: "tablet-landscape", width: 1024, height: 768 },
  { name: "desktop", width: 1440, height: 900 },
];

/** A cited answer, mocked at the API boundary so UI rendering is deterministic. */
const CITED_ANSWER = {
  session_id: "00000000-0000-0000-0000-000000000001",
  answer: "The child dose is 5 ml.¹ Adults receive 10 ml.²",
  citations: [
    {
      number: 1,
      chunk_id: "00000000-0000-0000-0000-0000000000a1",
      document_id: "00000000-0000-0000-0000-0000000000d1",
      document_title: "Oral Rehydration Protocol",
      document_filename: "oral_rehydration_protocol.pdf",
      page_number: 1,
      section_path: null,
      snippet: "Child dose is 5 ml.",
      reference: "1. Oral Rehydration Protocol, p. 1.",
    },
    {
      number: 2,
      chunk_id: "00000000-0000-0000-0000-0000000000a2",
      document_id: "00000000-0000-0000-0000-0000000000d2",
      document_title: "WHO Guidance 2024",
      document_filename: "who_guidance_2024.pdf",
      page_number: 14,
      section_path: null,
      snippet: "Adults receive 10 ml.",
      reference: "2. WHO Guidance 2024, p. 14.",
    },
  ],
  cache_status: "miss",
  output_filter_status: "passed",
  source_chunk_ids: [],
  query_audit_log_id: "00000000-0000-0000-0000-0000000000f1",
};

const NO_ANSWER = {
  ...CITED_ANSWER,
  answer:
    "I could not find that in your documents. Try uploading the document that covers it, or ask about a specific section.",
  citations: [],
};

async function mockChat(page: Page, body: unknown, delayMs = 0) {
  await page.route("**/api/v1/chat", async (route) => {
    if (delayMs) {
      await new Promise((resolve) => setTimeout(resolve, delayMs));
    }
    await route.fulfill({ json: body });
  });
}

test.describe("navigation and active state", () => {
  test("the current page shows active state and external links never do", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/");

    const chatLink = page.getByRole("link", { name: "Chat", exact: true });
    const documentsLink = page.getByRole("link", { name: "My documents" });

    await expect(chatLink).toHaveAttribute("aria-current", "page");
    await expect(documentsLink).not.toHaveAttribute("aria-current", "page");

    await documentsLink.click();
    await expect(page).toHaveURL(/\/documents$/);
    await expect(page.getByRole("link", { name: "My documents" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    await expect(page.getByRole("link", { name: "Chat", exact: true })).not.toHaveAttribute(
      "aria-current",
      "page",
    );

    // An external service cannot be known to be "current", so it must never claim it.
    const chainlitLink = page.getByRole("link", { name: /Chainlit chat/ });
    await expect(chainlitLink).not.toHaveAttribute("aria-current", "page");
    await expect(chainlitLink).toHaveAttribute("href", chainlitBaseURL);
  });
});

test.describe("responsive sidebar", () => {
  for (const viewport of [VIEWPORTS[0], VIEWPORTS[1], VIEWPORTS[2]]) {
    test(`sidebar collapses into a hamburger at ${viewport.width}px`, async ({ page }) => {
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await page.goto("/");

      const toggle = page.getByRole("button", { name: /navigation menu/i });
      const sidebar = page.locator("#primary-navigation");

      await expect(toggle).toBeVisible();
      await expect(toggle).toHaveAttribute("aria-expanded", "false");
      await expect(toggle).toHaveAttribute("aria-controls", "primary-navigation");
      await expect(sidebar).not.toBeInViewport();

      await toggle.click();
      await expect(toggle).toHaveAttribute("aria-expanded", "true");
      await expect(sidebar).toBeInViewport();

      // Escape dismisses the overlay.
      await page.keyboard.press("Escape");
      await expect(toggle).toHaveAttribute("aria-expanded", "false");
      await expect(sidebar).not.toBeInViewport();

      // Selecting an internal link closes the menu rather than leaving it over the page.
      await toggle.click();
      await page.getByRole("link", { name: "My documents" }).click();
      await expect(page).toHaveURL(/\/documents$/);
      await expect(toggle).toHaveAttribute("aria-expanded", "false");
    });
  }

  test("the sidebar is permanent and the hamburger is hidden at 1440px", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/");

    await expect(page.locator("#primary-navigation")).toBeVisible();
    await expect(page.getByRole("button", { name: /navigation menu/i })).toBeHidden();
  });
});

test.describe("prompt submission loading state", () => {
  test("a thinking row appears immediately and is replaced by the answer", async ({ page }) => {
    await mockChat(page, CITED_ANSWER, 1500);
    await page.goto("/");

    await page.getByLabel("Ask a question about your documents").fill("what is the child dose?");
    await page.getByRole("button", { name: "Send" }).click();

    // Feedback is visible while the request is still in flight.
    const thinking = page.getByLabel("Assistant is working");
    await expect(thinking).toBeVisible();
    await expect(page.getByText("Searching your documents…")).toBeVisible();

    // The same prompt cannot be submitted twice while it is in flight.
    await expect(page.getByRole("button", { name: "Sending…" })).toBeDisabled();

    await expect(page.getByText("The child dose is 5 ml.")).toBeVisible();
    await expect(thinking).toBeHidden();
  });
});

test.describe("answer presentation", () => {
  test("a cited answer renders superscripts and a Sources list", async ({ page }) => {
    await mockChat(page, CITED_ANSWER);
    await page.goto("/");

    await page.getByLabel("Ask a question about your documents").fill("what is the child dose?");
    await page.getByRole("button", { name: "Send" }).click();

    const answer = page.locator(".message-assistant").last();
    await expect(answer).toContainText("The child dose is 5 ml.");
    // Superscripts are rendered small and linked to their entry in the source list.
    await expect(answer.locator("sup.citation-marker").first()).toBeVisible();
    await expect(answer.locator('sup.citation-marker a[href="#reference-1"]')).toHaveText("1");

    await expect(answer.getByRole("heading", { name: "Sources" })).toBeVisible();
    await expect(answer.locator("#reference-1")).toContainText("Oral Rehydration Protocol, p. 1.");
    await expect(answer.locator("#reference-2")).toContainText("WHO Guidance 2024, p. 14.");

    // The answer must never open with a document name.
    await expect(answer.locator(".message-body p").first()).not.toContainText(".pdf");
  });

  test("a no-answer is concise and shows no sources", async ({ page }) => {
    await mockChat(page, NO_ANSWER);
    await page.goto("/");

    await page.getByLabel("Ask a question about your documents").fill("what about rabies?");
    await page.getByRole("button", { name: "Send" }).click();

    const answer = page.locator(".message-assistant").last();
    await expect(answer).toContainText("I could not find that in your documents.");
    // An empty reference list must not be rendered.
    await expect(answer.getByRole("heading", { name: "Sources" })).toHaveCount(0);
    await expect(answer.locator("sup.citation-marker")).toHaveCount(0);
  });
});

test.describe("upload entry point and layout integrity", () => {
  for (const viewport of VIEWPORTS) {
    test(`the + upload button is reachable and nothing overflows at ${viewport.width}x${viewport.height}`, async ({
      page,
    }, testInfo) => {
      await mockChat(page, CITED_ANSWER);
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await page.goto("/");

      const upload = page.getByRole("link", { name: "Add a document" });
      await expect(upload).toBeVisible();
      await expect(upload).toHaveAttribute("href", "/documents");

      // No horizontal scrolling at any supported width.
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(overflow).toBeLessThanOrEqual(1);

      // The composer stays fully on screen; the upload button must not cover it.
      const send = page.getByRole("button", { name: "Send" });
      const sendBox = await send.boundingBox();
      const uploadBox = await upload.boundingBox();
      expect(sendBox).not.toBeNull();
      expect(uploadBox).not.toBeNull();
      expect(sendBox!.y + sendBox!.height).toBeLessThanOrEqual(viewport.height + 1);
      const overlaps =
        sendBox!.x < uploadBox!.x + uploadBox!.width &&
        uploadBox!.x < sendBox!.x + sendBox!.width &&
        sendBox!.y < uploadBox!.y + uploadBox!.height &&
        uploadBox!.y < sendBox!.y + sendBox!.height;
      expect(overlaps).toBe(false);

      await testInfo.attach(`nextjs-${viewport.name}`, {
        body: await page.screenshot({ fullPage: false }),
        contentType: "image/png",
      });
    });

    test(`the documents page offers a visible way back to chat at ${viewport.width}x${viewport.height}`, async ({
      page,
    }) => {
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await page.goto("/documents");

      // Below 1024px the sidebar is behind a hamburger, so the page itself must carry the
      // route back to chat rather than relying on the menu.
      const back = page.getByRole("link", { name: /Back to chat/i });
      await expect(back).toBeVisible();
      await expect(back).toBeInViewport();

      await back.click();
      await expect(page).toHaveURL(new RegExp(`${new URL(page.url()).origin}/?$`));
      await expect(page.getByLabel("Ask a question about your documents")).toBeVisible();
    });

    test(`Chainlit shows the + upload button at ${viewport.width}x${viewport.height}`, async ({
      page,
    }, testInfo) => {
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await page.goto(chainlitBaseURL);

      // Inside the composer frame, bottom-left, matching the Next.js surface.
      const upload = page.locator("#rag-upload-btn");
      await expect(upload).toBeVisible({ timeout: 30_000 });
      await expect(upload).toHaveAttribute("href", /\/documents$/);

      const composer = page.locator("#message-composer");
      const composerBox = await composer.boundingBox();
      const uploadBox = await upload.boundingBox();
      expect(composerBox).not.toBeNull();
      expect(uploadBox).not.toBeNull();

      // Contained within the input frame, not floating outside it.
      expect(uploadBox!.x).toBeGreaterThanOrEqual(composerBox!.x - 1);
      expect(uploadBox!.y).toBeGreaterThanOrEqual(composerBox!.y - 1);
      expect(uploadBox!.x + uploadBox!.width).toBeLessThanOrEqual(
        composerBox!.x + composerBox!.width + 1,
      );
      expect(uploadBox!.y + uploadBox!.height).toBeLessThanOrEqual(
        composerBox!.y + composerBox!.height + 1,
      );
      // Bottom-left: in the left half, and in the lower half, of the frame.
      expect(uploadBox!.x - composerBox!.x).toBeLessThan(composerBox!.width / 2);
      expect(uploadBox!.y - composerBox!.y).toBeGreaterThan(composerBox!.height / 2 - 20);

      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(overflow).toBeLessThanOrEqual(1);

      await testInfo.attach(`chainlit-${viewport.name}`, {
        body: await page.screenshot({ fullPage: false }),
        contentType: "image/png",
      });
    });
  }
});
