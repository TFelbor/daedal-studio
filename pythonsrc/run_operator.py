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
        api_key = profile_data.get("api_key")
        if not api_key:
            api_key = os.environ.get("OCTOPRINT_API_KEY")
            
        base_url = os.environ.get("OCTOPRINT_URL") or profile_data.get("base_url", "http://localhost:5001")
        
        # Rewrite localhost if running inside docker so it can reach the host
        if "localhost" in base_url or "127.0.0.1" in base_url:
            if os.path.exists("/.dockerenv"):
                base_url = base_url.replace("localhost", "host.docker.internal").replace("127.0.0.1", "host.docker.internal")

        op = PrinterFactory.create(
            firmware=firmware,
            base_url=base_url,
            api_key=api_key,
        )

        logger.info(f"Connecting to {firmware} printer at {base_url}...")
        op.connect()

        filename = os.path.basename(args.gcode_path)
        logger.info(f"Uploading {filename}...")
        op.upload_file(args.gcode_path, filename, start_print=args.start_print)

        if args.start_print:
            # Print has been started during upload!
            logger.info("Print started automatically on upload.")

            
            import asyncio
            from pythonsrc.telemetry.db import TelemetryDB
            from pythonsrc.telemetry.octoprint_collector import OctoPrintCollector
            from urllib.parse import urlparse

            async def monitor_print():
                logger.info("Starting telemetry collector and polling print status...")
                db = TelemetryDB()
                parsed = urlparse(base_url)
                port = parsed.port or (443 if parsed.scheme == "https" else 80)
                
                job = db.get_job(args.job_id)
                if job and job.outcome == 'unknown' and not job.started_at:
                    import datetime
                    db.update_job_outcome(args.job_id, 'unknown', datetime.datetime.now(datetime.timezone.utc))

                collector = OctoPrintCollector(parsed.hostname or "localhost", port, api_key or "", args.job_id, db)
                await collector.start()
                
                try:
                    await asyncio.sleep(5)
                    while True:
                        try:
                            state = op.get_printer_state()
                            flags = state.get("state", {}).get("flags", {})
                            state_text = state.get("state", {}).get("text", "").lower()
                            
                            if (flags.get("ready") or flags.get("operational") or state_text == "operational" or state_text == "printed") and not flags.get("printing"):
                                logger.info(f"Print job completed! Final state: {state_text}")
                                break
                            
                            if flags.get("error") or flags.get("closedOrError") or state_text == "error":
                                logger.error("Printer reported an error state!")
                                raise Exception("Printer error state detected during printing.")
                                
                        except Exception as e:
                            logger.error(f"Error polling printer state: {e}")
                            raise e
                            
                        await asyncio.sleep(5)
                finally:
                    await collector.stop()
                    db.close()

            asyncio.run(monitor_print())

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