import os
import json
import secrets
from datetime import datetime, timedelta

from flask import Flask, request, jsonify, g, send_from_directory, make_response
from werkzeug.security import generate_password_hash, check_password_hash
import jwt
from flask_sock import Sock

from db import get_db, init_db, get_or_create_conversation

JWT_SECRET = os.environ.get("JWT_SECRET", secrets.token_hex(32))
JWT_ALGO = "HS256"
COOKIE_NAME = "token"

app = Flask(__name__, static_folder="static", static_url_path="")
sock = Sock(app)

init_db()

# userId -> list of open websocket connections (supports multiple tabs)
live_connections: dict[int, list] = {}


def make_token(user_id, username):
    payload = {
        "userId": user_id,
        "username": username,
        "exp": datetime.utcnow() + timedelta(days=30),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


def verify_token(token):
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
    except jwt.PyJWTError:
        return None


def current_user():
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    return verify_token(token)


def require_auth(f):
    from functools import wraps

    @wraps(f)
    def wrapper(*args, **kwargs):
        payload = current_user()
        if not payload:
            return jsonify({"error": "Not logged in"}), 401
        g.user_id = payload["userId"]
        g.username = payload["username"]
        return f(*args, **kwargs)

    return wrapper


# ---------------- Static frontend ----------------

@app.route("/")
def index():
    return send_from_directory("static", "index.html")


# ---------------- Auth ----------------

@app.route("/api/signup", methods=["POST"])
def signup():
    data = request.get_json(force=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    if len(username) < 2 or len(password) < 4:
        return jsonify({"error": "Username (2+ chars) and password (4+ chars) required"}), 400

    conn = get_db()
    existing = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
    if existing:
        conn.close()
        return jsonify({"error": "Username already taken"}), 409

    pw_hash = generate_password_hash(password)
    cur = conn.execute(
        "INSERT INTO users (username, password_hash) VALUES (?, ?)", (username, pw_hash)
    )
    conn.commit()
    user_id = cur.lastrowid
    conn.close()

    token = make_token(user_id, username)
    resp = make_response(jsonify({"id": user_id, "username": username}))
    resp.set_cookie(COOKIE_NAME, token, httponly=True, samesite="Lax",
                     max_age=30 * 24 * 3600)
    return resp


@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json(force=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()

    if not user or not check_password_hash(user["password_hash"], password):
        return jsonify({"error": "Invalid username or password"}), 401

    token = make_token(user["id"], user["username"])
    resp = make_response(jsonify({"id": user["id"], "username": user["username"]}))
    resp.set_cookie(COOKIE_NAME, token, httponly=True, samesite="Lax",
                     max_age=30 * 24 * 3600)
    return resp


@app.route("/api/logout", methods=["POST"])
def logout():
    resp = make_response(jsonify({"ok": True}))
    resp.delete_cookie(COOKIE_NAME)
    return resp


@app.route("/api/me")
@require_auth
def me():
    return jsonify({"id": g.user_id, "username": g.username})


# ---------------- Users ----------------

@app.route("/api/users")
@require_auth
def list_users():
    q = (request.args.get("q") or "").strip()
    conn = get_db()
    if q:
        rows = conn.execute(
            "SELECT id, username FROM users WHERE username LIKE ? AND id != ? LIMIT 20",
            (f"%{q}%", g.user_id),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, username FROM users WHERE id != ? LIMIT 50", (g.user_id,)
        ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


# ---------------- Conversations ----------------

@app.route("/api/conversations")
@require_auth
def list_conversations():
    conn = get_db()
    rows = conn.execute(
        """
        SELECT c.id as conversation_id,
               u.id as other_id, u.username as other_username,
               (SELECT text FROM messages WHERE conversation_id = c.id ORDER BY id DESC LIMIT 1) as last_text,
               (SELECT created_at FROM messages WHERE conversation_id = c.id ORDER BY id DESC LIMIT 1) as last_at,
               (SELECT COUNT(*) FROM messages WHERE conversation_id = c.id AND sender_id != ? AND read = 0) as unread
        FROM conversations c
        JOIN users u ON u.id = (CASE WHEN c.user_a = ? THEN c.user_b ELSE c.user_a END)
        WHERE c.user_a = ? OR c.user_b = ?
        ORDER BY last_at DESC
        """,
        (g.user_id, g.user_id, g.user_id, g.user_id),
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/conversations/start", methods=["POST"])
@require_auth
def start_conversation():
    data = request.get_json(force=True) or {}
    other_id = data.get("otherUserId")
    if not other_id or other_id == g.user_id:
        return jsonify({"error": "Invalid user"}), 400

    conn = get_db()
    other = conn.execute("SELECT id, username FROM users WHERE id = ?", (other_id,)).fetchone()
    if not other:
        conn.close()
        return jsonify({"error": "User not found"}), 404

    convo = get_or_create_conversation(conn, g.user_id, other_id)
    conn.close()
    return jsonify({
        "conversationId": convo["id"],
        "otherId": other["id"],
        "otherUsername": other["username"],
    })


@app.route("/api/conversations/<int:convo_id>/messages")
@require_auth
def get_messages(convo_id):
    conn = get_db()
    convo = conn.execute("SELECT * FROM conversations WHERE id = ?", (convo_id,)).fetchone()
    if not convo or g.user_id not in (convo["user_a"], convo["user_b"]):
        conn.close()
        return jsonify({"error": "Not your conversation"}), 403

    rows = conn.execute(
        "SELECT * FROM messages WHERE conversation_id = ? ORDER BY id ASC", (convo_id,)
    ).fetchall()
    conn.execute(
        "UPDATE messages SET read = 1 WHERE conversation_id = ? AND sender_id != ?",
        (convo_id, g.user_id),
    )
    conn.commit()
    conn.close()
    return jsonify([dict(r) for r in rows])


# ---------------- WebSocket ----------------

def send_to_user(user_id, payload):
    sockets = live_connections.get(user_id, [])
    dead = []
    for ws in sockets:
        try:
            ws.send(json.dumps(payload))
        except Exception:
            dead.append(ws)
    for d in dead:
        sockets.remove(d)


def broadcast_presence(user_id, online):
    payload = {"type": "presence", "userId": user_id, "online": online}
    for other_id, sockets in live_connections.items():
        if other_id == user_id:
            continue
        for ws in sockets:
            try:
                ws.send(json.dumps(payload))
            except Exception:
                pass


@sock.route("/ws")
def ws_handler(ws):
    token = request.cookies.get(COOKIE_NAME)
    payload = verify_token(token) if token else None
    if not payload:
        ws.close()
        return

    user_id = payload["userId"]
    username = payload["username"]

    live_connections.setdefault(user_id, []).append(ws)
    broadcast_presence(user_id, True)

    try:
        while True:
            raw = ws.receive()
            if raw is None:
                break
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue

            if data.get("type") == "message":
                convo_id = data.get("conversationId")
                text = (data.get("text") or "").strip()
                if not text:
                    continue

                conn = get_db()
                convo = conn.execute(
                    "SELECT * FROM conversations WHERE id = ?", (convo_id,)
                ).fetchone()
                if not convo or user_id not in (convo["user_a"], convo["user_b"]):
                    conn.close()
                    continue

                cur = conn.execute(
                    "INSERT INTO messages (conversation_id, sender_id, text) VALUES (?, ?, ?)",
                    (convo_id, user_id, text),
                )
                conn.commit()
                saved = conn.execute(
                    "SELECT * FROM messages WHERE id = ?", (cur.lastrowid,)
                ).fetchone()
                other_id = convo["user_b"] if convo["user_a"] == user_id else convo["user_a"]
                conn.close()

                msg_payload = {"type": "message", "message": dict(saved)}
                send_to_user(user_id, msg_payload)
                send_to_user(other_id, msg_payload)

            elif data.get("type") == "typing":
                convo_id = data.get("conversationId")
                conn = get_db()
                convo = conn.execute(
                    "SELECT * FROM conversations WHERE id = ?", (convo_id,)
                ).fetchone()
                conn.close()
                if not convo:
                    continue
                other_id = convo["user_b"] if convo["user_a"] == user_id else convo["user_a"]
                send_to_user(other_id, {
                    "type": "typing", "conversationId": convo_id, "username": username
                })
    finally:
        sockets = live_connections.get(user_id, [])
        if ws in sockets:
            sockets.remove(ws)
        if not sockets:
            live_connections.pop(user_id, None)
            broadcast_presence(user_id, False)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
