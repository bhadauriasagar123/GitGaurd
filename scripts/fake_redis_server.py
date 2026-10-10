"""Local stand-in for a Redis *server* (RESP over TCP) so multi-process production-mode runs can be rehearsed on a
machine without Redis:  python -m scripts.fake_redis_server 6390
Not for production use - use Azure-managed Redis / Upstash / Redis Cloud there."""
import sys

from fakeredis import TcpFakeServer

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 6390
    server = TcpFakeServer(("127.0.0.1", port), server_type="redis")
    print(f"fake redis listening on 127.0.0.1:{port}", flush=True)
    server.serve_forever()
