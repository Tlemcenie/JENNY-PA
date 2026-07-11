import { chromium } from "playwright";

const API = "http://127.0.0.1:8000";
const APP = "http://localhost:3000";

const r = await fetch(API + "/api/v1/auth/login", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ email: "demo@jenny.ai", password: "Demo!1234" }),
});
const { access_token } = await r.json();
if (!access_token) { console.error("pas de token"); process.exit(1); }

const b = await chromium.launch();
const ctx = await b.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2 });
await ctx.addInitScript((t) => localStorage.setItem("jenny_token", t), access_token);
const page = await ctx.newPage();

const shots = [
  ["dashboard", "/dashboard"],
  ["chat", "/chat"],
  ["lab", "/lab"],
  ["prestations", "/prestations"],
];
for (const [name, path] of shots) {
  try {
    await page.goto(APP + path, { waitUntil: "networkidle", timeout: 30000 });
  } catch (_) {}
  await page.waitForTimeout(2800);
  await page.screenshot({ path: `/tmp/jenny_charts/screen_${name}.png`, fullPage: false });
  console.log("shot", name);
}
await b.close();
