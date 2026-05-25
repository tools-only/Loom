'use strict';
const fs = require('fs');
const path = require('path');

function formatDuration(ms) {
  const m = Math.floor(ms / 60000);
  const s = Math.floor((ms % 60000) / 1000);
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

function commitmentsByLayer(commitments, layer) {
  return commitments
    .filter(c => c.layer === layer)
    .map(c => `- ${c.statement}`)
    .join('\n') || '- (no commitments reached for this layer)';
}

function gapTable(commitments) {
  const gaps = commitments.filter(c => c.layer === 'gap');
  if (!gaps.length) return '| - | - | - | - | - |\n| (no gap analysis reached) | | | | |';
  return gaps.map(c => `| | | ${c.statement} | | |`).join('\n');
}

function write(transcript, templatePath, debatesDir) {
  const dir = path.join(debatesDir, transcript.debate_id);
  fs.mkdirSync(dir, { recursive: true });

  const template = fs.existsSync(templatePath)
    ? fs.readFileSync(templatePath, 'utf8')
    : defaultTemplate();

  const durationMs = transcript.finished_at && transcript.created_at
    ? new Date(transcript.finished_at) - new Date(transcript.created_at)
    : 0;

  const lastRound = transcript.rounds[transcript.rounds.length - 1];
  const prdSummary = lastRound?.host_close?.summary || '(debate did not reach a final summary)';

  const spec = template
    .replace('{{topic}}', transcript.topic)
    .replace('{{debate_id}}', transcript.debate_id)
    .replace('{{rounds_used}}', transcript.rounds.length)
    .replace('{{duration}}', formatDuration(durationMs))
    .replace('{{finished_at}}', transcript.finished_at || new Date().toISOString())
    .replace('{{problem_phenomena}}', commitmentsByLayer(transcript.commitments, 'problem'))
    .replace('{{problem_stakeholders}}', '(see transcript)')
    .replace('{{problem_constraints}}', '(see transcript)')
    .replace('{{ideal_success_criteria}}', commitmentsByLayer(transcript.commitments, 'ideal'))
    .replace('{{ideal_required_properties}}', '(see transcript)')
    .replace('{{ideal_out_of_scope}}', '(see transcript)')
    .replace('{{gap_table_rows}}', gapTable(transcript.commitments))
    .replace('{{gap_root_causes}}', commitmentsByLayer(transcript.commitments, 'gap'))
    .replace('{{strategy_approach}}', commitmentsByLayer(transcript.commitments, 'strategy'))
    .replace('{{strategy_kpis}}', '(see transcript)')
    .replace('{{strategy_risks}}', '(see transcript)')
    .replace('{{strategy_open_questions}}', '(see transcript)')
    .replace('{{prd_summary}}', prdSummary)
    .replace('{{created_at}}', transcript.created_at)
    .replace('{{proposer_model}}', transcript.config.models.proposer || 'unknown')
    .replace('{{reviewer_model}}', transcript.config.models.reviewer || 'unknown');

  const specPath = path.join(dir, 'spec.md');
  fs.writeFileSync(specPath, spec);
  return specPath;
}

function defaultTemplate() {
  return `# Debate Spec — {{topic}}

> debate_id: {{debate_id}} · {{rounds_used}} rounds · {{duration}} · {{finished_at}}

---

## 1. 问题定义 (Problem Definition)

{{problem_phenomena}}

---

## 2. 理想态 (Ideal State)

{{ideal_success_criteria}}

---

## 3. 差距分析 (Gap Analysis)

| 维度 | 当前 | 理想 | 差距 | 优先级 |
|---|---|---|---|---|
{{gap_table_rows}}

{{gap_root_causes}}

---

## 4. 策略 (Strategy)

{{strategy_approach}}

---

## PRD 摘要

{{prd_summary}}

---

## 引用

- [Full Transcript](./transcript.json)
- Debate started: {{created_at}}
- Rounds: {{rounds_used}} / 14
- Proposer model: {{proposer_model}}
- Reviewer model: {{reviewer_model}}
`;
}

module.exports = { write };
