"""Single-admin authentication for the VoWiFi control plane."""
from __future__ import annotations
import hashlib, hmac, json, os, secrets, threading, time
from . import config as cfg

AUTH_PATH = os.path.join(cfg.DATA_DIR, "auth.json")
SESSION_COOKIE = "vowifi_session"
SESSION_TTL = 12 * 60 * 60
_sessions = {}
_failures = {}
_lock = threading.RLock()

def _read():
    try:
        with open(AUTH_PATH, encoding="utf-8") as f: v=json.load(f)
        return v if isinstance(v, dict) else {}
    except Exception: return {}

def configured():
    d=_read(); return bool(d.get("salt") and d.get("password_hash"))

def username(): return str(_read().get("username") or "admin")

def _derive(password, salt):
    return hashlib.scrypt(password.encode(), salt=salt, n=2**15, r=8, p=1, dklen=32, maxmem=64*1024*1024)

def setup(password, username="admin"):
    if configured(): raise ValueError("administrator account is already configured")
    if not 10 <= len(password) <= 256: raise ValueError("password must contain 10-256 characters")
    username=str(username or "admin").strip()
    if not username or len(username)>64: raise ValueError("username must contain 1-64 characters")
    salt=secrets.token_bytes(16)
    data={"version":1,"username":username,"salt":salt.hex(),"password_hash":_derive(password,salt).hex(),"created_at":int(time.time())}
    os.makedirs(cfg.DATA_DIR, exist_ok=True)
    tmp=AUTH_PATH+".tmp"
    with open(tmp,"w",encoding="utf-8") as f: json.dump(data,f,indent=2)
    os.chmod(tmp,0o600); os.replace(tmp,AUTH_PATH)

def throttled(peer):
    now=time.time()
    with _lock:
        xs=[x for x in _failures.get(peer,[]) if now-x<900]; _failures[peer]=xs
    return max(0,60-int(now-xs[-1])) if len(xs)>=5 else 0

def login(user,password,peer):
    d=_read()
    try: valid=hmac.compare_digest(_derive(password,bytes.fromhex(d["salt"])),bytes.fromhex(d["password_hash"])) and hmac.compare_digest(str(user),str(d.get("username") or "admin"))
    except Exception: valid=False
    with _lock:
        if not valid:
            _failures.setdefault(peer,[]).append(time.time()); return None
        _failures.pop(peer,None); token=secrets.token_urlsafe(32); csrf=secrets.token_urlsafe(24)
        _sessions[token]={"csrf":csrf,"expires":time.time()+SESSION_TTL}; return token,csrf

def session(token):
    if not token: return None
    with _lock:
        s=_sessions.get(token)
        if not s or s["expires"]<time.time(): _sessions.pop(token,None); return None
        s["expires"]=time.time()+SESSION_TTL; return dict(s)

def logout(token):
    with _lock: _sessions.pop(token,None)

def change_password(current,new):
    if not 10<=len(new)<=256: raise ValueError("new password must contain 10-256 characters")
    d=_read()
    try: ok=hmac.compare_digest(_derive(current,bytes.fromhex(d["salt"])),bytes.fromhex(d["password_hash"]))
    except Exception: ok=False
    if not ok: raise ValueError("current password is incorrect")
    salt=secrets.token_bytes(16); d.update(salt=salt.hex(),password_hash=_derive(new,salt).hex(),changed_at=int(time.time()))
    tmp=AUTH_PATH+".tmp"
    with open(tmp,"w",encoding="utf-8") as f: json.dump(d,f,indent=2)
    os.chmod(tmp,0o600); os.replace(tmp,AUTH_PATH)
    with _lock: _sessions.clear()
