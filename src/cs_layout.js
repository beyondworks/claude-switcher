#!/usr/bin/env node
// Copy the sidebar layout (sections, groups, pinned order) from one account's Local Storage to another's.
// Usage: node cs_layout.js <from Local Storage/leveldb> <to Local Storage/leveldb> <from key> <to key>
// A key is "<account uuid>/<org uuid>", the same pair that names the claude-code-sessions folder.
// Both apps must be closed: LevelDB allows one opener, and an open app rewrites these entries from memory.
// Prints one JSON line: {"changed": [...], "skipped": [...]}. Only the sidebar entries listed below are touched;
// everything else in Local Storage (login, tokens, other settings) is neither read nor written.
const { ClassicLevel } = require('classic-level');

const PER_ACCOUNT = ['LSS-persisted.dframe-code-sections', 'LSS-persisted.dframe-group-scopes']; // value.value[<account>/<org>] holds the layout
const WHOLE = ['LSS-persisted.dframe-local-slice','epitaxy.sessionRailSections', 'LSS-sidebar-selected-mode', 'LSS-persisted.starred-session-groups'];

const ORIGIN_PREFIX = Buffer.from('_https://claude.ai\x00\x01', 'latin1');

function decode(v) {
  return v[0] === 0 ? v.slice(1).toString('utf16le') : v.slice(1).toString('latin1');
}

function encode(s) {
  // Chromium stores a string as 0x01 + latin1 when every char fits, else 0x00 + UTF-16LE.
  for (let i = 0; i < s.length; i++) {
    if (s.charCodeAt(i) > 255) return Buffer.concat([Buffer.from([0]), Buffer.from(s, 'utf16le')]);
  }
  return Buffer.concat([Buffer.from([1]), Buffer.from(s, 'latin1')]);
}

async function readEntries(db, names) {
  const found = {};
  for await (const [k, v] of db.iterator()) {
    if (k.length <= ORIGIN_PREFIX.length || !k.slice(0, ORIGIN_PREFIX.length).equals(ORIGIN_PREFIX)) continue;
    const name = k.slice(ORIGIN_PREFIX.length).toString('latin1');
    if (names.includes(name)) found[name] = { key: k, value: v };
  }
  return found;
}

async function main() {
  const [fromDir, toDir, fromKey, toKey] = process.argv.slice(2);
  if (!fromDir || !toDir || !fromKey || !toKey) throw new Error('usage: cs_layout.js <from> <to> <from key> <to key>');
  const names = PER_ACCOUNT.concat(WHOLE);
  const opts = { keyEncoding: 'buffer', valueEncoding: 'buffer' };
  const src = new ClassicLevel(fromDir, opts);
  await src.open();
  let from;
  try {
    from = await readEntries(src, names);
  } finally {
    await src.close();
  }

  const dst = new ClassicLevel(toDir, opts);
  await dst.open();
  const changed = [];
  const skipped = [];
  try {
    const to = await readEntries(dst, names);
    const now = Date.now();
    const ops = [];
    for (const name of PER_ACCOUNT) {
      const s = from[name] && JSON.parse(decode(from[name].value));
      const layout = s && s.value && s.value[fromKey];
      if (!layout) { skipped.push(name + ': no layout for the source account'); continue; }
      const t = to[name] ? JSON.parse(decode(to[name].value)) : { value: {}, tabId: '' };
      t.value = t.value || {};
      if (JSON.stringify(t.value[toKey]) === JSON.stringify(layout)) continue;
      t.value[toKey] = layout;
      t.timestamp = now;
      ops.push({ type: 'put', key: (to[name] || from[name]).key, value: encode(JSON.stringify(t)) });
      changed.push(name);
    }
    for (const name of WHOLE) {
      if (!from[name]) continue;
      if (to[name] && to[name].value.equals(from[name].value)) continue;
      ops.push({ type: 'put', key: (to[name] || from[name]).key, value: from[name].value });
      changed.push(name);
    }
    if (ops.length) await dst.batch(ops);
  } finally {
    await dst.close();
  }
  console.log(JSON.stringify({ changed, skipped }));
}

main().catch((e) => {
  console.error(String(e && e.message || e));
  process.exit(1);
});
