// Manual end-to-end check: with the API and dashboard running, screenshot every page and report
// console errors or error notices.  Usage: node tests/screens.cjs <output-dir> [base-url]
const { chromium } = require('playwright');
const pages = ['/', '/markets', '/intelligence', '/screener/stocks', '/screener/etfs', '/growth', '/undervalued', '/dividends',
  '/international', '/tfsa', '/portfolio', '/allocation', '/diversification', '/news', '/reports', '/paper', '/strategy',
  '/predictions', '/watchlists', '/notifications', '/costs', '/settings', '/brokerage', '/investment/64', '/investment/1', '/reports/4'];
(async () => {
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 1500, height: 1000 } });
  const errors = [];
  p.on('console', m => { if (m.type() === 'error') errors.push(`${p.url()}: ${m.text()}`); });
  p.on('pageerror', e => errors.push(`${p.url()}: PAGEERROR ${e.message}`));
  for (const path of pages) {
    await p.goto((process.argv[3] || 'http://127.0.0.1:3000') + path, { waitUntil: 'networkidle' });
    await p.waitForTimeout(700);
    const name = path === '/' ? 'dashboard' : path.slice(1).replace(/\//g, '_');
    await p.screenshot({ path: `${process.argv[2]}/${name}.png`, fullPage: false });
    const txt = await p.evaluate(() => [...document.querySelectorAll('.notice.bad')].map(e => e.textContent).join(' | '));
    if (txt) errors.push(`${path}: BAD NOTICE ${txt}`);
  }
  console.log(errors.join('\n') || 'no errors');
  await b.close();
})();
