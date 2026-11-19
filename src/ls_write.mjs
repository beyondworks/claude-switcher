// Write account-unified sidebar/permission values into a Claude data folder's Local Storage (LevelDB).
// The desktop app keeps these preferences as "LSS-persisted.<key>" entries in Local Storage and only mirrors them into
// claude_desktop_config.json, so a value written to the config file alone is overwritten from Local Storage at the next
// start (2026-11-19: group assignments copied to account A came back empty). Run only while the app is closed:
// an open app holds the LevelDB lock and this exits with code 3 without writing.
//   node ls_write.mjs <data dir>/Local Storage/leveldb <values.json>   ({"<pref key>": <value>, ...})
import { ClassicLevel } from 'classic-level'
import fs from 'node:fs'

const [dir, file] = process.argv.slice(2)
const values = JSON.parse(fs.readFileSync(file, 'utf8'))
const PREFIX = Buffer.from('_https://claude.ai\u0000\u0001LSS-persisted.', 'latin1')
const encode = (s) => /^[\u0000-ÿ]*$/.test(s)
  ? Buffer.concat([Buffer.from([1]), Buffer.from(s, 'latin1')])
  : Buffer.concat([Buffer.from([0]), Buffer.from(s, 'utf16le')])
let db
try {
  db = new ClassicLevel(dir, { keyEncoding: 'buffer', valueEncoding: 'buffer', createIfMissing: false })
  await db.open()
} catch (e) {
  console.error(`cannot open ${dir}: ${e.code || e.message}`)
  process.exit(3)
}
const now = Date.now()
const ops = Object.entries(values).map(([k, v]) => ({
  type: 'put', key: Buffer.concat([PREFIX, Buffer.from(k, 'latin1')]),
  value: encode(JSON.stringify({ value: v, tabId: '', timestamp: now })),
}))
await db.batch(ops)
await db.close()
console.log(ops.length)
