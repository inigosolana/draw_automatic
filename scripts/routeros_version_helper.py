#!/usr/bin/env python3
"""Helper de host para consultar la versión de RouterOS de un router.

Por qué existe: la app draw_automatic corre en un contenedor Docker en una red
bridge aislada y NO tiene ruta hacia los routers. Quien SÍ los alcanza es el
propio host, a través del túnel WireGuard `wg-mikrotik-api`: el policy-routing
del host marca el tráfico TCP a :8728 (fwmark 0x8728) y lo saca por el túnel,
usando como origen la IP del túnel (10.10.10.3). Es el mismo camino que usa NOP
para hablar con los routers (no tocamos NOP: solo reutilizamos el túnel del host).

Este servicio se ejecuta EN EL HOST (uid con acceso al túnel), abre la API de
RouterOS (puerto 8728) ligando el socket a la IP del túnel, hace login y lee
`/system/resource` para devolver la versión. La app (contenedor) lo llama por
HTTP a través del gateway de su red bridge (regla ufw dedicada).

Solo lee `/system/resource/print`: no modifica nada en el router.
"""
from __future__ import annotations

import hashlib
import json
import os
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

WG_SOURCE_ADDR = os.environ.get("ROUTEROS_WG_SOURCE_ADDR", "10.10.10.3").strip()
DEFAULT_API_PORT = int(os.environ.get("ROUTEROS_API_PORT", "8728"))
CONNECT_TIMEOUT = float(os.environ.get("ROUTEROS_TIMEOUT_S", "8"))
HELPER_BIND = os.environ.get("ROUTEROS_HELPER_BIND", "172.28.0.1").strip()
HELPER_PORT = int(os.environ.get("ROUTEROS_HELPER_PORT", "49500"))
# Token compartido: el contenedor lo envía en la cabecera X-Helper-Token.
# El servicio acepta credenciales+host arbitrarios, así que se protege con ufw
# (solo la subred del contenedor) y con este token.
HELPER_TOKEN = os.environ.get("ROUTEROS_HELPER_TOKEN", "").strip()
if not HELPER_TOKEN:
    print("[SEGURIDAD] ROUTEROS_HELPER_TOKEN vacío: el sidecar NO exige token. "
          "Define ROUTEROS_HELPER_TOKEN (y el mismo valor en la app).", flush=True)


class RouterOsError(RuntimeError):
    pass


def _encode_len(n: int) -> bytes:
    if n < 0x80:
        return bytes([n])
    if n < 0x4000:
        return bytes([(n >> 8) | 0x80, n & 0xFF])
    if n < 0x200000:
        return bytes([(n >> 16) | 0xC0, (n >> 8) & 0xFF, n & 0xFF])
    if n < 0x10000000:
        return bytes([(n >> 24) | 0xE0, (n >> 16) & 0xFF, (n >> 8) & 0xFF, n & 0xFF])
    return bytes([0xF0, (n >> 24) & 0xFF, (n >> 16) & 0xFF, (n >> 8) & 0xFF, n & 0xFF])


class RouterOsClient:
    """Cliente mínimo del protocolo binario de la API de RouterOS."""

    def __init__(self, host: str, port: int = DEFAULT_API_PORT, *,
                 source_addr: str = WG_SOURCE_ADDR, timeout: float = CONNECT_TIMEOUT):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if source_addr:
            self.sock.bind((source_addr, 0))
        self.sock.settimeout(timeout)
        self.sock.connect((host, port))

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass

    def _write_word(self, word: str) -> None:
        raw = word.encode("utf-8")
        self.sock.sendall(_encode_len(len(raw)) + raw)

    def send(self, *words: str) -> None:
        for word in words:
            self._write_word(word)
        self.sock.sendall(b"\x00")

    def _recv_exact(self, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise RouterOsError("Conexión RouterOS cerrada durante la lectura.")
            buf += chunk
        return buf

    def _read_len(self) -> int:
        c = self._recv_exact(1)[0]
        if c < 0x80:
            return c
        if c < 0xC0:
            return ((c & 0x3F) << 8) + self._recv_exact(1)[0]
        if c < 0xE0:
            b = self._recv_exact(2)
            return ((c & 0x1F) << 16) + (b[0] << 8) + b[1]
        if c < 0xF0:
            b = self._recv_exact(3)
            return ((c & 0x0F) << 24) + (b[0] << 16) + (b[1] << 8) + b[2]
        b = self._recv_exact(4)
        return (b[0] << 24) + (b[1] << 16) + (b[2] << 8) + b[3]

    def _read_word(self) -> str:
        n = self._read_len()
        if n == 0:
            return ""
        return self._recv_exact(n).decode("utf-8", errors="replace")

    def read_sentences(self) -> list[list[str]]:
        sentences: list[list[str]] = []
        while True:
            words: list[str] = []
            while True:
                w = self._read_word()
                if w == "":
                    break
                words.append(w)
            sentences.append(words)
            if words and words[0] in ("!done", "!fatal"):
                break
        return sentences

    def login(self, username: str, password: str) -> None:
        # RouterOS >= 6.43: login en texto plano en una sola sentencia.
        self.send("/login", f"=name={username}", f"=password={password}")
        reply = self.read_sentences()
        if self._has_trap(reply):
            # RouterOS < 6.43: challenge-response MD5.
            challenge = self._extract(reply, "=ret=")
            if not challenge:
                self.send("/login")
                reply = self.read_sentences()
                challenge = self._extract(reply, "=ret=")
            if not challenge:
                raise RouterOsError("Login rechazado por el router (credenciales o API deshabilitada).")
            digest = hashlib.md5()
            digest.update(b"\x00")
            digest.update(password.encode("utf-8"))
            digest.update(bytes.fromhex(challenge))
            response = "00" + digest.hexdigest()
            self.send("/login", f"=name={username}", f"=response={response}")
            reply = self.read_sentences()
            if self._has_trap(reply):
                raise RouterOsError("Login rechazado (challenge MD5): revisa usuario/contraseña.")

    def system_resource(self) -> dict[str, str]:
        self.send("/system/resource/print")
        fields: dict[str, str] = {}
        for sentence in self.read_sentences():
            for word in sentence:
                if word.startswith("=") and "=" in word[1:]:
                    key, _, value = word[1:].partition("=")
                    fields[key] = value
        return fields

    @staticmethod
    def _has_trap(sentences: list[list[str]]) -> bool:
        return any(s and s[0] in ("!trap", "!fatal") for s in sentences)

    @staticmethod
    def _extract(sentences: list[list[str]], prefix: str) -> str:
        for s in sentences:
            for word in s:
                if word.startswith(prefix):
                    return word[len(prefix):]
        return ""


def major_version(version: str) -> int | None:
    """Devuelve el major (6, 7...) a partir de '6.49.20 (long-term)' etc."""
    digits = ""
    for ch in version.strip():
        if ch.isdigit():
            digits += ch
        else:
            break
    return int(digits) if digits else None


def get_router_version(host: str, username: str, password: str,
                        port: int = DEFAULT_API_PORT) -> dict:
    client = RouterOsClient(host, port)
    try:
        client.login(username, password)
        res = client.system_resource()
    finally:
        client.close()
    version = res.get("version", "").strip()
    major = major_version(version)
    return {
        "ok": True,
        "version": version,
        "major": major,
        "is_v7": (major is not None and major >= 7),
        "board": res.get("board-name", "").strip(),
        "platform": res.get("platform", "").strip(),
    }


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # silencio: sin volcar credenciales a stdout
        pass

    def do_GET(self):
        if self.path.rstrip("/") == "/health":
            self._json(200, {"ok": True, "service": "routeros-version-helper"})
        else:
            self._json(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        if self.path.rstrip("/") != "/routeros/version":
            self._json(404, {"ok": False, "error": "not found"})
            return
        if HELPER_TOKEN and self.headers.get("X-Helper-Token", "") != HELPER_TOKEN:
            self._json(401, {"ok": False, "error": "token inválido"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            data = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        except (ValueError, json.JSONDecodeError):
            self._json(400, {"ok": False, "error": "JSON inválido"})
            return
        host = str(data.get("host", "")).strip()
        username = str(data.get("username", "")).strip()
        password = str(data.get("password", ""))
        port = DEFAULT_API_PORT  # puerto API fijo (8728); no aceptar puerto del cliente (anti-SSRF)
        if not host or not username or not password:
            self._json(400, {"ok": False, "error": "faltan host/username/password"})
            return
        try:
            self._json(200, get_router_version(host, username, password, port))
        except (OSError, RouterOsError) as exc:
            self._json(502, {"ok": False, "error": str(exc)})


def main() -> None:
    server = ThreadingHTTPServer((HELPER_BIND, HELPER_PORT), Handler)
    print(f"routeros-version-helper escuchando en {HELPER_BIND}:{HELPER_PORT} "
          f"(origen túnel {WG_SOURCE_ADDR}, API {DEFAULT_API_PORT})", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
