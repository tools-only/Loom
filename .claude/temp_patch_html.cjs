const fs = require('fs');
const path = require('path');
const fp = path.join(__dirname, '..', 'mcp', 'server.cjs');
let s = fs.readFileSync(fp, 'utf8');

// Read exact bytes from file
const raw = fs.readFileSync(fp, 'utf8');
const idx = raw.indexOf("app.post('/html'");
const endIdx = raw.indexOf('\n});\n\n// Legacy', idx) + 4;
const old = raw.substring(idx, endIdx).replace(/\r\n/g, '\n');

const next = old
  .replace('const html = req.body.html || \'\';', "const html = req.body.html || '';\n  const surface = normalizeSurface(req.body.surface || 'fin');")
  .replace('broadcast(html);', 'setSurfaceHtml(surface, html);\n  broadcast(html, surface);');

if (!s.includes(old)) {
  console.log('ERROR: could not match route');
  console.log('EXTRACTED:');
  console.log(JSON.stringify(old));
  process.exit(1);
}
s = s.replace(old, next);
fs.writeFileSync(fp, s, 'utf8');
console.log('OK - patched POST /html to support surface parameter');
