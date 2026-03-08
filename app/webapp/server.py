from __future__ import annotations

from contextlib import contextmanager
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from app.agent import answer_question
from app.core.config import load_settings
from app.inspection.dashboard import build_dashboard_payload
from app.notion.sync import sync_notion
from app.retrieval.tools import list_recent_pages, search_local_notion
from app.storage.db import connect, init_db


STATIC_DIR = Path(__file__).resolve().parent.parent / "web"


def run_server(host: str = "127.0.0.1", port: int = 8000) -> None:
    server = ThreadingHTTPServer((host, port), OhMyNotionHandler)
    print(f"Oh My Notion web app running at http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
    finally:
        server.server_close()


class OhMyNotionHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._serve_file("index.html", "text/html; charset=utf-8")
            return
        if parsed.path == "/styles.css":
            self._serve_file("styles.css", "text/css; charset=utf-8")
            return
        if parsed.path == "/app.js":
            self._serve_file("app.js", "application/javascript; charset=utf-8")
            return
        if parsed.path == "/api/health":
            self._send_json({"ok": True})
            return
        if parsed.path == "/api/recent":
            self._handle_recent(parsed.query)
            return
        if parsed.path == "/api/dashboard":
            self._handle_dashboard()
            return
        if parsed.path == "/api/search":
            self._handle_search(parsed.query)
            return
        if parsed.path == "/api/ask":
            self._handle_ask(parsed.query)
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/sync":
            self._handle_sync()
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def log_message(self, format: str, *args) -> None:
        return

    def _handle_recent(self, query_string: str) -> None:
        params = parse_qs(query_string)
        limit = safe_int(params.get("limit", ["10"])[0], default=10)
        with app_connection() as connection:
            rows = list_recent_pages(connection, limit=limit)
        payload = [
            {
                "id": row["id"],
                "title": row["title"],
                "url": row["url"],
                "last_edited_time": row["last_edited_time"],
            }
            for row in rows
        ]
        self._send_json(payload)

    def _handle_dashboard(self) -> None:
        settings = load_settings()
        raw_snapshots = len(list(settings.raw_dir.glob("*.json")))
        with app_connection() as connection:
            payload = build_dashboard_payload(connection, raw_snapshots=raw_snapshots)
        self._send_json(payload)

    def _handle_search(self, query_string: str) -> None:
        params = parse_qs(query_string)
        query = params.get("q", [""])[0].strip()
        top_k = safe_int(params.get("top_k", ["6"])[0], default=6)
        if not query:
            self._send_json({"error": "Missing q parameter."}, status=HTTPStatus.BAD_REQUEST)
            return

        with app_connection() as connection:
            results = search_local_notion(connection, query=query, top_k=top_k)

        payload = [
            {
                "page_id": result.page_id,
                "chunk_id": result.chunk_id,
                "title": result.title,
                "heading": result.heading,
                "content": result.content,
                "url": result.url,
                "rank": result.rank,
                "fts_score": result.fts_score,
                "vector_score": result.vector_score,
                "rerank_score": result.rerank_score,
                "retrieval_method": result.retrieval_method,
            }
            for result in results
        ]
        self._send_json(payload)

    def _handle_ask(self, query_string: str) -> None:
        params = parse_qs(query_string)
        question = params.get("q", [""])[0].strip()
        top_k = safe_int(params.get("top_k", ["5"])[0], default=5)
        if not question:
            self._send_json({"error": "Missing q parameter."}, status=HTTPStatus.BAD_REQUEST)
            return

        with app_connection() as connection:
            settings = load_settings()
            answer = answer_question(connection, settings=settings, question=question, top_k=top_k)
            evidence = search_local_notion(connection, query=question, top_k=top_k)

        self._send_json(
            {
                "question": question,
                "answer": answer,
                "evidence": [
                    {
                        "title": item.title,
                        "heading": item.heading,
                        "content": item.content,
                        "url": item.url,
                    }
                    for item in evidence
                ],
            }
        )

    def _handle_sync(self) -> None:
        settings = load_settings()
        with app_connection() as connection:
            message = sync_notion(settings, connection)
        self._send_json({"message": message})

    def _serve_file(self, filename: str, content_type: str) -> None:
        file_path = STATIC_DIR / filename
        if not file_path.exists():
            self.send_error(HTTPStatus.NOT_FOUND, "Static asset not found")
            return
        body = file_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, payload: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

@contextmanager
def app_connection():
    settings = load_settings()
    connection = connect(settings.db_path)
    init_db(connection)
    try:
        yield connection
    finally:
        connection.close()


def safe_int(value: str, default: int) -> int:
    try:
        return int(value)
    except ValueError:
        return default
