"""`tura-code`: run the host, or check that everything it needs is in place."""

from __future__ import annotations

import argparse
import logging
import os
import sys
import webbrowser


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tura-code", description="root — a coding agent in your browser.")
    sub = parser.add_subparsers(dest="command")
    serve = sub.add_parser("serve", help="Run the server (default).")
    for target in (parser, serve):
        target.add_argument("--host", default=os.environ.get("TURA_CODE_HOST", "127.0.0.1"))
        target.add_argument("--port", type=int, default=int(os.environ.get("TURA_CODE_PORT", "8787")))
        target.add_argument("--open", action="store_true", help="Open the UI in a browser.")
        target.add_argument("--debug", action="store_true")
    sub.add_parser("doctor", help="Check the runtime binary, Dhee, and the OpenRouter key.")
    args = parser.parse_args(argv)

    if args.command == "doctor":
        return doctor()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if args.host not in ("127.0.0.1", "localhost", "::1"):
        allowed = os.environ.get("TURA_CODE_ALLOWED_HOSTS", "")
        if not allowed:
            print(
                "Refusing to listen on a non-local address without TURA_CODE_ALLOWED_HOSTS.\n"
                "The agent can run commands on this machine; expose it deliberately.",
                file=sys.stderr,
            )
            return 2

    import uvicorn

    from .app import create_app

    url = f"http://{'localhost' if args.host in ('127.0.0.1', '::1') else args.host}:{args.port}"
    print(f"root is running at {url}")
    if args.open:
        webbrowser.open(url)
    uvicorn.run(
        create_app(),
        host=args.host,
        port=args.port,
        log_level="debug" if args.debug else "info",
        # Image attachments travel over the socket as base64.
        ws_max_size=64 * 1024 * 1024,
    )
    return 0


def doctor() -> int:
    from . import launcher
    from .settings import SettingsStore, data_dir

    ok = True
    root = data_dir()
    print(f"data directory:   {root}")
    try:
        print(f"runtime binary:   {launcher.find_runtime_binary()}")
    except launcher.RuntimeNotFound as error:
        ok = False
        print(f"runtime binary:   MISSING — {error}")
    try:
        print(f"agent spec:       {launcher.base_agent_file()}")
    except launcher.RuntimeNotFound as error:
        ok = False
        print(f"agent spec:       MISSING — {error}")
    settings = SettingsStore(root).get()
    print(f"OpenRouter key:   {settings.key_source()}")
    print(f"model:            {settings.model}")
    print(f"Jev director:     {settings.director_mode}")
    try:
        import dhee

        print(f"Dhee:             {dhee.__version__} (memory mode: {settings.memory_mode})")
    except Exception as error:  # noqa: BLE001
        print(f"Dhee:             not installed ({error}); memory will be off")
    if settings.key_source() == "missing" and not os.environ.get(launcher.SCRIPTED_ECHO_ENV):
        ok = False
        print("\nSet OPENROUTER_API_KEY or add a key in the UI's settings.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
