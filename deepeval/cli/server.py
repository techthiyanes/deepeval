from typing import Dict
from rich import print
import socketserver
import http.server
import webbrowser
import threading
import json

from deepeval.telemetry import set_logged_in_with

LOGGED_IN_WITH = "logged_in_with"


def start_server(pairing_code: str, prod_url: str) -> str:

    class PairingHandler(http.server.SimpleHTTPRequestHandler):

        def log_message(self, format, *args):
            pass  # Suppress default logging

        def do_OPTIONS(self):
            """Handle CORS preflight requests."""
            self.send_response(200)
            self.send_header("Access-Control-Allow-Origin", prod_url)
            self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

        def do_POST(self):
            content_length = int(self.headers["Content-Length"])
            body = self.rfile.read(content_length)
            data: Dict = json.loads(body)

            if self.path == f"/{LOGGED_IN_WITH}":
                logged_in_with = data.get(LOGGED_IN_WITH)
                pairing_code_recieved = data.get("pairing_code")
                if logged_in_with and pairing_code == pairing_code_recieved:
                    set_logged_in_with(logged_in_with)
                    self.send_response(200)
                    self.send_header("Access-Control-Allow-Origin", prod_url)
                    self.end_headers()
                    print(f"Logged in with: {logged_in_with}")
                    threading.Thread(target=httpd.shutdown, daemon=True).start()
                    return
                self.send_response(400)
                self.send_header("Access-Control-Allow-Origin", prod_url)
                self.end_headers()
                self.wfile.write(b"Invalid pairing code or data")

    with socketserver.TCPServer(("localhost", 0), PairingHandler) as httpd:
        port = httpd.server_address[1]
        login_url = f"{prod_url}/pair?code={pairing_code}&port={port}"
        print(
            f"Login and grab your API key here: [link={prod_url}]{prod_url}[/link] "
        )
        webbrowser.open(login_url)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        thread.join()
