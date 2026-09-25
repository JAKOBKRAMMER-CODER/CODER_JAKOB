# Threadline (Python + HTML)

A real multi-user messaging app: accounts, hashed passwords, SQLite storage, and real-time delivery over WebSockets — built with Flask (backend) and plain HTML/CSS/JS (frontend), no frontend framework.

## Run it locally

Requires Python 3.9+.

```bash
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
python3 server.py
```

Then open **http://localhost:5000** in your browser.

Open it in two different browsers (or one normal + one incognito window) to sign up as two different users and message each other live.

## What's real here

- Accounts with bcrypt-style hashed passwords (via Werkzeug), sessions via JWT cookie
- Messages persisted in SQLite (`data/threadline.db`) — survive a server restart
- Real-time delivery over WebSockets (via flask-sock) — no polling, no fake replies
- Online/offline presence and a typing indicator
- Search any username on the server to start a new conversation with them

## What's NOT included (yet)

- No message encryption (not end-to-end encrypted like real WhatsApp)
- No media/file attachments, only text
- No group chats, only 1:1
- No push notifications when the tab/browser is closed
- The built-in Flask server is for development only — see below for production

## Running in production

`python3 server.py` uses Flask's built-in dev server, which is not meant for production traffic. For real deployment, run it behind a proper WSGI/ASGI server that supports WebSockets, for example:

```bash
pip install gunicorn eventlet
gunicorn -k eventlet -w 1 server:app
```

Also set a real `JWT_SECRET` environment variable (a long random string) rather than relying on the auto-generated one, since that one changes every restart and would log everyone out.

Good hosts for this: [Render](https://render.com), [Fly.io](https://fly.io), [Railway](https://railway.app), or a basic VPS.

## Project structure

```
server.py         Flask app: auth, REST API, WebSocket handling
db.py              SQLite schema and setup
static/
  index.html       Login/signup + chat UI markup
  style.css         Styling
  app.js            Frontend logic: auth, contacts, live messaging
requirements.txt   Python dependencies
```
