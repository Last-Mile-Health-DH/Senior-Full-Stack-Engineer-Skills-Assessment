import { expect, test } from "@playwright/test";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";

const apiBaseURL = process.env.PLAYWRIGHT_API_BASE_URL ?? "http://localhost:6100/api/v1";
const chainlitBaseURL = process.env.PLAYWRIGHT_CHAINLIT_BASE_URL ?? "http://localhost:8000";

test("uploads table PDF, waits for indexing, and answers through Chainlit with a cited page", async ({
  page,
  request,
}, testInfo) => {
  const documentsResponse = await request.get(`${apiBaseURL}/documents`);
  expect(documentsResponse.ok()).toBeTruthy();

  const fixturePath = testInfo.outputPath("table-fixture.pdf");
  writeTableFixturePdf(fixturePath);

  await page.goto("/documents");
  await expect(page.getByRole("heading", { name: "Documents" })).toBeVisible();
  await expect(page.getByText(/PDF only, up to \d+ MB/)).toBeVisible();

  await page.getByLabel("Upload PDF").setInputFiles(fixturePath);
  const uploadedRow = page.locator("tr", { hasText: "table-fixture.pdf" });
  await expect(uploadedRow).toBeVisible();
  await expect(uploadedRow.getByText("indexed")).toBeVisible({ timeout: 180_000 });

  await page.goto(chainlitBaseURL);
  await expect(page.locator("body")).toContainText(/document-grounded question/i);

  const chatInput = page.locator("textarea").last();
  await expect(chatInput).toBeVisible({ timeout: 30_000 });
  await chatInput.fill("According to the Oral Rehydration Protocol table, what dose is listed for Child?");
  const sendButton = page.getByRole("button", { name: /send/i }).last();
  if ((await sendButton.count()) > 0) {
    await sendButton.click();
  } else {
    await chatInput.press("Enter");
  }

  await expect(page.getByText(/5 ml/i)).toBeVisible({ timeout: 90_000 });
  await expect(page.getByText(/p\. 1/i)).toBeVisible();
});

function writeTableFixturePdf(path: string) {
  mkdirSync(dirname(path), { recursive: true });
  const stream = [
    "BT /F1 18 Tf 72 735 Td (Oral Rehydration Protocol) Tj ET",
    "BT /F1 11 Tf 72 710 Td (This page contains a table used for grounded chat verification.) Tj ET",
    "0.75 w",
    "72 675 m 440 675 l S",
    "72 650 m 440 650 l S",
    "72 625 m 440 625 l S",
    "72 600 m 440 600 l S",
    "72 675 m 72 600 l S",
    "220 675 m 220 600 l S",
    "340 675 m 340 600 l S",
    "440 675 m 440 600 l S",
    "BT /F1 10 Tf 82 660 Td (Age group) Tj ET",
    "BT /F1 10 Tf 230 660 Td (Dose) Tj ET",
    "BT /F1 10 Tf 350 660 Td (Page) Tj ET",
    "BT /F1 10 Tf 82 635 Td (Child) Tj ET",
    "BT /F1 10 Tf 230 635 Td (5 ml) Tj ET",
    "BT /F1 10 Tf 350 635 Td (1) Tj ET",
    "BT /F1 10 Tf 82 610 Td (Adult) Tj ET",
    "BT /F1 10 Tf 230 610 Td (10 ml) Tj ET",
    "BT /F1 10 Tf 350 610 Td (1) Tj ET",
  ].join("\n");

  const objects = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
    `<< /Length ${Buffer.byteLength(stream)} >>\nstream\n${stream}\nendstream`,
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
  ];

  let pdf = "%PDF-1.4\n";
  const offsets = [0];
  for (const [index, object] of objects.entries()) {
    offsets.push(Buffer.byteLength(pdf));
    pdf += `${index + 1} 0 obj\n${object}\nendobj\n`;
  }

  const xrefOffset = Buffer.byteLength(pdf);
  pdf += `xref\n0 ${objects.length + 1}\n`;
  pdf += "0000000000 65535 f \n";
  for (const offset of offsets.slice(1)) {
    pdf += `${String(offset).padStart(10, "0")} 00000 n \n`;
  }
  pdf += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xrefOffset}\n%%EOF\n`;

  writeFileSync(path, pdf, "binary");
}
