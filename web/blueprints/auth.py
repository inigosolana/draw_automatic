from __future__ import annotations

from flask import Blueprint, Response, redirect, render_template, request, session, url_for
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from app_context import security_logger
from generator.glpi_client import GlpiClient, GlpiError
from generator.utils import is_safe_redirect


def create_auth_blueprint(limiter: Limiter) -> Blueprint:
    bp = Blueprint("auth", __name__)

    @bp.route("/login", methods=["GET", "POST"])
    @limiter.limit("10 per minute")
    def login() -> str:
        error = ""
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            client_ip = get_remote_address()

            client = GlpiClient.from_environment()
            if not client:
                error = "El acceso no esta disponible en este momento."
                security_logger.warning(f"Login attempt failed: GLPI not configured (IP: {client_ip})")
            elif not username or not password:
                error = "Introduce usuario y clave de acceso."
                security_logger.warning(f"Login attempt failed: empty credentials (IP: {client_ip})")
            else:
                try:
                    session.clear()
                    session["technician"] = client.authenticate_user(username, password)
                    session.permanent = True
                    security_logger.info(f"Login successful: user={username}, IP={client_ip}")
                    next_url = request.args.get("next", "")
                    return redirect(next_url if is_safe_redirect(next_url) else url_for("home.index"))
                except GlpiError:
                    error = "Usuario o clave incorrectos."
                    security_logger.warning(
                        f"Login attempt failed: invalid credentials for user={username}, IP={client_ip}"
                    )
        return render_template("login.html", error=error)

    @bp.get("/logout")
    def logout_get() -> Response:
        return redirect(url_for("auth.login"))

    @bp.post("/logout")
    def logout() -> Response:
        username = session.get("technician", {}).get("username", "unknown")
        client_ip = get_remote_address()
        session.clear()
        security_logger.info(f"Logout: user={username}, IP={client_ip}")
        return redirect(url_for("auth.login"))

    return bp
