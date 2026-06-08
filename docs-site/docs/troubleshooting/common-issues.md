# Common Issues

If you run into issues, check here first.

### Connection refused — cannot reach OctoPrint
**Cause:** Docker network can't resolve the host machine.  
**Fix (macOS/Windows):** Use `http://host.docker.internal:5001` in your `.env` file instead of `localhost` or `127.0.0.1`.  
**Fix (Linux):** Use your LAN IP or add `--add-host=host.docker.internal:host-gateway` to your startup scripts.

### 403 Forbidden from OctoPrint
**Cause:** Incorrect or missing `OCTOPRINT_API_KEY`.  
**Fix:** Generate a new Global API Key in OctoPrint and update your `.env` file.

### Out of disk space during model download
**Cause:** Insufficient space for 16GB FLUX weights.  
**Fix:** Ensure you have at least 30 GB free. Run `docker system df` to see what is taking up space, and clean up old images or prune unused volumes.

### GPU not detected inside container
**Cause:** Missing NVIDIA Container Toolkit.  
**Fix:** Install `nvidia-container-toolkit` on the host and run `sudo systemctl restart docker`.

### `api-server` fails to start: port 8000 in use
**Cause:** Another service on your computer is bound to port 8000.  
**Fix:** Stop the blocking process or edit `docker-compose.yml` to map the container's port to a different host port (e.g., `8080:8000`).

### Telemetry DB locked
**Cause:** Multiple `api-server` instances attempting concurrent SQLite writes.  
**Fix:** Ensure only one `api-server` container is running by running `docker compose down` before bringing the server up again.

### OctoPrint telemetry not collecting
**Cause:** OctoPrint's Socket.IO server version does not match the `python-socketio` client.  
**Fix:** Ensure your OctoPrint instance is fully updated.
