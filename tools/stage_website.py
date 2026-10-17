"""Stage Privelto in the canonical server management workspace."""
from pathlib import Path
import json
import shutil
import yaml

root = Path(__file__).resolve().parents[1]
management = Path("D:/Otros IA/gestion_gallego_top")
site = management / "static-sites/sites/privelto.com"
shutil.copytree(root / "website/dist", site, dirs_exist_ok=True)
config = management / "static-sites/sites-enabled/privelto.com.conf"
config.write_text('''server {
    listen 8080;
    server_name privelto.com www.privelto.com;
    root /srv/sites/privelto.com;
    index index.html;
    charset utf-8;

    location = /__health {
        access_log off;
        default_type text/plain;
        return 200 "ok\\n";
    }

    location ~ ^/downloads/[^/]+\\.(exe|dmg|AppImage|zip|tar\\.gz)$ {
        default_type application/octet-stream;
        add_header Content-Disposition "attachment" always;
        add_header Cache-Control "public, max-age=31536000, immutable" always;
        try_files $uri =404;
    }

    location /downloads/ {
        add_header Cache-Control "no-cache" always;
        try_files $uri =404;
    }

    location / {
        add_header Cache-Control "no-cache" always;
        try_files $uri $uri/ =404;
    }

    location ~ (^|/)\\. {
        deny all;
    }
}
''', encoding="utf-8")
dynamic_path = management / "static-sites/traefik-dynamic/static-sites.yml"
dynamic = yaml.safe_load(dynamic_path.read_text())
for suffix, domain in [("", "privelto.com"), ("-www", "www.privelto.com")]:
    dynamic["http"]["routers"]["static-privelto" + suffix] = {
        "rule": f"Host(`{domain}`)", "priority": 100,
        "entryPoints": ["websecure"],
        "middlewares": (["privelto-www-redirect"] if suffix else []) + ["privelto-security"],
        "service": "static-sites", "tls": {"certResolver": "letsencrypt"},
    }
dynamic["http"]["middlewares"]["privelto-www-redirect"] = {"redirectRegex": {
    "regex": r"^https://www\.privelto\.com/(.*)", "replacement": "https://privelto.com/${1}", "permanent": True}}
dynamic["http"]["middlewares"]["privelto-security"] = {"headers": {
    "contentSecurityPolicy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; font-src 'self'; connect-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'; upgrade-insecure-requests",
    "referrerPolicy": "no-referrer", "contentTypeNosniff": True,
    "frameDeny": True, "stsSeconds": 31536000,
    "permissionsPolicy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
    "customResponseHeaders": {"X-XSS-Protection": "0", "Cross-Origin-Resource-Policy": "same-origin"},
}}
dynamic_path.write_text(yaml.safe_dump(dynamic, sort_keys=False), encoding="utf-8")
analytics_path = management / "web-analytics/router-domains.json"
analytics = json.loads(analytics_path.read_text())
analytics["static-privelto@file"] = "privelto.com"
analytics["static-privelto-www@file"] = "www.privelto.com"
analytics_path.write_text(json.dumps(analytics, indent=2) + "\n", encoding="utf-8")
inventory_path = Path("D:/gallego.top/inventory/services.yaml")
inventory = yaml.safe_load(inventory_path.read_text(encoding="utf-8"))
if not any(service["id"] == "privelto_static_site" for service in inventory["services"]):
    inventory["services"].append({"id": "privelto_static_site", "url": "https://privelto.com", "access": "public", "operational_state": "pending_publication", "source": "D:/Proyectos/herramientas/anonimato/website", "stack_path": "/opt/docker/stacks/static-sites"})
inventory_path.write_text(yaml.safe_dump(inventory, sort_keys=False, allow_unicode=True), encoding="utf-8")
print(f"Staged site: {site}")
