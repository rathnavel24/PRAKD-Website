# Prakd website

Source of [prakd.in](https://prakd.in): a static site plus a small enquiry API.

- `site/` — plain HTML, CSS and JS; no build step.
- `backend/server.mjs` — Node enquiry API (no dependencies, built-in SQLite). Listens on `127.0.0.1:8788` and stores enquiries in `backend/data/enquiries.db`.
- `deploy/` — nginx site config, systemd unit and installer for the server.
- `read-enquiries.sh` — prints recent enquiries.

## Deploy

```
sudo bash deploy/install.sh               # install or update, and go live
sudo bash deploy/install.sh maintenance   # back to the maintenance page
```

The unit and nginx config assume the checkout is at `/home/rat/apps/prakd-site`, with a Node that has `node:sqlite` (22.5+).
For a Telegram message per enquiry, copy `deploy/local.env.example` to `deploy/local.env`.
