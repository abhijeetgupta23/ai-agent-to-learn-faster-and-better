// Drives the /visual page with Playwright, taking screenshots at each
// SSE event. Run:
//   node scripts/capture_visual.mjs
// Requires that the FastAPI server is already running on localhost:8000.

import { chromium } from "playwright";
import { mkdir } from "node:fs/promises";

const BASE = process.env.VISUAL_BASE || "http://localhost:8000/visual/";
const OUT  = process.env.VISUAL_OUT  || "docs/visual/screens";

// The SSE phases we want a screenshot for, in the order they arrive.
const PHASES = [
  { key: "initial",       waitFor: null,                                        label: "01_initial" },
  { key: "graph_loaded",  waitFor: ".stream-card .label:has-text('graph loaded')", label: "02_graph_loaded" },
  { key: "gap",           waitFor: ".stream-card .title:has-text('GapEstimate')",  label: "03_gap_diagnosed" },
  { key: "workflow",      waitFor: ".stream-card .title:has-text('Workflow')",     label: "04_workflow_planned" },
  { key: "artifact",      waitFor: ".stream-card .title:has-text('Artifact')",     label: "05_artifact_generated" },
  { key: "ready",         waitFor: ".stream-card .label:has-text('session ready')", label: "06_session_ready" },
];

async function main() {
  await mkdir(OUT, { recursive: true });

  const browser = await chromium.launch();
  const ctx = await browser.newContext({
    viewport: { width: 1280, height: 880 },
    deviceScaleFactor: 2,
    recordVideo: { dir: OUT, size: { width: 1280, height: 880 } },
  });
  const page = await ctx.newPage();

  console.log("[visual] navigating to", BASE);
  await page.goto(BASE, { waitUntil: "networkidle" });

  // 1. Initial state screenshot
  await page.screenshot({ path: `${OUT}/${PHASES[0].label}.png`, fullPage: true });
  console.log(`[visual] captured: ${PHASES[0].label}`);

  // 2. Kick off the session
  await page.click("#start");

  // 3. Capture each phase as it lands
  for (const phase of PHASES.slice(1)) {
    try {
      await page.waitForSelector(phase.waitFor, { timeout: 180_000 });
      // Give animation a beat to settle
      await page.waitForTimeout(400);
      await page.screenshot({ path: `${OUT}/${phase.label}.png`, fullPage: true });
      console.log(`[visual] captured: ${phase.label}`);
    } catch (e) {
      console.error(`[visual] timed out waiting for phase ${phase.key}:`, e.message);
      await page.screenshot({ path: `${OUT}/${phase.label}_TIMEOUT.png`, fullPage: true });
      break;
    }
  }

  await ctx.close(); // flushes the video
  await browser.close();
  console.log("[visual] done. Outputs in", OUT);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
