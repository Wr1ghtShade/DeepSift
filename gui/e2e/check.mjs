// Drives the built GUI, served by the gateway under its real CSP, in headless Chrome.
// Fails on any CSP or Trusted Types violation, console error or page error.
//   node e2e/check.mjs [--screenshots DIR]
import { mkdirSync } from "node:fs";
import puppeteer from "puppeteer-core";

const BASE = process.env.E2E_BASE ?? "http://127.0.0.1:8800";
const CHROME = process.env.CHROME_PATH ?? "/usr/bin/google-chrome";
const shotsAt = process.argv.indexOf("--screenshots");
const shots = shotsAt > 0 ? process.argv[shotsAt + 1] : null;
if (shots) mkdirSync(shots, { recursive: true });

const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: true,
  args: ["--no-sandbox", "--no-proxy-server"],
});
const page = await browser.newPage();
await page.setViewport({ width: 1440, height: 1000 });
const problems = [];
page.on("console", (m) => {
  if (m.type() === "error") problems.push(`console: ${m.text()}`);
});
page.on("pageerror", (e) => problems.push(`page error: ${e.message}`));
await page.evaluateOnNewDocument(() => {
  document.addEventListener("securitypolicyviolation", (e) =>
    console.error(`CSP violation: ${e.effectiveDirective} ${e.blockedURI} ${e.sample}`),
  );
});

const pause = (ms) => new Promise((r) => setTimeout(r, ms));
async function step(name, action) {
  try {
    await action();
    if (shots) await page.screenshot({ path: `${shots}/${name}.png`, fullPage: true });
    console.log(`ok  ${name}`);
  } catch (error) {
    problems.push(`${name}: ${error.message}`);
    console.log(`FAIL ${name}`);
  }
}

await step("login", async () => {
  await page.goto(`${BASE}/`, { waitUntil: "networkidle0" });
  await page.type("#token", "e2e-token");
  await page.click("button[type=submit]");
  await page.waitForSelector("#selector", { timeout: 5000 });
});

let investigation;
await step("new-search", async () => {
  await page.type("#selector", "alice");
  await page.waitForFunction(() => document.querySelector(".detected")?.textContent?.includes("Pseudo"));
  // Keep only the fake services that pivot into each other.
  for (const name of ["fake"]) {
    const box = await page.$(`#svc-${name}`);
    if (box && (await box.evaluate((b) => b.checked))) await box.click();
  }
  await page.click("button[type=submit]");
  await page.waitForFunction(() => /\/investigations\/\w+/.test(location.pathname), { timeout: 5000 });
  investigation = page.url().split("/").pop();
});

await step("results", async () => {
  await page.waitForFunction(() => document.querySelectorAll("table.data tbody tr").length >= 5, {
    timeout: 10000,
  });
  await page.waitForFunction(() => document.querySelector(".lede")?.textContent?.includes("terminée"), {
    timeout: 10000,
  });
  await page.waitForSelector(".graph canvas", { timeout: 10000 });
  await pause(500);
});

await step("entity", async () => {
  await page.click("table.data tbody tr a.cell-link");
  await page.waitForSelector(".entity-head", { timeout: 5000 });
});

await step("services", async () => {
  await page.goto(`${BASE}/services`, { waitUntil: "networkidle0" });
  await page.waitForSelector("#h-manifest", { timeout: 5000 });
});

await step("settings-light-theme", async () => {
  await page.goto(`${BASE}/settings`, { waitUntil: "networkidle0" });
  await page.waitForSelector("#h-gateway");
  const light = await page.$$("fieldset.choice input[value=light]");
  await light[0].click();
  const scheme = await page.$eval('meta[name="color-scheme"]', (m) => m.content);
  if (scheme !== "light") throw new Error(`theme not applied: ${scheme}`);
});

await step("investigations-delete", async () => {
  await page.goto(`${BASE}/investigations`, { waitUntil: "networkidle0" });
  await page.click("td.cell-actions button");
  await page.waitForSelector("dialog[open]");
  await page.click('dialog button[value="confirm"]');
  await page.waitForFunction(() => document.querySelector(".empty"), { timeout: 5000 });
});

await browser.close();
if (problems.length) {
  console.error(`\n${problems.length} problem(s):\n${problems.join("\n")}`);
  process.exit(1);
}
console.log(`\nGUI check passed (investigation ${investigation}).`);
