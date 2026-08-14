#!/usr/bin/env node

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const root = path.resolve(__dirname, '..');
const includePath = path.join(root, '_includes', 'research-theme-map.html');
const dataPath = path.join(root, '_data', 'research_theme_scores.json');
const configPath = path.join(root, 'scripts', 'research_theme_concepts.json');
const include = fs.readFileSync(includePath, 'utf8');
const data = JSON.parse(fs.readFileSync(dataPath, 'utf8'));
const configBytes = fs.readFileSync(configPath);
const fail = message => { throw new Error(message); };
const paperOrder = data.metadata.paper_order;
const themes = data.concepts.filter(concept => concept.kind === 'theme');
const keywords = data.concepts.filter(concept => concept.kind === 'keyword');

if (data.sources.length !== 14 || paperOrder.length !== 14) fail('Expected 14 paper sources.');
if (themes.length !== 14) fail('Expected 14 main themes.');
if (keywords.length !== 22) fail('Expected 22 secondary keywords.');
if (data.metadata.families.length !== 6) fail('Expected six research families.');
const configHash = crypto.createHash('sha256').update(configBytes).digest('hex');
if (configHash !== data.metadata.concept_config_sha256) fail('Concept config hash is stale.');
data.concepts.forEach(concept => {
  if (!concept.lines?.length || concept.lines.length > 2) fail(`Invalid label lines: ${concept.label}`);
  const scores = paperOrder.map(id => concept.paper_scores[id]);
  if (scores.some(score => !Number.isFinite(score))) fail(`Missing paper score: ${concept.label}`);
  if (Math.abs(Math.max(...scores) - 1) > 1e-6) fail(`Paper scores are not normalized: ${concept.label}`);
  const familyTotal = Object.values(concept.family_weights).reduce((sum, value) => sum + value, 0);
  if (Math.abs(familyTotal - 1) > 1e-5) fail(`Family weights do not sum to one: ${concept.label}`);
});
const rendered = include.replace(
  /\{\{\s*site\.data\.research_theme_scores\s*\|\s*jsonify\s*\}\}/g,
  JSON.stringify(data)
);
const scripts = [...rendered.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/gi)]
  .map(match => match[1])
  .filter(script => script.trim());

if (!scripts.length) throw new Error('No inline scripts found in research theme map.');
scripts.forEach((script, index) => {
  try {
    new Function(script);
  } catch (error) {
    throw new Error(`Inline script ${index + 1} failed to parse: ${error.message}`);
  }
});

console.log(`Validated ${scripts.length} map script(s), 14 themes, 22 keywords, and six family mixtures.`);
