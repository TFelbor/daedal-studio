# Environment Variables

You configure Prompt2Print by modifying the `.env` file located in the root of the project directory.

| Variable | Required? | Description | Example |
|----------|-----------|-------------|---------|
| `HF_TOKEN` | **Yes** | Your HuggingFace API token to download the AI models. | `hf_xyz...` |
| `OCTOPRINT_URL` | **Yes** | The network address of your OctoPrint server. | `http://192.168.1.50:5001` |
| `OCTOPRINT_API_KEY` | **Yes** | The Global API Key generated in OctoPrint. | `ABC123DEF456...` |
| `TELEMETRY_DB_PATH` | No | Where to save the SQLite database for telemetry. | `/app/telemetry/telemetry.db` |
| `PAUSE_ON_FAILURE` | No | Whether to pause the printer automatically when an anomaly is detected. | `true` or `false` |
| `PYTORCH_ENABLE_MPS_FALLBACK` | No | Should be set to `1` for Mac users to ensure PyTorch compatibility. | `1` |

> Do NOT commit your `.env` file or share your API keys with anyone!
