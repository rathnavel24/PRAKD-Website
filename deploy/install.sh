#!/bin/bash
# Deploy the Prakd site and put it live on prakd.in.
#   sudo bash ~/apps/prakd-site/deploy/install.sh               install/update + go live
#   sudo bash ~/apps/prakd-site/deploy/install.sh maintenance   back to the maintenance page
set -euo pipefail
cd "$(dirname "$0")/.."
EN=/etc/nginx/sites-enabled

if [ "${1:-}" = maintenance ]; then
  rm -f $EN/prakd.conf
  ln -sf /etc/nginx/sites-available/maintenance.conf $EN/maintenance.conf
  nginx -t && systemctl reload nginx
  echo "Maintenance page is back."; exit 0
fi

# 1. site files
install -d /var/www/prakd
cp -r site/. /var/www/prakd/
chmod -R a+rX /var/www/prakd

# 2. enquiry backend (FastAPI in its own Python environment, owned by rat)
install -d -o rat -g rat backend/data
if [ ! -x backend/.venv/bin/python ]; then
  python3 -c 'import ensurepip' 2>/dev/null || apt-get install -y python3-venv
  sudo -u rat python3 -m venv backend/.venv
fi
sudo -u rat backend/.venv/bin/python -m pip install -q --disable-pip-version-check -r backend/requirements.txt
install -m 644 deploy/prakd-backend.service /etc/systemd/system/prakd-backend.service
systemctl daemon-reload
systemctl enable prakd-backend >/dev/null 2>&1
systemctl restart prakd-backend

# 3. nginx: swap the maintenance page for the site (roll back if the config is bad)
install -m 644 deploy/prakd.conf /etc/nginx/sites-available/prakd.conf
rm -f $EN/maintenance.conf $EN/we-rewamp.conf $EN/default
ln -sf /etc/nginx/sites-available/prakd.conf $EN/prakd.conf
if ! nginx -t; then
  rm -f $EN/prakd.conf; ln -sf /etc/nginx/sites-available/maintenance.conf $EN/maintenance.conf
  echo "nginx config failed its test; maintenance page left in place."; exit 1
fi
systemctl reload nginx

sleep 3
echo "--- checks:"
echo "site:    $(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1/)  (want 200)"
echo "api:     $(curl -s http://127.0.0.1/api/health)  (want {\"status\":\"ok\"})"
echo "backend: $(systemctl is-active prakd-backend)"
