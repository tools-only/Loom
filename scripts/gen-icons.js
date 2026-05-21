'use strict';
// Gen-icons: uses Electron's Chromium to render logo-mark.svg → icon.png + icon.ico
// Run: npm run gen-icons

const { app, BrowserWindow, nativeImage } = require('electron');
const path = require('path');
const fs   = require('fs');

const ROOT      = path.join(__dirname, '..');
const ASSET_DIR = path.join(ROOT, 'resource', 'assets');

app.disableHardwareAcceleration(); // avoid GPU init delay

app.whenReady().then(async () => {
  const svgRaw = fs.readFileSync(path.join(ASSET_DIR, 'logo-mark.svg'), 'utf8');

  // Render SVG on a macOS-style rounded-square background (512×512)
  const html = `<!DOCTYPE html><html><head><meta charset="utf-8">
<style>
  * { margin:0; padding:0; box-sizing:border-box; }
  html, body { width:512px; height:512px; overflow:hidden; }
  body {
    display:flex; align-items:center; justify-content:center;
    background:
      radial-gradient(circle at 28% 28%, #EDE9FE 0%, #C4B5FD 28%, #7A5AF8 60%, #4A2EC0 100%);
    border-radius: 118px;
  }
  .logo { width:300px; height:300px; }
</style>
</head>
<body>
<div class="logo">${svgRaw.replace('<svg ', '<svg class="logo" ')}</div>
</body></html>`;

  const win = new BrowserWindow({
    width: 512, height: 512,
    show: false, frame: false,
    webPreferences: { offscreen: false },
  });

  await win.loadURL('data:text/html;charset=utf-8,' + encodeURIComponent(html));

  // Wait for render & gradients to settle
  await new Promise(r => setTimeout(r, 600));

  const captured = await win.webContents.capturePage({ x: 0, y: 0, width: 512, height: 512 });
  win.destroy();

  if (captured.isEmpty()) {
    console.error('capturePage returned empty — try running with a display connected.');
    app.exit(1);
    return;
  }

  // ── Save icon.png (512×512) ───────────────────────────────────────
  const png512 = captured.resize({ width: 512, height: 512 });
  const png512Buf = png512.toPNG();
  fs.writeFileSync(path.join(ASSET_DIR, 'icon.png'), png512Buf);
  console.log('✓ icon.png  (512×512)');

  // ── Build icon.ico (multi-size: 16/32/48/256) ────────────────────
  // ICO supports embedded PNG data (Windows Vista+)
  const icoSizes = [16, 32, 48, 256];
  const icoPngs  = icoSizes.map(s =>
    captured.resize({ width: s, height: s }).toPNG()
  );
  fs.writeFileSync(path.join(ASSET_DIR, 'icon.ico'), buildIco(icoPngs, icoSizes));
  console.log('✓ icon.ico  (16 / 32 / 48 / 256)');

  // ── Tray-sized copies (just in case) ─────────────────────────────
  const png32Buf = captured.resize({ width: 32, height: 32 }).toPNG();
  fs.writeFileSync(path.join(ASSET_DIR, 'icon-32.png'), png32Buf);

  console.log('\nAll icons written to resource/assets/');
  app.quit();
});

// ── Pure-JS ICO builder (embeds PNG blobs, no deps) ──────────────────
function buildIco(pngBuffers, sizes) {
  const n          = pngBuffers.length;
  const headerSize = 6;
  const dirSize    = n * 16;

  let dataOffset = headerSize + dirSize;
  const offsets  = pngBuffers.map(buf => { const o = dataOffset; dataOffset += buf.length; return o; });

  const header = Buffer.alloc(headerSize);
  header.writeUInt16LE(0, 0);  // reserved
  header.writeUInt16LE(1, 2);  // type = ICO
  header.writeUInt16LE(n, 4);  // image count

  const dirs = pngBuffers.map((buf, i) => {
    const d = Buffer.alloc(16);
    const s = sizes[i];
    d.writeUInt8(s >= 256 ? 0 : s, 0);  // 0 means 256
    d.writeUInt8(s >= 256 ? 0 : s, 1);
    d.writeUInt8(0, 2);           // color count (0 = TrueColor)
    d.writeUInt8(0, 3);           // reserved
    d.writeUInt16LE(1, 4);        // color planes
    d.writeUInt16LE(32, 6);       // bits per pixel
    d.writeUInt32LE(buf.length, 8);    // byte size of image data
    d.writeUInt32LE(offsets[i], 12);   // offset from start of file
    return d;
  });

  return Buffer.concat([header, ...dirs, ...pngBuffers]);
}
