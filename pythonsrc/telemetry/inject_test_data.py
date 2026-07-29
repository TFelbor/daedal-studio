#!/usr/bin/env python3
"""Inject test telemetry data for a specific job to verify the end-to-end pipeline."""

import sys
from datetime import datetime, timezone, timedelta
from pythonsrc.telemetry.db import TelemetryDB
from pythonsrc.telemetry.schema import TelemetrySample


def inject_test_telemetry(job_id: str, num_samples: int = 10, db_path: str | None = None) -> None:
    """Inject synthetic telemetry samples into the database.
    
    Args:
        job_id: The job ID to inject samples for.
        num_samples: Number of synthetic samples to create (default 10).
        db_path: Optional database path (defaults to standard location).
    """
    db = TelemetryDB(db_path=db_path)
    db.init_schema()
    
    # Check if job exists
    job = db.get_job(job_id)
    if not job:
        print(f"ERROR: Job {job_id} not found in database!")
        print("Run a print first to create the job, then inject test data.")
        db.close()
        return
    
    print(f"✓ Job found: {job.job_id} ({job.printer_firmware})")
    
    # Create synthetic telemetry samples
    base_time = datetime.now(timezone.utc)
    samples_created = 0
    
    for i in range(num_samples):
        sample_time = base_time - timedelta(seconds=num_samples - i)
        
        # Simulate realistic temperature progression (cold to hot)
        hotend_actual = 20 + (i / num_samples) * 200  # 20°C → 220°C
        hotend_target = 220
        bed_actual = 20 + (i / num_samples) * 60      # 20°C → 80°C
        bed_target = 80
        z_height = i * 0.2                             # 0mm → 1.8mm over 10 samples
        
        sample = TelemetrySample(
            job_id=job_id,
            sampled_at=sample_time,
            gcode_line=None,
            z_height_mm=z_height,
            hotend_actual_c=hotend_actual,
            hotend_target_c=hotend_target,
            bed_actual_c=bed_actual,
            bed_target_c=bed_target,
            print_speed_pct=100.0,
            extrusion_factor_pct=100.0,
            fan_speed_pct=50.0
        )
        
        db.insert_sample(sample)
        samples_created += 1
        print(f"  [{i+1}/{num_samples}] Sample at {sample_time.isoformat()}: "
              f"Hotend {hotend_actual:.1f}°C, Bed {bed_actual:.1f}°C, Z {z_height:.2f}mm")
    
    db.close()
    print(f"\n✓ Injected {samples_created} test samples for job {job_id}")
    print("\nNow:")
    print("  1. Reload the browser at http://0.0.0.0:8000/monitor")
    print("  2. Navigate to your print job")
    print("  3. The TelemetryChart should now display the synthetic data")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m pythonsrc.telemetry.inject_test_data <job_id> [num_samples] [db_path]")
        print("\nExample:")
        print("  python -m pythonsrc.telemetry.inject_test_data e16ad6d1-697f-4396-b9a2-3e73ef37e3e8 15")
        sys.exit(1)
    
    job_id = sys.argv[1]
    num_samples = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    db_path = sys.argv[3] if len(sys.argv) > 3 else None
    
    inject_test_telemetry(job_id, num_samples, db_path)
