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

        # Recorded before the Docker rewrite below: host.docker.internal is a
        # container artifact, not the address anyone configured.
        dispatch_url = base_url

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
        # Base-signature call only — OctoPrint's upload-and-print kwarg is not part of
        # the BasePrinterOperator contract and raises TypeError on other firmwares.
        op.upload_file(args.gcode_path, filename)

        # The dispatch moment is the only moment the target URL is true — this is
        # what later distinguishes simulator telemetry from real hardware.
        try:
            from pythonsrc.telemetry.db import TelemetryDB as _DispatchDB

            _ddb = _DispatchDB()
            _ddb.update_job_dispatch(args.job_id, printer_url=dispatch_url)
            _ddb.close()
        except Exception as exc:
            logger.warning(f"Could not record the dispatch target: {exc}")

        if args.start_print:
            logger.info("Starting print...")
            op.start_print(filename)

            
            import asyncio
            from pythonsrc.telemetry.db import TelemetryDB
            from pythonsrc.telemetry.detector import attach_detector
            from pythonsrc.telemetry.octoprint_collector import OctoPrintCollector
            from urllib.parse import urlparse

            async def monitor_print():
                logger.info("Starting telemetry collector and polling print status...")
                db = TelemetryDB()
                parsed = urlparse(base_url)
                port = parsed.port or (443 if parsed.scheme == "https" else 80)
                
                # Stamp started_at — not completed_at, which this used to write:
                # `update_job_outcome`'s second timestamp is the *completion*
                # column, so every print marked its finish at the moment it began.
                job = db.get_job(args.job_id)
                if job and job.outcome == 'unknown' and not job.started_at:
                    import datetime
                    db.update_job_start_time(args.job_id, datetime.datetime.now(datetime.timezone.utc))

                collector = OctoPrintCollector(
                    parsed.hostname or "localhost", port, api_key or "",
                    args.job_id, db, gcode_filename=filename,
                )
                await collector.start()

                # Consume the samples so automated failure detection runs.
                detector_task = attach_detector(collector, db, op)

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
                    detector_task.cancel()
                    try:
                        await detector_task
                    except asyncio.CancelledError:
                        pass
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