// test-envelope.cjs — validates the envelope schema checker
// Run: node mcp/test-envelope.cjs
// No external deps; uses Node built-in assert.

const assert = require('assert');

// Clone of the SCHEMA_STUB from server.cjs for self-contained testing
const SCHEMA = {
  type: 'object',
  required: ['intent', 'provenance', 'schema_version'],
  properties: {
    schema_version: { const: '1.0' },
    intent: {
      type: 'object',
      required: ['op', 'target_kind'],
      properties: {
        op: { enum: ['refine','expand','shorten','longer','edit','lock','annotate','branch','restructure','ask','custom'] },
        instruction: { type: 'string', maxLength: 4000 },
        target_kind: { enum: ['anchor','selection','global'] },
        target_ref: { type: 'string' }
      }
    },
    selection: {
      type: ['object', 'null'],
      properties: {
        text: { type: 'string' },
        start_offset: { type: 'integer' },
        end_offset: { type: 'integer' },
        ancestor_anchor: { type: ['string', 'null'] },
        dom_path: { type: 'string' }
      }
    },
    context_bundle: {
      type: 'object',
      properties: {
        scope_hint: { enum: ['minimal','standard','wide'] },
        transient_override: { type: 'boolean' }
      }
    },
    render_state: { type: 'object' },
    provenance: {
      type: 'object',
      required: ['session_id', 'event_id', 'timestamp'],
      properties: {
        session_id: { type: 'string' },
        event_id: { type: 'string' },
        parent_event_id: { type: ['string', 'null'] },
        timestamp: { type: 'string' }
      }
    }
  }
};

function matchType(t, val) {
  if (t === 'string') return typeof val === 'string';
  if (t === 'integer') return typeof val === 'number' && Number.isInteger(val);
  if (t === 'number') return typeof val === 'number';
  if (t === 'boolean') return typeof val === 'boolean';
  if (t === 'object' || t === 'array') return val !== null && typeof val === t;
  if (t === 'null') return val === null;
  return false;
}

function validate(instance) {
  function check(schema, inst, path) {
    if (schema.required) {
      for (const r of schema.required) {
        if (!(r in (inst || {}))) {
          return { ok: false, code: 'MISSING_REQUIRED', message: r + ' is required', details: { path: path + '.' + r } };
        }
      }
    }
    if (inst === null || inst === undefined) {
      if (schema.type) {
        const types = Array.isArray(schema.type) ? schema.type : [schema.type];
        if (!types.includes('null')) return { ok: false, code: 'WRONG_TYPE', message: path + ' is null', details: { path, expected: types } };
        return { ok: true };
      }
      return { ok: true };
    }

    if (schema.enum && !schema.enum.includes(inst)) {
      return { ok: false, code: 'INVALID_ENUM', message: path + ' must be one of: ' + schema.enum.join(', ') };
    }
    if (schema.const !== undefined && inst !== schema.const) {
      return { ok: false, code: 'INVALID_CONST', message: path + ' must be ' + schema.const };
    }
    if (schema.maxLength !== undefined && typeof inst === 'string' && inst.length > schema.maxLength) {
      return { ok: false, code: 'TOO_LONG', message: path + ' exceeds max length ' + schema.maxLength };
    }

    if (schema.type) {
      const types = Array.isArray(schema.type) ? schema.type : [schema.type];
      if (!types.some(t => matchType(t, inst))) {
        return { ok: false, code: 'WRONG_TYPE', message: path + ' must be ' + types.join('|') };
      }
    }

    if (schema.properties && inst && typeof inst === 'object') {
      for (const [key, propSchema] of Object.entries(schema.properties)) {
        if (key in inst) {
          const r = check(propSchema, inst[key], path + '.' + key);
          if (!r.ok) return r;
        }
      }
    }
    return { ok: true };
  }
  return check(SCHEMA, instance, '');
}

function makeEnvelope(overrides) {
  const base = {
    schema_version: '1.0',
    intent: { op: 'refine', target_kind: 'anchor', target_ref: 'test.1', instruction: '' },
    provenance: { session_id: 'sess_1', event_id: 'evt_1', timestamp: new Date().toISOString() }
  };
  if (overrides) Object.assign(base, overrides);
  return base;
}

let passed = 0, failed = 0;

function test(name, fn) {
  try { fn(); console.log('  PASS:', name); passed++; }
  catch (e) { console.log('  FAIL:', name, '—', e.message); failed++; }
}

console.log('Testing envelope validator…\n');

// 1. Happy path
test('valid envelope passes', () => {
  assert.strictEqual(validate(makeEnvelope()).ok, true);
});

// 2. Missing required (intent)
test('missing intent fails', () => {
  const r = validate({ schema_version: '1.0', provenance: { session_id: 'x', event_id: 'y', timestamp: 'z' } });
  assert.strictEqual(r.ok, false);
  assert.strictEqual(r.code, 'MISSING_REQUIRED');
});

// 3. Missing required in nested (provenance.timestamp)
test('missing provenance timestamp fails', () => {
  const r = validate({ schema_version: '1.0', intent: { op: 'refine', target_kind: 'anchor' }, provenance: { session_id: 'x', event_id: 'y' } });
  assert.strictEqual(r.ok, false);
  assert.strictEqual(r.code, 'MISSING_REQUIRED');
});

// 4. Wrong enum (op)
test('invalid op enum fails', () => {
  const r = validate(makeEnvelope({ intent: { op: 'bogus', target_kind: 'anchor', target_ref: 'x' } }));
  assert.strictEqual(r.ok, false);
  assert.strictEqual(r.code, 'INVALID_ENUM');
});

// 5. Wrong enum (target_kind)
test('invalid target_kind enum fails', () => {
  const r = validate(makeEnvelope({ intent: { op: 'refine', target_kind: 'bogus', target_ref: 'x' } }));
  assert.strictEqual(r.ok, false);
  assert.strictEqual(r.code, 'INVALID_ENUM');
});

// 6. Wrong type
test('instruction as number fails', () => {
  const r = validate(makeEnvelope({ intent: { op: 'refine', target_kind: 'anchor', target_ref: 'x', instruction: 42 } }));
  assert.strictEqual(r.ok, false);
  assert.strictEqual(r.code, 'WRONG_TYPE');
});

// 7. Wrong const (schema_version)
test('wrong schema_version fails', () => {
  const r = validate(makeEnvelope({ schema_version: '2.0' }));
  assert.strictEqual(r.ok, false);
  assert.strictEqual(r.code, 'INVALID_CONST');
});

// 8. maxLength (instruction > 4000)
test('instruction exceeding maxLength fails', () => {
  const r = validate(makeEnvelope({ intent: { op: 'refine', target_kind: 'anchor', target_ref: 'x', instruction: 'x'.repeat(5000) } }));
  assert.strictEqual(r.ok, false);
  assert.strictEqual(r.code, 'TOO_LONG');
});

// 9. selection with null allowed
test('null selection passes', () => {
  assert.strictEqual(validate(makeEnvelope({ selection: null })).ok, true);
});

// 10. scope_hint enum in context_bundle
test('invalid scope_hint fails', () => {
  const r = validate(makeEnvelope({ context_bundle: { scope_hint: 'huge' } }));
  assert.strictEqual(r.ok, false);
  assert.strictEqual(r.code, 'INVALID_ENUM');
});

console.log('\n' + passed + ' passed, ' + failed + ' failed');
process.exit(failed > 0 ? 1 : 0);
