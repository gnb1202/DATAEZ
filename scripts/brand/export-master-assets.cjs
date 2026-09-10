// Chrome's CLI window-size clips small SVGs on Windows. Use an exact viewport.
const { chromium } = require("../ui-eval/node_modules/playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const path = require("node:path");
const root = path.resolve(__dirname, "../..");
const brand = path.join(root, "outputs/brand/gathered-ledger");
const jobs = [];
const add = (name, width, height = width) => jobs.push({ name, width, height, file: `${name}-${width === height ? width : `${width}x${height}`}.png` });
for (const size of [16, 32, 48, 180, 192, 512]) {
  add("dataez-app-icon-blue", size); add("dataez-app-icon-charcoal", size);
}
for (const size of [16, 24, 32, 64, 128, 256, 512]) add("dataez-symbol-blue", size);
for (const size of [64, 256, 512]) add("dataez-symbol-bright", size);
for (const tone of ["black", "white"]) add(`dataez-symbol-${tone}`, 512);
for (const tone of ["dark", "light", "black", "white"]) add(`dataez-lockup-${tone}`, 1280, 256);

async function main() {
  const browser = await chromium.launch({ headless: true, ...(process.argv[2] ? { executablePath: process.argv[2] } : { channel: process.env.BROWSER_CHANNEL || "chrome" }) });
  try {
    const page = await browser.newPage({ deviceScaleFactor: 1 });
    await fs.mkdir(path.join(brand, "master/raster"), { recursive: true });
    for (const { name, file, width, height } of jobs) {
      const source = await fs.readFile(path.join(brand, "master/vector", `${name}.svg`), "utf8");
      await page.setViewportSize({ width, height });
      await page.setContent(`<style>html,body{margin:0;background:transparent}svg{display:block;width:${width}px;height:${height}px}</style>${source}`);
      const png = await page.screenshot({ omitBackground: true });
      assert.equal(png.readUInt32BE(16), width, `${file}: width`);
      assert.equal(png.readUInt32BE(20), height, `${file}: height`);
      const bounds = await page.evaluate(async (data) => {
        const img = new Image(); img.src = `data:image/png;base64,${data}`; await img.decode();
        const canvas = document.createElement("canvas"); canvas.width = img.width; canvas.height = img.height;
        const ctx = canvas.getContext("2d"); ctx.drawImage(img, 0, 0);
        const pixels = ctx.getImageData(0, 0, img.width, img.height).data;
        let left = img.width, right = -1, top = img.height, bottom = -1, transparent = 0;
        for (let y = 0; y < img.height; y++) for (let x = 0; x < img.width; x++) {
          if (pixels[(y * img.width + x) * 4 + 3] > 0) {
            left = Math.min(left, x); right = Math.max(right, x); top = Math.min(top, y); bottom = Math.max(bottom, y);
          } else transparent++;
        }
        return { left, right, top, bottom, transparent };
      }, png.toString("base64"));
      assert.ok(bounds.right - bounds.left > width * 0.7, `${file}: empty or horizontally clipped`);
      assert.ok(bounds.bottom - bounds.top > height * 0.7, `${file}: vertically clipped`);
      assert.ok(bounds.transparent > 0, `${file}: missing transparent background`);
      await fs.writeFile(path.join(brand, "master/raster", file), png);
      console.log(`PASS ${file}`);
    }
    await fs.copyFile(path.join(brand, "social-share-1200x630.png"), path.join(root, "web/public/og-dataez.png"));
    console.log(`Rendered and verified ${jobs.length} PNG assets.`);
  } finally { await browser.close(); }
}
main().catch((error) => { console.error(error); process.exitCode = 1; });
