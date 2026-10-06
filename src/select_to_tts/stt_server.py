"""Local-only, OpenAI-shaped HTTP adapter for subscription STT.

Run python -m select_to_tts.stt_server. The private connection URL is written
to %LOCALAPPDATA%/select-to-tts/stt-connection.json, never logged.
"""
import argparse
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import queue
import secrets
import socket
import threading

from .stt import BusyError, MAX_BYTES, MODEL, transcribe

MAX_BODY = MAX_BYTES + 65536


def parse_form(content_type, body):
    if not content_type or len(content_type) > 1024 or "\r" in content_type or "\n" in content_type:
        raise ValueError("Expected multipart/form-data")
    message = BytesParser(policy=policy.default).parsebytes(
        b"Content-Type: " + content_type.encode("ascii") + b"\r\nMIME-Version: 1.0\r\n\r\n" + body)
    if message.get_content_type() != "multipart/form-data" or not message.is_multipart() or message.defects:
        raise ValueError("Invalid multipart/form-data")
    fields = {}
    for part in message.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if name not in {"file", "model", "language", "prompt", "response_format"} or name in fields:
            raise ValueError("Unknown or duplicate form field")
        if part.is_multipart() or part.defects or part.get("Content-Transfer-Encoding"):
            raise ValueError("Invalid form part")
        data = part.get_payload(decode=True)
        if name == "file":
            if not data or len(data) > MAX_BYTES:
                raise ValueError("File must be nonempty and at most 25 MiB")
            fields[name] = data
        else:
            if len(data) > 8000:
                raise ValueError("Form field too long")
            fields[name] = data.decode("utf-8")
    if "file" not in fields:
        raise ValueError("Missing file")
    if fields.get("model", "") not in ("", MODEL):
        raise ValueError(f"Model must be {MODEL}")
    if fields.get("response_format", "json") not in ("json", "text"):
        raise ValueError("response_format must be json or text")
    return fields


class SttServer(ThreadingHTTPServer):
    allow_reuse_address = False
    daemon_threads = False
    block_on_close = True
    request_queue_size = 4

    def __init__(self, port=18765):
        self.token = secrets.token_urlsafe(24)
        self.slots, self.busy = threading.BoundedSemaphore(4), threading.Lock()
        super().__init__(("127.0.0.1", port), Handler)

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

    @property
    def base_url(self):
        return f"http://127.0.0.1:{self.server_port}/{self.token}/v1"

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()

    def handle_error(self, request, client_address):
        pass  # Never log request paths, which contain the local access capability.


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(15)
        self.deadline = threading.Timer(15, self.abort_read)
        self.deadline.daemon = True
        self.deadline.start()

    def abort_read(self):
        try:
            self.connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    def finish(self):
        self.deadline.cancel()
        super().finish()

    def log_message(self, *args):
        pass

    def reply(self, status, data, *, plain=False):
        body = data.encode("utf-8") if plain else json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8" if plain else "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        if getattr(self, "authorized", False) and self.headers.get("Origin") == "null":
            self.send_header("Access-Control-Allow-Origin", "null")
            self.send_header("Vary", "Origin")
        self.end_headers()
        self.wfile.write(body)

    def error(self, status, message):
        self.reply(status, {"error": {"message": message}})

    def authorize(self):
        hosts = self.headers.get_all("Host", [])
        if len(hosts) != 1 or hosts[0] not in (f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"):
            self.error(403, "Invalid local host")
            return False
        pieces = self.path.split("/")
        if len(pieces) < 3 or not pieces[1].isascii() or not secrets.compare_digest(pieces[1], self.server.token):
            self.error(403, "Invalid local access URL")
            return False
        origins = self.headers.get_all("Origin", [])
        if origins not in ([], ["null"]):
            self.error(403, "Browser origin is not allowed")
            return False
        self.authorized = True
        return True

    def do_GET(self):
        if self.authorize():
            if self.path == f"/{self.server.token}/v1/models":
                self.reply(200, {"object": "list", "data": [{"id": MODEL, "object": "model", "owned_by": "local"}]})
            else:
                self.error(404, "Unknown endpoint")

    def do_OPTIONS(self):
        if self.authorize():
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "null")
            self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Content-Length", "0")
            self.end_headers()

    def do_POST(self):
        if not self.authorize():
            return
        if self.path != f"/{self.server.token}/v1/audio/transcriptions":
            self.error(404, "Unknown endpoint")
            return
        if not self.server.busy.acquire(blocking=False):
            self.error(429, "A transcription is already running")
            return
        try:
            lengths = self.headers.get_all("Content-Length", [])
            if self.headers.get("Transfer-Encoding") or len(lengths) != 1 or not lengths[0].isdigit():
                self.error(411, "One Content-Length is required; chunked uploads are unsupported")
                return
            length = int(lengths[0])
            if not 0 < length <= MAX_BODY:
                self.error(413, "Upload is empty or exceeds 25 MiB plus form overhead")
                return
            body = self.rfile.read(length)
            if len(body) != length:
                raise ValueError("Incomplete upload")
            self.deadline.cancel()
            fields = parse_form(self.headers.get("Content-Type"), body)
            text = transcribe(fields["file"], language=fields.get("language", ""), prompt=fields.get("prompt", ""))
            if fields.get("response_format") == "text":
                self.reply(200, text, plain=True)
            else:
                self.reply(200, {"text": text})
        except ValueError as error:
            self.error(400, str(error))
        except BusyError:
            self.error(429, "A transcription is already running")
        except (TimeoutError, queue.Empty):
            self.error(504, "Transcription timed out")
        except Exception:
            self.error(502, "Codex transcription failed. Check Codex login and retry.")
        finally:
            self.server.busy.release()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=18765)
    parser.add_argument("--connection-file", type=Path, default=Path(os.environ["LOCALAPPDATA"]) / "select-to-tts" / "stt-connection.json")
    args = parser.parse_args()
    with SttServer(args.port) as server:
        connection = json.dumps({"base_url": server.base_url, "model": MODEL}, indent=2)
        args.connection_file.parent.mkdir(parents=True, exist_ok=True)
        args.connection_file.write_text(connection, encoding="utf-8")
        print(f"STT listening on loopback port {server.server_port}. Private URL saved to {args.connection_file}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            if args.connection_file.exists() and args.connection_file.read_text(encoding="utf-8") == connection:
                args.connection_file.unlink()


if __name__ == "__main__":
    main()
