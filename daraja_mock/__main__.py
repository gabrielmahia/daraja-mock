"""Run daraja-mock as a standalone server: `python -m daraja_mock [--port N]` or the `daraja-mock` command."""
import argparse

from daraja_mock import DarajaMock


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="daraja-mock: local Daraja test server (a test double, not a Safaricom simulator)")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8765, help="Port to listen on (default: 8765)")
    args = parser.parse_args(argv)

    mock = DarajaMock()
    print(f"daraja-mock running on http://{args.host}:{args.port}")
    print("Endpoints:")
    for rule in sorted(r.rule for r in mock.app.url_map.iter_rules() if r.endpoint != "static"):
        print(f"  {rule}")
    print("Press Ctrl+C to stop.")
    mock.run(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
