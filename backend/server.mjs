// Prakd enquiry backend: POST /api/enquiries from the prakd.in contact form.
// Zero dependencies: Node's built-in http + sqlite. Sits behind nginx on 127.0.0.1.
import { createServer } from 'node:http';
import { randomBytes } from 'node:crypto';
import { mkdirSync, readFileSync } from 'node:fs';
import { dirname } from 'node:path';
import { DatabaseSync } from 'node:sqlite';

const PORT = Number(process.env.PORT ?? 8788);
const HOST = process.env.HOST ?? '127.0.0.1';
const DB_PATH = process.env.DB_PATH ?? new URL('./data/enquiries.db', import.meta.url).pathname;
const MAX_BODY = 32 * 1024;
const RATE_LIMIT = { max: 5, windowMs: 10 * 60 * 1000 }; // 5 enquiries per IP per 10 minutes

const TOPICS = new Set(['Web & app development', 'AI & automation', 'Cloud, DevOps & hosting', 'IT consulting & support']);
const VENTURES = new Set();
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

// Telegram notification for each new enquiry (same bot as the server alerts). Off if no token file.
const TG_CHAT = process.env.TELEGRAM_CHAT ?? '';
let TG_TOKEN = '';
try { if (process.env.TELEGRAM_TOKEN_FILE) TG_TOKEN = readFileSync(process.env.TELEGRAM_TOKEN_FILE, 'utf8').trim(); }
catch (err) { console.error(`telegram disabled: ${err.message}`); }
const esc = (v) => String(v ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
async function notify(e) {
  if (!TG_TOKEN || !TG_CHAT) return;
  const text = `📩 <b>New enquiry on prakd.in</b>\n\n<b>${esc(e.name)}</b>${e.company ? ` (${esc(e.company)})` : ''}\n${esc(e.email)}`
    + `\nTopics: ${esc(e.topics.join(', ') || '-')}\n\n${esc((e.message ?? '').slice(0, 3000))}`;
  try {
    const r = await fetch(`https://api.telegram.org/bot${TG_TOKEN}/sendMessage`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ chat_id: TG_CHAT, text, parse_mode: 'HTML', disable_web_page_preview: true }),
      signal: AbortSignal.timeout(15000)
    });
    if (!r.ok) console.error(`telegram notify failed: HTTP ${r.status}`);
  } catch (err) { console.error(`telegram notify failed: ${err.name}`); }
}

mkdirSync(dirname(DB_PATH), { recursive: true });
const db = new DatabaseSync(DB_PATH);
db.exec(`CREATE TABLE IF NOT EXISTS enquiries (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  name TEXT NOT NULL,
  email TEXT NOT NULL,
  company TEXT, phone TEXT, message TEXT,
  topics TEXT NOT NULL DEFAULT '[]',
  venture TEXT, source TEXT, ip TEXT, user_agent TEXT
)`);
const insert = db.prepare(`INSERT INTO enquiries
  (id, created_at, name, email, company, phone, message, topics, venture, source, ip, user_agent)
  VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`);

const hits = new Map(); // ip -> timestamps
function rateLimited(ip) {
  const now = Date.now();
  const recent = (hits.get(ip) ?? []).filter((t) => now - t < RATE_LIMIT.windowMs);
  if (recent.length >= RATE_LIMIT.max) { hits.set(ip, recent); return true; }
  recent.push(now);
  hits.set(ip, recent);
  return false;
}
setInterval(() => {
  const now = Date.now();
  for (const [ip, ts] of hits) if (ts.every((t) => now - t >= RATE_LIMIT.windowMs)) hits.delete(ip);
}, RATE_LIMIT.windowMs).unref();

function send(res, status, body) {
  res.writeHead(status, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' });
  res.end(JSON.stringify(body));
}

function readJson(req) {
  return new Promise((resolve, reject) => {
    let size = 0;
    const chunks = [];
    req.on('data', (c) => {
      size += c.length;
      if (size > MAX_BODY) { reject(Object.assign(new Error('Request too large.'), { status: 413 })); req.destroy(); return; }
      chunks.push(c);
    });
    req.on('end', () => {
      try { resolve(JSON.parse(Buffer.concat(chunks).toString('utf8') || '{}')); }
      catch { reject(Object.assign(new Error('Invalid JSON body.'), { status: 400 })); }
    });
    req.on('error', reject);
  });
}

const str = (v, max) => (typeof v === 'string' ? v.trim().slice(0, max) : '');

function validate(b) {
  const errors = [];
  if (!b || typeof b !== 'object' || Array.isArray(b)) return { errors: [{ msg: 'Invalid request body.' }] };
  const e = {
    name: str(b.name, 200),
    email: str(b.email, 254),
    company: str(b.company, 200) || null,
    phone: str(b.phone, 50) || null,
    message: str(b.message, 5000) || null,
    topics: Array.isArray(b.topics) ? [...new Set(b.topics.filter((t) => TOPICS.has(t)))] : [],
    venture: VENTURES.has(b.venture) ? b.venture : null,
    source: str(b.source, 300) || null
  };
  if (!e.name) errors.push({ loc: ['body', 'name'], msg: 'Please enter your name.' });
  if (!e.message) errors.push({ loc: ['body', 'message'], msg: 'Please enter a message.' });
  if (!EMAIL_RE.test(e.email)) errors.push({ loc: ['body', 'email'], msg: 'Please enter a valid email address.' });
  return { errors, enquiry: e };
}

const server = createServer(async (req, res) => {
  const url = new URL(req.url, 'http://localhost');
  // nginx sets X-Client-IP (Cloudflare's CF-Connecting-IP for tunnel traffic, else the peer address)
  const ip = req.headers['x-client-ip'] || req.socket.remoteAddress;

  try {
    if (url.pathname === '/api/health' && req.method === 'GET') return send(res, 200, { status: 'ok' });

    if (url.pathname === '/api/enquiries') {
      if (req.method !== 'POST') { res.setHeader('Allow', 'POST'); return send(res, 405, { detail: 'Method not allowed.' }); }
      if (!String(req.headers['content-type'] ?? '').includes('application/json'))
        return send(res, 415, { detail: 'Content-Type must be application/json.' });

      const body = await readJson(req);
      const { errors, enquiry: e } = validate(body);
      if (typeof body.website === 'string' && body.website.trim()) return send(res, 201, { id: 'enq_ok', status: 'received' });
      if (errors.length) return send(res, 422, { detail: errors });
      if (rateLimited(ip)) return send(res, 429, { detail: 'Too many enquiries from your connection. Please try again later.' });

      const id = `enq_${Date.now().toString(36)}${randomBytes(6).toString('hex')}`;
      const createdAt = new Date().toISOString();
      insert.run(id, createdAt, e.name, e.email, e.company, e.phone, e.message, JSON.stringify(e.topics),
        e.venture, e.source, String(ip), str(req.headers['user-agent'], 300) || null);
      console.log(`enquiry ${id} from ${e.email}${e.venture ? ` (${e.venture})` : ''}`);
      notify(e); // not awaited: the visitor gets their answer even if Telegram is slow
      return send(res, 201, { id, status: 'received', createdAt });
    }

    send(res, 404, { detail: 'Not found.' });
  } catch (err) {
    if (err.status) return send(res, err.status, { detail: err.message });
    console.error(err);
    send(res, 500, { detail: 'Our server had a problem. Please try again in a moment.' });
  }
});

server.listen(PORT, HOST, () => console.log(`prakd-backend listening on http://${HOST}:${PORT}, db ${DB_PATH}`));
for (const sig of ['SIGINT', 'SIGTERM']) process.on(sig, () => server.close(() => { db.close(); process.exit(0); }));
