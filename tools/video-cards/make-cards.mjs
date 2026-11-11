// Renders the title, results and end cards used in the demo videos (landscape and vertical PNGs).
// Usage: node tools/video-cards/make-cards.mjs <output-dir>   (PLAYWRIGHT_MODULE / CHROMIUM_PATH optional)
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE ?? 'playwright');
const out = process.argv[2];
const css = (v) => `
*{box-sizing:border-box;margin:0}body{width:100vw;height:100vh;display:flex;flex-direction:column;justify-content:center;
padding:${v?'0 90px':'0 160px'};font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;color:#0b0b0b;
background:linear-gradient(160deg,#f9f9f7 0%,#e3eefc 100%)}
.logo{display:flex;align-items:center;gap:${v?22:20}px;margin-bottom:${v?56:40}px}
.mark{width:${v?96:108}px;height:${v?96:108}px;border-radius:20px;background:#1c5cab;display:grid;place-items:center}
.mark svg{width:60%;height:60%}
.name{font-size:${v?72:84}px;font-weight:700;letter-spacing:-.5px}
h1{font-size:${v?64:76}px;line-height:1.15;font-weight:700;letter-spacing:-.5px;margin-bottom:${v?40:28}px}
p{font-size:${v?40:42}px;line-height:1.4;color:#3a3a37}
.small{font-size:${v?30:30}px;color:#6f6d68;margin-top:${v?60:44}px}
ul{list-style:none;padding:0;display:grid;gap:${v?44:30}px;margin-top:${v?16:8}px}
li{display:grid;grid-template-columns:${v?'24px':'26px'} 1fr;gap:${v?28:30}px;font-size:${v?40:44}px;line-height:1.35}
li i{display:block;width:100%;height:${v?24:26}px;margin-top:${v?14:15}px;border-radius:5px;background:#eb6834}
li b{font-weight:650}
.src{display:block;font-size:${v?28:28}px;color:#6f6d68;margin-top:6px}
.cta{display:inline-block;align-self:flex-start;margin-top:${v?56:40}px;padding:${v?'26px 38px':'26px 42px'};border-radius:14px;background:#1c5cab;color:#fff;font-size:${v?40:42}px;font-weight:650}`;
const shield = `<svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linejoin="round"><path d="M12 3l7 3v5c0 5-3.5 8.5-7 10-3.5-1.5-7-5-7-10V6z"/><path d="M9 12l2 2 4-4"/></svg>`;
const logo = `<div class="logo"><div class="mark">${shield}</div><div class="name">Adaptive IDS</div></div>`;
const cards = {
  intro: `${logo}<h1>Machine-learning intrusion detection you can explain, monitor and change safely</h1>
    <p>Runs on your own hardware. No data leaves your network.</p>
    <div class="small">Walkthrough of the working product · demo data is clearly labelled SYNTHETIC</div>`,
  chapter: `<h1>Now on real public data</h1><p>NSL-KDD benchmark: models trained only on the training file, tested on unseen records</p>`,
  results: `<h1>Tested over time on CSE\u2011CIC\u2011IDS2018</h1><ul>
    <li><i></i><div><b>The approval gate blocked an update</b> that would have added 7.7 points of false positives</div></li>
    <li><i></i><div><b>When an attack type returned,</b> the governed model's recall rose from 0.2\u00a0% to 56\u00a0% with no rise in false positives</div></li>
    <li><i></i><div><b>Honest about limits:</b> no model caught new attack types on the day they first appeared</div></li></ul>`,
  offer: `<h1>Free 6-week evaluation for SOC teams and MSSPs</h1><ul>
    <li><i></i><div><b>Runs on your hardware</b> — no data leaves your network</div></li>
    <li><i></i><div><b>Read-only,</b> alongside your existing tools</div></li>
    <li><i></i><div><b>Success criteria agreed up front</b></div></li>
    <li><i></i><div><b>A results report you approve</b> before anyone else sees it</div></li></ul>`,
  end: `${logo}<h1>Let’s talk about an evaluation on your network</h1>
    <p>Muhammad Haider Abbas · Founder</p><div class="cta">Message me on LinkedIn</div>`,
};
const b = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
for (const [fmt, w, h] of [['landscape', 1920, 1080], ['vertical', 1080, 1920]]) {
  const p = await b.newPage({ viewport: { width: w, height: h } });
  for (const [k, body] of Object.entries(cards)) {
    await p.setContent(`<!doctype html><html><head><meta charset="utf-8"><style>${css(fmt === 'vertical')}</style></head><body>${body}</body></html>`);
    await p.screenshot({ path: `${out}/${k}-${fmt}.png` });
  }
}
await b.close();
