// Records the real-data chapter of the demo video from an instance loaded with the NSL-KDD worked example
// (docs/phase-6-governance.md, docs/model-explanations.md): the failed candidate evaluation and an explained
// false positive. Usage:
//   DEMO_PASSWORD=... EVAL_ID=2 ALERT_ID=425 node tools/record-real-data.mjs <base-url> <out-dir> landscape|vertical
// Optional: DEMO_USER (default admin), PLAYWRIGHT_MODULE, CHROMIUM_PATH.
import { mkdirSync, readdirSync, renameSync } from 'node:fs';
import { join } from 'node:path';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE ?? 'playwright');
const EVAL_ID = process.env.EVAL_ID ?? '2', ALERT_ID = process.env.ALERT_ID ?? '425';
if (!process.env.DEMO_PASSWORD) throw new Error('set DEMO_PASSWORD');
const [BASE, OUT, FMT] = process.argv.slice(2);
const VERTICAL = FMT === 'vertical';
mkdirSync(OUT, { recursive: true });
const viewport = VERTICAL ? { width: 540, height: 960 } : { width: 1920, height: 1080 };
const zoom = VERTICAL ? 1 : 1.5;
const b = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
const ctx = await b.newContext({ viewport, recordVideo: { dir: OUT, size: viewport }, bypassCSP: true, colorScheme: 'light' });
if (zoom !== 1) await ctx.addInitScript((z) => { document.addEventListener('DOMContentLoaded', () => { document.documentElement.style.zoom = String(z); }); }, zoom);
const page = await ctx.newPage();
const pause = (ms) => page.waitForTimeout(ms);
async function caption(t, body, ms) {
  await page.evaluate(([t, b, v]) => {
    let el = document.getElementById('__c');
    if (!el) { el = document.createElement('div'); el.id = '__c';
      Object.assign(el.style, { position: 'fixed', left: '50%', bottom: v ? '56px' : '28px', transform: 'translateX(-50%)', zIndex: '99999',
        width: v ? '88%' : 'auto', maxWidth: '880px', padding: v ? '16px 18px' : '14px 20px', borderRadius: '12px',
        background: 'rgba(11,11,11,0.88)', color: '#fff', font: `${v ? 17 : 15}px/1.45 system-ui, sans-serif`, pointerEvents: 'none' });
      document.body.appendChild(el); }
    el.replaceChildren();
    const h = document.createElement('div'); h.textContent = t;
    Object.assign(h.style, { fontWeight: '600', fontSize: v ? '20px' : '17px', marginBottom: '4px' }); el.appendChild(h);
    const p = document.createElement('div'); p.textContent = b; el.appendChild(p);
  }, [t, body, VERTICAL]);
  await pause(ms);
}
async function go(path) { await page.goto(BASE + path); await page.waitForLoadState('networkidle'); await page.mouse.move(2, 2); await pause(700); }
async function scrollTo(sel, off = 70) {
  await page.evaluate(([s, o]) => { const el = document.querySelector(s); if (el) window.scrollTo({ top: el.getBoundingClientRect().top + window.scrollY - o, behavior: 'smooth' }); }, [sel, off]);
  await pause(1000);
}
await page.goto(BASE + '/login');
await page.getByLabel('Username').fill(process.env.DEMO_USER ?? 'admin'); await page.getByLabel('Password').fill(process.env.DEMO_PASSWORD);
await page.getByRole('button', { name: 'Sign in' }).click();
await page.waitForURL((u) => !u.pathname.startsWith('/login'));
await go(`/evaluations/${EVAL_ID}`);
await caption('Real public data: NSL-KDD', 'Two models trained only on the dataset’s training file, compared on the same 22,544 test events.', 5000);
await caption('A better-looking model, blocked', 'The candidate catches 3.3 points more attacks, but false positives rise 1.7 points — beyond the 0.5-point margin. Verdict: fail.', 6500);
await scrollTo('.forest', 120);
await pause(3500);
await go(`/alerts/${ALERT_ID}`);
await scrollTo('#explain-h');
await page.locator('.shap-row').first().waitFor();
await caption('A false positive, explained', 'A normal record flagged as “teardrop” — almost entirely because of one feature: wrong_fragment.', 6000);
await page.locator('.shap-row').first().hover(); await pause(2000); await page.mouse.move(2, 600);
await caption('One learned rule, found', 'In training, fragment errors never occur in normal traffic. All 52 such test records were flagged: 22 % of all false positives.', 7000);
await ctx.close(); await b.close();
const v = readdirSync(OUT).filter((f) => f.endsWith('.webm')).map((f) => join(OUT, f))[0];
renameSync(v, join(OUT, `real-${FMT}.webm`));
console.log('ok', FMT);
