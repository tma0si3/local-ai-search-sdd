"""Console entry point: ``uv run localsearch``."""

from __future__ import annotations

HOST = "127.0.0.1"
PORT = 8000


def main() -> None:
    import uvicorn

    print(f"\n  Local Document Search running at http://{HOST}:{PORT}")
    print("  Nothing leaves this machine. Press Ctrl+C to stop.\n")
    # Host is fixed rather than configurable: binding to 0.0.0.0 would put the user's
    # documents on the network, which FR-026 forbids.
    uvicorn.run("localsearch.web.app:app", host=HOST, port=PORT, log_level="info")


if __name__ == "__main__":
    main()
