/**
 * Capture one screenshot per view for the report.
 *
 * Uses the Edge/Chrome already installed on the machine (playwright-core, no
 * browser download). Requires the API on :8000 and the Vite dev server on :5173.
 *
 *   npm run screenshots
 */
import { mkdir } from "node:fs/promises";
import path from "node:path";

import { chromium } from "playwright-core";

const EDGE = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const BASE = process.env.FRONTEND_URL ?? "http://localhost:5173";
const OUT = path.resolve(process.cwd(), "..", "report", "screenshots");

const VIEWS = [
  {
    id: "network",
    file: "stage7_network_explorer.png",
    waitFor: "Open this author on OpenAlex",
  },
  { id: "fragility", file: "stage7_fragility.png", waitFor: "Cascade:" },
  {
    id: "recommender",
    file: "stage7_recommender.png",
    waitFor: "Top predicted collaborations",
  },
  { id: "reviewers", file: "stage7_reviewers.png", waitFor: "Method comparison" },
];

await mkdir(OUT, { recursive: true });

const browser = await chromium.launch({ executablePath: EDGE, headless: true });
const page = await browser.newPage({
  viewport: { width: 1440, height: 1000 },
  deviceScaleFactor: 1,
});

for (const view of VIEWS) {
  // Reload after setting the hash so the app boots directly on that view.
  await page.goto(`${BASE}/#/${view.id}`, { waitUntil: "domcontentloaded" });
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.getByText(view.waitFor, { exact: false }).first().waitFor({
    timeout: 90000,
  });
  // Let Cytoscape finish its layout and the fonts settle.
  await page.waitForTimeout(1800);
  await page.screenshot({ path: path.join(OUT, view.file), fullPage: true });
  console.log(`saved report/screenshots/${view.file}`);
}

await browser.close();
