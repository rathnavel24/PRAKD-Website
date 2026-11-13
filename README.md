# Prakd website

Source of [prakd.in](https://prakd.in): a static site plus a small enquiry API.

- `site/` — plain HTML, CSS and JS; no build step.
- `backend/main.py` — FastAPI enquiry API (Python, SQLite). Run by uvicorn from `backend/.venv`; listens on `127.0.0.1:8788` and stores enquiries in `backend/data/enquiries.db`.
- `deploy/` — nginx site config, Supervisor program config and installer for the server.
- `read-enquiries.sh` — prints recent enquiries.

## Deploy

```
sudo bash deploy/install.sh               # install or update, and go live
sudo bash deploy/install.sh maintenance   # back to the maintenance page
```

The Supervisor and nginx configs assume the checkout is at `/home/rat/apps/prakd-site`, and Python 3.10+. The installer creates `backend/.venv` and installs `backend/requirements.txt`.
For a Telegram message per enquiry, copy `deploy/local.env.example` to `deploy/local.env`.

## Manage the backend

```
sudo supervisorctl status
sudo supervisorctl restart prakd-backend
sudo supervisorctl tail -f prakd-backend
```
