import http.server
import socketserver
import json
import os
import time
from pathlib import Path

try:
    from src.infrastructure.path_registry import PathRegistry
except ImportError:
    PathRegistry = None

PORT = 8080

class HealthHandler(http.server.SimpleHTTPRequestHandler):
    """HTTP handler for health check endpoints."""
    
    def log_message(self, format, *args):
        """Suppress default logging to reduce noise."""
        pass
    
    def do_GET(self):
        if self.path == '/health':
            self._send_health_response()
        elif self.path == '/status':
            self._send_status_response()
        else:
            self.send_response(404)
            self.end_headers()
    
    def _send_health_response(self):
        """Simple health check - just confirms process is running."""
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        status = {
            "status": "running",
            "service": "trading_bot",
            "timestamp": int(time.time())
        }
        self.wfile.write(json.dumps(status).encode('utf-8'))
    
    def _send_status_response(self):
        """Detailed status including bot health indicators."""
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        
        status = {
            "status": "running",
            "service": "trading_bot",
            "timestamp": int(time.time()),
            "checks": {}
        }
        
        if PathRegistry:
            heartbeat_file = PathRegistry.LOGS_DIR / ".bot_heartbeat"
            if heartbeat_file.exists():
                try:
                    mtime = heartbeat_file.stat().st_mtime
                    age_seconds = time.time() - mtime
                    status["checks"]["heartbeat"] = {
                        "age_seconds": round(age_seconds, 1),
                        "healthy": age_seconds < 120
                    }
                except:
                    status["checks"]["heartbeat"] = {"healthy": False, "error": "read_failed"}
        
        self.wfile.write(json.dumps(status).encode('utf-8'))


def start_server():
    """Start the health check HTTP server."""
    if PathRegistry:
        PathRegistry.ensure_directories()
    
    socketserver.TCPServer.allow_reuse_address = True
    
    try:
        with socketserver.TCPServer(("", PORT), HealthHandler) as httpd:
            print(f"[HealthCheck] Listening on port {PORT}")
            httpd.serve_forever()
    except Exception as e:
        print(f"[HealthCheck] Failed: {e}")


if __name__ == "__main__":
    start_server()
