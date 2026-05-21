'use strict';
// Prebuild helper: pre-extract winCodeSign to electron-builder's cache,
// skipping the macOS darwin/ symlinks that fail on Windows without Dev Mode.
// Run automatically via "prebuild" npm hook.

const { spawnSync } = require('child_process');
const https = require('https');
const path  = require('path');
const fs    = require('fs');
const os    = require('os');

if (process.platform !== 'win32') process.exit(0);

const VERSION    = '2.6.0';
const CACHE_BASE = path.join(os.homedir(), 'AppData', 'Local', 'electron-builder', 'Cache', 'winCodeSign');
const TARGET_DIR = path.join(CACHE_BASE, `winCodeSign-${VERSION}`);   // stable cache path eb checks
const ARCHIVE    = path.join(CACHE_BASE, `winCodeSign-${VERSION}.7z`);
const URL_GITHUB = `https://github.com/electron-userland/electron-builder-binaries/releases/download/winCodeSign-${VERSION}/winCodeSign-${VERSION}.7z`;
const URL_MIRROR = `https://npmmirror.com/mirrors/electron-builder-binaries/winCodeSign-${VERSION}/winCodeSign-${VERSION}.7z`;
const BIN_7ZA    = path.join(__dirname, '..', 'node_modules', '7zip-bin', 'win', 'x64', '7za.exe');

// ── Already cached? ─────────────────────────────────────────────────
if (fs.existsSync(TARGET_DIR) && fs.existsSync(path.join(TARGET_DIR, 'windows'))) {
  console.log('[setup-winsign] cache hit:', TARGET_DIR);
  process.exit(0);
}

fs.mkdirSync(CACHE_BASE, { recursive: true });

// ── Find archive (may be left from previous failed attempts) ─────────
function findExistingArchive() {
  if (fs.existsSync(ARCHIVE)) return ARCHIVE;
  // electron-builder leaves hash-named .7z files; pick any
  try {
    const f = fs.readdirSync(CACHE_BASE).find(n => n.endsWith('.7z'));
    return f ? path.join(CACHE_BASE, f) : null;
  } catch { return null; }
}

// ── Download ─────────────────────────────────────────────────────────
function download(url, dest) {
  return new Promise((resolve, reject) => {
    const tmp = dest + '.tmp';
    const file = fs.createWriteStream(tmp);
    const get = (u) => {
      const req = https.get(u, { headers: { 'User-Agent': 'loom-prebuild/1.0' } }, (res) => {
        if (res.statusCode === 301 || res.statusCode === 302) {
          file.close();
          get(res.headers.location);
          return;
        }
        if (res.statusCode !== 200) {
          reject(new Error('HTTP ' + res.statusCode + ' from ' + u));
          return;
        }
        let received = 0;
        const total = parseInt(res.headers['content-length'] || '0', 10);
        res.on('data', chunk => {
          received += chunk.length;
          if (total) process.stdout.write(`\r  ${(received / 1024 / 1024).toFixed(1)} / ${(total / 1024 / 1024).toFixed(1)} MB`);
        });
        res.pipe(file);
        file.on('finish', () => {
          file.close();
          process.stdout.write('\n');
          fs.renameSync(tmp, dest);
          resolve();
        });
      });
      req.on('error', reject);
    };
    get(url);
  });
}

// ── Extract ───────────────────────────────────────────────────────────
// Use -x!darwin -x!linux to skip macOS symlinks that require Dev Mode.
// Exit code 0 = OK, 1 = warning (symlinks skipped) — both acceptable.
function extract(archive, outDir) {
  console.log('[setup-winsign] extracting (skipping darwin symlinks)…');
  const r = spawnSync(BIN_7ZA, [
    'x', archive,
    '-o' + outDir,
    '-x!darwin',     // exclude macOS dir (contains .dylib symlinks)
    '-x!linux',      // exclude Linux dir (not needed on Windows)
    '-y',            // yes to all
    '-bd',           // no progress
  ], { stdio: 'inherit' });
  // 7zip exits 2 on "warnings" (e.g., skipped entries) which is fine
  if (r.status !== 0 && r.status !== 1 && r.status !== 2) {
    throw new Error('7zip exited ' + r.status);
  }
  // Verify windows tools were extracted
  if (!fs.existsSync(path.join(outDir, 'windows-10')) && !fs.existsSync(path.join(outDir, 'windows-6'))) {
    throw new Error('windows-10/ dir missing after extraction');
  }
}

// ── Main ─────────────────────────────────────────────────────────────
async function main() {
  let archive = findExistingArchive();

  if (!archive) {
    console.log('[setup-winsign] downloading winCodeSign', VERSION, '…');
    try {
      await download(URL_GITHUB, ARCHIVE);
    } catch (e) {
      console.log('[setup-winsign] primary failed, trying mirror…', e.message);
      await download(URL_MIRROR, ARCHIVE);
    }
    archive = ARCHIVE;
  } else {
    console.log('[setup-winsign] using existing archive:', archive);
  }

  extract(archive, TARGET_DIR);
  console.log('[setup-winsign] ready:', TARGET_DIR);
}

main().catch(e => {
  console.error('[setup-winsign] failed:', e.message);
  console.error('  Tip: enable Windows Developer Mode and retry, or run terminal as Administrator.');
  process.exit(1);
});
