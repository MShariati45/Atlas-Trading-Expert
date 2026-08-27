from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
import os

root = Path(__file__).parent / "dashboard"
os.chdir(root)
print("Atlas dashboard: http://127.0.0.1:8765")
ThreadingHTTPServer(("127.0.0.1", 8765), SimpleHTTPRequestHandler).serve_forever()
