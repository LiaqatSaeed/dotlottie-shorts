#!/usr/bin/env python3
"""
Static file server (same as plain `python3 -m http.server`) plus one extra
endpoint: POST /save?name=<filename> writes the request body to dist/<filename>.
Used by docs/export.html to hand back a recorded video/audio blob without
needing filesystem downloads (which are OS-sandboxed in this environment).
"""
import http.server
import json
import socketserver
import sys
import tempfile
import traceback
import urllib.parse
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DIST_DIR = REPO_ROOT / "dist"

sys.path.insert(0, str(REPO_ROOT / "src"))

# Small catalog so the browser can say "wave" instead of a repo-relative
# path - add an entry here for any character you want the /speak endpoint
# to offer, including ones adapted from third-party .lottie files.
SPEAK_TEMPLATES = {
    "wave": "templates/characters/wave-character.json",
    "nod": "templates/characters/nod-character.json",
    "point": "templates/characters/point-character.json",
    "your-character": "external-refs/character-speaking.json",
}


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(REPO_ROOT), **kwargs)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/speak":
            self.handle_speak()
            return
        if parsed.path != "/save":
            self.send_response(404)
            self.end_headers()
            return

        query = urllib.parse.parse_qs(parsed.query)
        name = query.get("name", [None])[0]
        if not name or "/" in name or ".." in name:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"bad or missing 'name' query param")
            return

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)

        DIST_DIR.mkdir(parents=True, exist_ok=True)
        out_path = DIST_DIR / name
        out_path.write_bytes(body)

        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(f"saved {len(body)} bytes to {out_path}".encode())

    def handle_speak(self):
        """POST /speak with a JSON body {text, template, voiceEngine?, voice?}
        composes a fresh one-scene .lottie on the spot and returns its bytes -
        the live "type a phrase, character speaks it" feature."""
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length))
            text = body["text"].strip()
            template_key = body.get("template", "wave")
            if not text:
                raise ValueError("empty text")
            if template_key not in SPEAK_TEMPLATES:
                raise ValueError(f"unknown template '{template_key}' - must be one of {list(SPEAK_TEMPLATES)}")

            from build_short import compose, package_dotlottie  # local import: only needed for this endpoint

            plan = {
                "animationId": "speak",
                "aspectRatio": body.get("aspectRatio", "1:1"),
                "scenes": [{
                    "label": "speak",
                    "template": SPEAK_TEMPLATES[template_key],
                    "narration": text,
                }],
            }
            combined = compose(
                plan,
                voice_engine=body.get("voiceEngine", "kokoro"),
                voice=body.get("voice"),
            )
            with tempfile.NamedTemporaryFile(suffix=".lottie") as tmp:
                package_dotlottie(combined, "speak", tmp.name)
                lottie_bytes = Path(tmp.name).read_bytes()

            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.end_headers()
            self.wfile.write(lottie_bytes)
        except Exception as e:
            traceback.print_exc()
            self.send_response(500)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(str(e).encode())

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8743
    with socketserver.TCPServer(("", port), Handler) as httpd:
        print(f"Serving {REPO_ROOT} on port {port} (POST /save?name=... enabled)")
        httpd.serve_forever()
