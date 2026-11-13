document.getElementById('year').textContent = new Date().getFullYear();

const form = document.getElementById('enquiry');
const msg = document.getElementById('form-msg');
const say = (text, cls) => { msg.textContent = text; msg.className = 'form-msg ' + (cls || ''); };

form.addEventListener('submit', async (ev) => {
  ev.preventDefault();
  const f = form.elements;
  const body = {
    name: f.name.value.trim(),
    email: f.email.value.trim(),
    company: f.company.value.trim(),
    message: f.message.value.trim(),
    topics: [...form.querySelectorAll('input[name=topics]:checked')].map((c) => c.value),
    website: f.website.value,
    source: location.pathname
  };
  const bad = [];
  if (!body.name) bad.push(f.name);
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(body.email)) bad.push(f.email);
  if (!body.message) bad.push(f.message);
  for (const el of [f.name, f.email, f.message]) el.classList.toggle('bad', bad.includes(el));
  if (bad.length) { say('Please fill in your name, a valid email and a message.', 'err'); bad[0].focus(); return; }

  const btn = form.querySelector('button');
  btn.disabled = true; say('Sending…');
  try {
    const r = await fetch('/api/enquiries', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
    });
    if (r.status === 201) { form.reset(); say('Thanks, your message is in. We\'ll reply by email.', 'ok'); }
    else if (r.status === 429) say('Too many messages from your connection. Please try again later.', 'err');
    else if (r.status === 422) say('Please check your name, email and message.', 'err');
    else say('Something went wrong on our side. Please try again in a minute.', 'err');
  } catch {
    say('Could not reach the server. Check your connection and try again.', 'err');
  } finally { btn.disabled = false; }
});
