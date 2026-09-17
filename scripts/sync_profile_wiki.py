"""Export profiles to a dedicated Obsidian folder without starting the agent."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from user_profile.obsidian_export import export_wiki, CONFIG_PATH


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--configure", action="store_true", help="Enable automatic export on server scheduler")
    args = parser.parse_args()
    result = export_wiki(args.destination)
    if args.configure:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps({"enabled": True, "destination": str(args.destination.resolve())}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=True))


if __name__ == "__main__":
    main()
