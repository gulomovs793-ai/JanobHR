import base64
from pathlib import Path

root = Path(__file__).parent
html = (root / "index.html").read_text(encoding="utf-8")
css = (root / "app.css").read_text(encoding="utf-8")
js = (root / "app.js").read_text(encoding="utf-8")
# ChatGPT fayl ko'rish oynasi HTML'ni blob: manzilda ochadi. Mustaqil demo
# hech qachon jonli API'ga murojaat qilmasligi uchun rejimni majburan yoqamiz.
js = js.replace(
    "const previewMode = location.protocol === 'file:' || ['localhost', '127.0.0.1'].includes(location.hostname);",
    "const previewMode = true;",
)

html = html.replace('<link rel="stylesheet" href="/miniapp-assets/app.css">', f"<style>{css}</style>")
html = html.replace('<script src="https://telegram.org/js/telegram-web-app.js"></script>', "")
html = html.replace('<script src="/miniapp-assets/app.js" defer></script>', f"<script>{js}</script>")
html = html.replace("__TENANT_ID__", "1")
logo_path = root / "logo.png"
if logo_path.exists():
    logo_data = base64.b64encode(logo_path.read_bytes()).decode("ascii")
    html = html.replace("/miniapp-assets/logo.png", f"data:image/png;base64,{logo_data}")

(root.parent / "JanobHR-Mini-App-Demo.html").write_text(html, encoding="utf-8")
