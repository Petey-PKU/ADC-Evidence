"""Launch an extracted ADC-Evidence release without a Git checkout or model API."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path, PurePosixPath


def configure_release(root: Path) -> dict[str, str]:
    root = root.resolve()
    manifest = json.loads((root / "RELEASE_MANIFEST.json").read_text(encoding="utf-8"))
    application = manifest.get("application", {})
    if application.get("mode") != "bundled_source":
        raise ValueError("This archive lacks the bundled application; download a v2 release.")
    configured = {}
    for key, variable in (
        ("database_path", "ADC_DATABASE_PATH"),
        ("catalog_path", "ADC_SEED_PATH"),
        ("index_path", "ADC_VECTOR_INDEX_PATH"),
    ):
        raw = application.get(key, "")
        relative = PurePosixPath(raw)
        if not raw or relative.is_absolute() or ".." in relative.parts or "\\" in raw or ":" in raw:
            raise ValueError(f"Invalid release path: {key}")
        selected = (root / relative).resolve()
        if not selected.is_relative_to(root) or not selected.exists():
            raise ValueError(f"Release path is missing or escapes the archive: {key}")
        configured[variable] = str(selected)
    # Set before importing application modules, whose defaults are evaluated
    # at import time. The extracted source takes precedence over any checkout.
    configured.update(ADC_OFFLINE_ONLY="true", ADC_LLM_BACKEND="extractive", ADC_PUBLIC_DEMO="true")
    os.environ.update(configured)
    os.environ.pop("ADC_ENV_FILE", None)
    sys.path.insert(0, str(root / "src"))
    return configured


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--question", help="Answer once and print JSON; otherwise start the browser app.")
    mode.add_argument("--check", action="store_true", help="Check release paths without starting the app.")
    parser.add_argument("--port", type=int, default=8501)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    configured = configure_release(root)
    if args.check:
        print(json.dumps({"status": "configured", "offline_only": True, "backend": "extractive"}))
        return
    try:
        if args.question is not None:
            from adc_evidence.generation.generators import create_generator
            from adc_evidence.generation.service import EvidenceAnsweringService

            service = EvidenceAnsweringService(
                database_path=Path(configured["ADC_DATABASE_PATH"]),
                seed_path=Path(configured["ADC_SEED_PATH"]),
                generator=create_generator("extractive"),
            )
            result = service.answer(args.question)
            if hasattr(sys.stdout, "reconfigure"):
                sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            print(result.model_dump_json(indent=2))
        else:
            from streamlit.web import cli

            sys.argv = [
                "streamlit", "run", str(root / "src" / "adc_evidence" / "app.py"),
                "--browser.gatherUsageStats=false", "--server.address=127.0.0.1",
                "--server.headless=true", f"--server.port={args.port}",
            ]
            cli.main()
    except ModuleNotFoundError as error:
        parser.exit(1, f"Missing dependency {error.name!r}. From the release folder run: python -m pip install -e .\n")


if __name__ == "__main__":
    main()
