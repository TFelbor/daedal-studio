# Printer Setup

Connecting your 3D printer to Daedal Studio allows the system to automatically slice files for your specific bed size and dispatch them directly for printing.

## Connecting OctoPrint

1. Obtain your **Global API Key** from OctoPrint (Settings > API).
2. Open your `.env` file in the project root.
3. Set `OCTOPRINT_URL` to your OctoPrint URL (e.g., `http://192.168.1.100:5001`). If OctoPrint is running on the same Mac/Windows host, use `http://host.docker.internal:5001`.
4. Set `OCTOPRINT_API_KEY` to your generated key.

## Connecting Klipper / Moonraker

If you use Klipper with the Moonraker API, you can connect it using the built-in Moonraker operator.
1. Update your `.env` file with your Moonraker IP address.
2. Ensure your Klipper instance is in a "ready" state before dispatching prints.

## Setup Wizard (Coming Soon)
A UI-based wizard is in development to help you auto-detect firmware, select standard printer profiles (e.g., Ender 3, Prusa), and perform pre-flight connectivity tests.
