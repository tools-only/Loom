'use strict';

const { contextBridge } = require('electron');

// Expose minimal platform info to the renderer (localhost:3000)
contextBridge.exposeInMainWorld('__loom__', {
  platform: process.platform,
  versions: {
    electron: process.versions.electron,
    node:     process.versions.node,
  },
  isDesktop: true,
});
