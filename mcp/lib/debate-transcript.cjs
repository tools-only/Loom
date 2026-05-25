'use strict';
const fs = require('fs');
const path = require('path');

function create(debateId, topic, config) {
  return {
    debate_id: debateId,
    topic,
    created_at: new Date().toISOString(),
    finished_at: null,
    status: 'running',
    config: {
      max_rounds: config.max_rounds || 14,
      max_minutes: config.max_minutes || 60,
      models: config.models || {},
    },
    commitments: [],
    rounds: [],
    spec_path: null,
    anchor_patch_target: null,
  };
}

function addRound(transcript, roundData) {
  transcript.rounds.push(roundData);
}

function addCommitments(transcript, commitments) {
  for (const c of commitments) {
    transcript.commitments.push(c);
  }
}

function finalize(transcript, status, { specPath, patchTarget } = {}) {
  transcript.finished_at = new Date().toISOString();
  transcript.status = status;
  if (specPath) transcript.spec_path = specPath;
  if (patchTarget) transcript.anchor_patch_target = patchTarget;
}

function save(transcript, debatesDir) {
  const dir = path.join(debatesDir, transcript.debate_id);
  fs.mkdirSync(dir, { recursive: true });
  const filePath = path.join(dir, 'transcript.json');
  fs.writeFileSync(filePath, JSON.stringify(transcript, null, 2));
  return filePath;
}

function load(debateId, debatesDir) {
  const filePath = path.join(debatesDir, debateId, 'transcript.json');
  return JSON.parse(fs.readFileSync(filePath, 'utf8'));
}

module.exports = { create, addRound, addCommitments, finalize, save, load };
