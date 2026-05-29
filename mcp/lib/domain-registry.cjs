'use strict';

const fs = require('fs');
const path = require('path');

function loadDomainManifests(rootDir) {
  const domainsDir = path.join(rootDir, 'domains');
  if (!fs.existsSync(domainsDir)) return [];

  return fs.readdirSync(domainsDir, { withFileTypes: true })
    .filter(entry => entry.isDirectory())
    .map(entry => path.join(domainsDir, entry.name, 'manifest.json'))
    .filter(manifestPath => fs.existsSync(manifestPath))
    .map(manifestPath => {
      const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
      return {
        ...manifest,
        manifestPath,
      };
    });
}

function buildDomainManifestResponse(manifests) {
  return {
    ok: true,
    domains: manifests.map(({ manifestPath, ...manifest }) => manifest),
  };
}

module.exports = {
  buildDomainManifestResponse,
  loadDomainManifests,
};
