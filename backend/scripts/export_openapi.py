"""Export without reading environment, dotenv, databases or provider keys."""
import argparse
import json
from pathlib import Path
from fitcheck_backend.config import Settings
from fitcheck_backend.api.app import create_app
from fitcheck_backend.contracts.openapi import export_openapi


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[2] / "contracts/fitcheck.openapi.json")
    args = parser.parse_args()
    settings = Settings(_env_file=None, _env_prefix="FITCHECK_SCHEMA_EXPORT_", env="test")
    content = json.dumps(export_openapi(create_app(settings)), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.check:
        if not args.output.exists() or args.output.read_text() != content:
            print(f"OpenAPI drift: regenerate {args.output}")
            return 1
        print("OpenAPI artifact is current")
        return 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(content)
    print(f"Exported {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
