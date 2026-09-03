from pathlib import Path


def replace_once(path: str, old: str, new: str, label: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"{label}: anchor not found in {path}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


# 1) Frontend: robust Telegram initData acquisition + multiple safe transports.
replace_once(
    "miniapp/app.js",
    """  const tg = window.Telegram?.WebApp;\n  const tenant = document.body.dataset.tenant;\n  const initData = tg?.initData || '';\n  const previewMode = location.protocol === 'file:' || ['localhost', '127.0.0.1'].includes(location.hostname);\n""",
    """  const tg = window.Telegram?.WebApp;\n  const tenant = document.body.dataset.tenant;\n  let initData = tg?.initData || '';\n  const previewMode = location.protocol === 'file:' || ['localhost', '127.0.0.1'].includes(location.hostname);\n\n  function initDataFromLocation(){\n    for(const source of [location.hash.replace(/^#/, ''), location.search.replace(/^\\?/, '')]){\n      if(!source) continue;\n      const params = new URLSearchParams(source);\n      const value = params.get('tgWebAppData');\n      if(value) return value;\n    }\n    return '';\n  }\n  function persistInitData(value){\n    if(!value || previewMode) return;\n    try{\n      document.cookie = `jh_tg_init=${encodeURIComponent(value)}; Path=/; Max-Age=3600; Secure; SameSite=Lax`;\n    }catch{}\n  }\n  async function ensureInitData(){\n    if(previewMode) return '';\n    if(initData){ persistInitData(initData); return initData; }\n    const deadline = Date.now() + 1800;\n    while(Date.now() < deadline){\n      initData = window.Telegram?.WebApp?.initData || initDataFromLocation() || '';\n      if(initData){ persistInitData(initData); return initData; }\n      await new Promise(resolve => setTimeout(resolve, 60));\n    }\n    return '';\n  }\n  function authHeaders(extra={}){\n    const headers = {'Content-Type':'application/json', ...extra};\n    if(initData){\n      headers['X-Telegram-Init-Data'] = initData;\n      headers['Authorization'] = `tma ${initData}`;\n    }\n    return headers;\n  }\n  window.JanobHRAuth = {ensure:ensureInitData, headers:authHeaders, get:()=>initData};\n""",
    "frontend auth bootstrap",
)
replace_once(
    "miniapp/app.js",
    """    const response = await fetch(`/api/miniapp/${tenant}${path}`, {...options, headers:{'Content-Type':'application/json','X-Telegram-Init-Data':initData,...options.headers}});\n""",
    """    await ensureInitData();\n    const response = await fetch(`/api/miniapp/${tenant}${path}`, {...options, headers:authHeaders(options.headers||{})});\n""",
    "frontend api auth",
)
replace_once(
    "miniapp/app.js",
    """  async function exportVacancy(key,title){if(previewMode){toast('Demo rejimida Excel eksport tayyor');return;}try{const response=await fetch(`/api/miniapp/${tenant}/vacancies/${encodeURIComponent(key)}/export`,{headers:{'X-Telegram-Init-Data':initData}});if(!response.ok)throw new Error((await response.text())||'Eksport xatosi');""",
    """  async function exportVacancy(key,title){if(previewMode){toast('Demo rejimida Excel eksport tayyor');return;}try{await ensureInitData();const response=await fetch(`/api/miniapp/${tenant}/vacancies/${encodeURIComponent(key)}/export`,{headers:authHeaders()});if(!response.ok)throw new Error((await response.text())||'Eksport xatosi');""",
    "export auth",
)
replace_once(
    "miniapp/app.js",
    """  tg?.ready();tg?.expand();tg?.setHeaderColor?.('#f5f5f7');tg?.setBackgroundColor?.('#f5f5f7');\n  if(!initData&&!previewMode){fail(new Error('Mini Appni kompaniyangizning Admin botidagi “Boshqaruv paneli” tugmasidan oching.'));}else{loadDashboard();}\n""",
    """  tg?.ready();tg?.expand();tg?.setHeaderColor?.('#f5f5f7');tg?.setBackgroundColor?.('#f5f5f7');\n  (async()=>{\n    await ensureInitData();\n    if(!initData&&!previewMode){fail(new Error('Telegram sessiyasi olinmadi. Admin botdagi “Boshqaruv paneli” menu tugmasini yopib, qayta bosing.'));}\n    else{loadDashboard();}\n  })();\n""",
    "frontend boot auth",
)

# Secondary UI also waits for the shared auth helper instead of capturing an empty value forever.
replace_once(
    "miniapp/janobhr2.js",
    """  const initData = tg?.initData || '';\n""",
    """  let initData = tg?.initData || '';\n""",
    "secondary init variable",
)
replace_once(
    "miniapp/janobhr2.js",
    """    const response = await fetch(`/api/miniapp/${tenant}${path}`, {\n      ...options,\n      headers: {'Content-Type':'application/json','X-Telegram-Init-Data':initData,...options.headers}\n    });\n""",
    """    if(window.JanobHRAuth?.ensure) initData = await window.JanobHRAuth.ensure();\n    const headers = window.JanobHRAuth?.headers\n      ? window.JanobHRAuth.headers(options.headers||{})\n      : {'Content-Type':'application/json', ...(initData?{'X-Telegram-Init-Data':initData,'Authorization':`tma ${initData}`}:{ }), ...options.headers};\n    const response = await fetch(`/api/miniapp/${tenant}${path}`, {\n      ...options,\n      headers\n    });\n""",
    "secondary api auth",
)

# 2) Server: accept the same Telegram credential from header, standard auth,
# or a same-origin short-lived cookie. Signature verification is unchanged.
replace_once(
    "miniapp_api.py",
    """from urllib.parse import parse_qsl\n""",
    """from urllib.parse import parse_qsl, unquote\n""",
    "server url imports",
)
replace_once(
    "miniapp_api.py",
    """async def _authorize(request: web.Request) -> tuple[dict, dict]:\n""",
    """def _request_init_data(request: web.Request) -> str:\n    value = (request.headers.get(\"X-Telegram-Init-Data\") or \"\").strip()\n    if value:\n        return value\n    authorization = (request.headers.get(\"Authorization\") or \"\").strip()\n    if authorization.lower().startswith(\"tma \"):\n        value = authorization[4:].strip()\n        if value:\n            return value\n    cookie = request.cookies.get(\"jh_tg_init\") or \"\"\n    if cookie:\n        try:\n            return unquote(cookie).strip()\n        except Exception:\n            return \"\"\n    return \"\"\n\n\nasync def _authorize(request: web.Request) -> tuple[dict, dict]:\n""",
    "server auth extractor",
)
replace_once(
    "miniapp_api.py",
    """    auth = verify_init_data(\n        request.headers.get(\"X-Telegram-Init-Data\", \"\"), tenant[\"admin_bot_token\"]\n    )\n""",
    """    auth = verify_init_data(_request_init_data(request), tenant[\"admin_bot_token\"])\n""",
    "server auth use",
)

# 3) Configure a chat-specific menu button for every admin, not only the
# global default. This makes Telegram launch it in the actual private chat
# context that owns the admin user.
replace_once(
    "webhook_app.py",
    """    try:\n        await admin_bot.set_chat_menu_button(\n            menu_button=MenuButtonWebApp(\n                text=\"Boshqaruv paneli\",\n                web_app=WebAppInfo(url=f\"{miniapp_base}/{tenant['id']}\"),\n            )\n        )\n    finally:\n        await admin_bot.session.close()\n""",
    """    try:\n        menu_button = MenuButtonWebApp(\n            text=\"Boshqaruv paneli\",\n            web_app=WebAppInfo(url=f\"{miniapp_base}/{tenant['id']}\"),\n        )\n        # Keep a default for future admins, but explicitly bind the button to\n        # every known private admin chat as well. Telegram's Bot API supports\n        # per-chat menu buttons and this preserves the correct user context.\n        await admin_bot.set_chat_menu_button(menu_button=menu_button)\n        for admin_id in tenant.get(\"admin_user_ids\", []):\n            try:\n                await admin_bot.set_chat_menu_button(\n                    chat_id=admin_id, menu_button=menu_button\n                )\n            except Exception:\n                logger.exception(\n                    \"Admin Mini App menu tugmasi chatga ulanmagan: tenant_id=%s admin_id=%s\",\n                    tenant.get(\"id\"), admin_id,\n                )\n    finally:\n        await admin_bot.session.close()\n""",
    "chat-specific menu button",
)

# Bust Telegram WebView cache so the repaired JS is loaded immediately.
replace_once(
    "miniapp/index.html",
    """  <script src=\"/miniapp-assets/app.js\" defer></script>\n  <script src=\"/miniapp-assets/janobhr2.js\" defer></script>\n""",
    """  <script src=\"/miniapp-assets/app.js?v=auth3\" defer></script>\n  <script src=\"/miniapp-assets/janobhr2.js?v=auth3\" defer></script>\n""",
    "cache bust",
)
