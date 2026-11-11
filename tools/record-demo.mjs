// Records a captioned walkthrough of the SYNTHETIC demo as a video (WebM).
// DEMO_FORMAT=landscape (default, 1920x1080) or vertical (1080x1920, for Shorts, Reels and TikTok).
//
// Prerequisites:
//   adaptive-ids db-upgrade && adaptive-ids create-user admin --role admin
//   adaptive-ids demo --admin admin
//   (cd apps/web && npm ci && npm run build); ADAPTIVE_IDS_WEB_DIST=apps/web/dist adaptive-ids serve
//   npm install --no-save playwright   (or use an existing Playwright install)
//
// Usage: DEMO_PASSWORD=... node tools/record-demo.mjs [base-url] [output-dir]
// Optional: PLAYWRIGHT_MODULE (path to playwright's index.mjs), CHROMIUM_PATH (browser executable).
// The narration that goes with each scene is in docs/demo-script.md.

import { mkdirSync, readdirSync, renameSync } from "node:fs";
import { join } from "node:path";

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE ?? "playwright");
const BASE = process.argv[2] ?? "http://127.0.0.1:8000";
const OUT = process.argv[3] ?? "demo-recording";
const USER = process.env.DEMO_USER ?? "admin";
const PASSWORD = process.env.DEMO_PASSWORD;
if (!PASSWORD) throw new Error("set DEMO_PASSWORD to the demo admin's password");
mkdirSync(OUT, { recursive: true });

const VERTICAL = process.env.DEMO_FORMAT === "vertical";
// Playwright records frames at the viewport's CSS-pixel size (a larger video size only adds padding).
// Landscape: a 1920x1080 viewport with the page zoomed 1.5x, so the app lays out as at 1280x720 but renders
// sharply at full HD. Vertical: a 540x960 phone-width viewport (the app's mobile layout); upscale the
// recording to 1080x1920 afterwards.
const viewport = VERTICAL ? { width: 540, height: 960 } : { width: 1920, height: 1080 };
const zoom = VERTICAL ? 1 : 1.5;
const PACE = VERTICAL ? 0.8 : 1; // vertical cuts are shorter
const browser = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
// bypassCSP only lets the recorder draw its caption overlay; the app itself is unchanged.
const ctx = await browser.newContext({ viewport, recordVideo: { dir: OUT, size: viewport }, bypassCSP: true,
  colorScheme: "light" });
if (zoom !== 1) {
  await ctx.addInitScript((z) => {
    document.addEventListener("DOMContentLoaded", () => { document.documentElement.style.zoom = String(z); });
  }, zoom);
}
const page = await ctx.newPage();
const pause = (ms) => page.waitForTimeout(ms);

async function caption(title, body = "", ms = 4500) {
  await page.evaluate(([t, b, vertical]) => {
    let el = document.getElementById("__demo_caption");
    if (!el) {
      el = document.createElement("div");
      el.id = "__demo_caption";
      Object.assign(el.style, {
        position: "fixed", left: "50%", bottom: vertical ? "56px" : "28px", transform: "translateX(-50%)", zIndex: "99999",
        width: vertical ? "88%" : "auto", maxWidth: "880px", padding: vertical ? "16px 18px" : "14px 20px",
        borderRadius: "12px", background: "rgba(11,11,11,0.88)", color: "#fff",
        font: `${vertical ? 17 : 15}px/1.45 system-ui, sans-serif`, boxShadow: "0 6px 24px rgba(0,0,0,0.25)",
        pointerEvents: "none",
      });
      document.body.appendChild(el);
    }
    el.replaceChildren();
    const h = document.createElement("div");
    h.textContent = t;
    Object.assign(h.style, { fontWeight: "600", fontSize: vertical ? "20px" : "17px", marginBottom: b ? "4px" : "0" });
    el.appendChild(h);
    if (b) { const p = document.createElement("div"); p.textContent = b; el.appendChild(p); }
  }, [title, body, VERTICAL]);
  await pause(ms * PACE);
}

async function go(path) {
  await page.goto(BASE + path);
  await page.waitForLoadState("networkidle");
  await pause(600);
}

async function scrollTo(selector) {
  await page.evaluate((s) => {
    const el = document.querySelector(s);
    if (el) window.scrollTo({ top: el.getBoundingClientRect().top + window.scrollY - 70, behavior: "smooth" });
  }, selector);
  await pause(900);
}

// Scene 1 — sign in
await go("/login");
await caption("Adaptive IDS", "A local-first intrusion detection platform. This walkthrough uses the built-in SYNTHETIC demo data.", 4000);
await page.getByLabel("Username").fill(USER);
await page.getByLabel("Password").fill(PASSWORD);
await page.getByRole("button", { name: "Sign in" }).click();
await page.waitForURL((u) => !u.pathname.startsWith("/login"));
await page.waitForLoadState("networkidle");

// Scene 2 — dashboard
await pause(800);
await caption("Dashboard", "Every number comes from the API with its counting rule. Model alerts are suspicions, not confirmed attacks.", 6000);

// Scene 3 — alerts and one investigation with its explanation
const token = await page.evaluate(() => Object.values(sessionStorage).find((v) => typeof v === "string" && v.length > 20));
const alerts = await page.evaluate(async ([t]) => {
  const r = await fetch("/api/alerts?limit=500", { headers: { Authorization: `Bearer ${t}` } });
  return (await r.json()).items;
}, [token]);
const pick = [...alerts].filter((a) => a.status === "new").sort((a, b) => (a.score ?? 1) - (b.score ?? 1))[0] ?? alerts[0];
await go("/alerts");
await caption("Alerts", "Created from suspicious predictions, with severity from documented, configurable rules.", 5000);
await go(`/alerts/${pick.id}`);
await caption("Investigation view", "The prediction, the exact model and preprocessing versions, the event and its input features.", 5500);
await scrollTo("#explain-h");
await page.locator(".shap-row").first().waitFor();
await caption("Why the model gave this score", "Exact SHAP contributions from the same artifact. Shown only after the prediction is reproduced and the parts add up to the score.", 6500);
await page.locator(".shap-row").nth(0).hover();
await pause(1800);
await page.locator(".shap-row").nth(1).hover();
await pause(1800);
await page.mouse.move(5, 5);
await page.evaluate(() => window.scrollTo({ top: 0, behavior: "smooth" }));
await pause(800);
await page.getByRole("button", { name: "Start investigating" }).click();
const dialog = page.getByRole("dialog");
await dialog.getByRole("textbox").fill("Reviewing the source host's other flows.");
await pause(1200);
await dialog.getByRole("button", { name: "Start investigating" }).click();
await page.waitForLoadState("networkidle");
await pause(1200);
await caption("Analyst decisions are separate", "Status changes and notes are recorded as the analyst's decisions, never mixed with model output.", 5000);

// Scene 4 — drift
await go("/drift");
await caption("Drift monitoring", "Feature, prediction, performance and suspected concept drift are reported separately. Drift never retrains or promotes a model.", 6500);
await go("/drift/analyses/1");
await caption("A drift analysis", "Reference vs current window: per-feature statistics, thresholds and events for review.", 5500);

// Scene 5 — governance
await go("/models");
await caption("Model governance", "A candidate is evaluated against the active model on the same labelled events before anyone can approve it.", 6000);
await go("/evaluations/2");
await caption("Candidate evaluation", "Paired-bootstrap confidence intervals against non-inferiority margins. This candidate fails the false-positive gate.", 7000);
await scrollTo(".forest");
await pause(2500);
await go("/models/2");
await caption("Approval is explicit", "A failed evaluation can only be approved with an audited, written override. Activation first proves the artifact can be restored.", 6500);

// Scene 6 — audit and close
await go("/audit");
await caption("Audit log", "Sign-ins, imports, scoring, decisions, approvals and exports are recorded.", 5000);
await go("/");
await caption("Local-first, reproducible, explainable", "Runs on one machine with no cloud services. Source, tests and documentation: see the repository README.", 5500);

await ctx.close();
await browser.close();
const video = readdirSync(OUT).filter((f) => f.endsWith(".webm")).map((f) => join(OUT, f))[0];
if (video) {
  const target = join(OUT, `adaptive-ids-demo-${VERTICAL ? "vertical" : "landscape"}.webm`);
  renameSync(video, target);
  console.log(`Wrote ${target}`);
}
