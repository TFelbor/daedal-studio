import argparse
import json
import logging
import sys
import os
from pathlib import Path

from pythonsrc.operators import PrinterFactory

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("run_operator")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--gcode-path", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--start-print", action="store_true", default=True,
                        help="Automatically start the print after upload (default: True)")
    args = parser.parse_args()

    try:
        with open(args.profile, "r") as f:
            profile_data = json.load(f)

        firmware = profile_data.get("firmware", "octoprint")
        base_url = profile_data.get("base_url", "http://localhost:5001")
        api_key = profile_data.get("api_key")

        op = PrinterFactory.create(
            firmware=firmware,
            base_url=base_url,
            api_key=api_key,
        )

        logger.info(f"Connecting to {firmware} printer at {base_url}...")
        op.connect()

        filename = os.path.basename(args.gcode_path)
        logger.info(f"Uploading {filename}...")
        op.upload_file(args.gcode_path, filename)

        if args.start_print:
            logger.info("Starting print...")
            op.start_print(filename)

        logger.info("Print dispatched successfully.")

        # Write status file for job tracking
        repo_root = Path(__file__).parent.parent
        log_dir = repo_root / "data" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        status_file = log_dir / f"{args.job_id}.status"
        with open(status_file, "a") as sf:
            import datetime
            sf.write(json.dumps({
                "phase": 5,
                "name": "operator",
                "status": "complete",
                "ts": datetime.datetime.now(datetime.timezone.utc).isoformat()
            }) + "\n")

    except Exception as e:
        logger.error(f"Failed to dispatch print: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()