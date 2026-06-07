// Drives the /visual page on the AI domain and captures stills per phase.
// Companion to capture_visual.mjs but pre-fills domain="ai".
import { chromium } from "playwright";
import { mkdir } from "node:fs/promises";

const BASE = process.env.VISUAL_BASE || "http://localhost:8000/visual/";
const OUT  = process.env.VISUAL_OUT  || "docs/visual/ai_screens";

const PHASES = [
  { waitFor: null,                                                  label: "01_initial" },
  { waitFor: ".stream-card .label:has-text('graph loaded')",        label: "02_graph_loaded" },
  { waitFor: ".stream-card .title:has-text('GapEstimate')",         label: "03_gap_diagnosed" },
  { waitFor: ".stream-card .title:has-text('Workflow')",            label: "04_workflow_planned" },
  { waitFor: ".stream-card .title:has-text('Artifact')",            label: "05_artifact_generated" },
  { waitFor: ".stream-card .label:has-text('session ready')",       label: "06_session_ready" },
];

async function main() {
  await mkdir(OUT, { recursive: true });
  const browser = await chromium.launch();
  const ctx = await browser.newContext({
    viewport: { width: 1280, height: 880 },
    deviceScaleFactor: 2,
  });
  const page = await ctx.newPage();

  console.log("[ai-visual] navigating to", BASE);
  await page.goto(BASE, { waitUntil: "networkidle" });

  // Pre-fill the AI domain
  await page.fill("#user", "builder");
  await page.fill("#domain", "ai");
  await page.screenshot({ path: `${OUT}/${PHASES[0].label}.png`, fullPage: true });
  console.log(`[ai-visual] captured: ${PHASES[0].label}`);

  await page.click("#start");

  for (const phase of PHASES.slice(1)) {
    try {
      await page.waitForSelector(phase.waitFor, { timeout: 240_000 });
      await page.waitForTimeout(400);
      await page.screenshot({ path: `${OUT}/${phase.label}.png`, fullPage: true });
      console.log(`[ai-visual] captured: ${phase.label}`);
    } catch (e) {
      console.error(`[ai-visual] timed out: ${phase.label}: ${e.message}`);
      await page.screenshot({ path: `${OUT}/${phase.label}_TIMEOUT.png`, fullPage: true });
      break;
    }
  }
  await ctx.close();
  await browser.close();
}

main().catch((e) => { console.error(e); process.exit(1); });
