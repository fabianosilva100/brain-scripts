"""Base do canal Telegram do Brain. Token e chat_id vêm de ~/.brain/telegram.env
(fora do Drive) ou de variáveis de ambiente. Só biblioteca padrão."""
import json, os, re, urllib.error, urllib.request, urllib.parse
from pathlib import Path

ENV_FILE = Path.home() / ".brain" / "telegram.env"

def _load_env():
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

TOKEN_RE = re.compile(r"\d{8,10}:[A-Za-z0-9_-]{35}")

def token():
    _load_env()
    t = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip().strip('"').strip("'")
    if not t or t.startswith("COLE_"):
        raise SystemExit(f"Token ausente. Preencha TELEGRAM_BOT_TOKEN em {ENV_FILE}")
    if not TOKEN_RE.fullmatch(t):
        bad = sorted({c for c in t if not (c.isalnum() or c in "_-:")})
        raise SystemExit(
            f"Token com formato inválido (esperado: 8-10 dígitos, ':', 35 caracteres). "
            f"Caracteres estranhos: {bad or 'nenhum'}. "
            f"Recopie do BotFather (/mybots → bot → API Token) e cole de novo em {ENV_FILE}")
    return t

def chat_id():
    _load_env()
    c = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not c:
        raise SystemExit(f"chat_id ausente. Rode telegram_chat_id.py e preencha em {ENV_FILE}")
    return c

def api(method, data=None):
    url = f"https://api.telegram.org/bot{token()}/{method}"
    body = urllib.parse.urlencode(data).encode() if data else None
    try:
        with urllib.request.urlopen(url, body, timeout=30) as r:
            out = json.load(r)
    except urllib.error.HTTPError as e:
        if e.code in (401, 404):
            raise SystemExit(f"Telegram respondeu {e.code}: token inválido. Recopie do BotFather e cole em {ENV_FILE}")
        raise SystemExit(f"Telegram respondeu {e.code}: {e.read().decode(errors='replace')[:300]}")
    except urllib.error.URLError as e:
        raise SystemExit(f"Sem conexão com api.telegram.org: {e.reason}")
    if not out.get("ok"):
        raise SystemExit(f"Telegram: {out}")
    return out["result"]
