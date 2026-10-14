#!/usr/bin/env python3
"""AeroPredict AI read-only local dashboard server.

This only binds to loopback (127.0.0.1), serving two exact routes:
  GET /              -> dashboard/index.html
  GET /api/results   -> existing local JSON backtest + FEES history output

Unlike running 'python -m http.server' from the repo root, this deliberately
does NOT expose .env, .git or any other repository files to the browser.
No external dependencies; no private keys, contracts or transactions.
"""
import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "dashboard" / "index.html"
RESULTS = ROOT / "data" / "pool_fee_backtest_base.json"
HISTORY = ROOT / "data" / "pool_fee_histories_base.json"
INCENTIVES = ROOT / "data" / "pool_incentives_base.json"
PAIRS = ROOT / "data" / "pool_pairs_base.json"
OPTIMIZER_JS = ROOT / "dashboard" / "optimizer.js"
EXPANDED_BUNDLE = ROOT / "data" / "expanded_dashboard_bundle.json"
REFRESH_STATUS = ROOT / "data" / "expanded_refresh_status.json"
# The expanded dataset is an opt-in local research preview. The original
# seven-pool dashboard remains the default and is never overwritten here.
DATASETS = {
    "demo": {
        "backtest": RESULTS, "history": HISTORY,
        "incentives": INCENTIVES, "pairs": PAIRS,
    },
    "expanded": {
        "backtest": ROOT / "data" / "pool_fee_backtest_expanded_base.json",
        "history": ROOT / "data" / "pool_fee_histories_expanded_base.json",
        "incentives": ROOT / "data" / "pool_incentives_expanded_base.json",
        "pairs": ROOT / "data" / "pool_pairs_expanded_base.json",
    },
}


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "AeroPredictLocal/0.1"

    def send_payload(self, status, mime, data):
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(data)

    def json_response(self, status, value):
        self.send_payload(
            status,
            "application/json; charset=utf-8",
            json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8"),
        )

    def do_GET(self):
        path = urlsplit(self.path).path
        if path in ("/", "/index.html"):
            try:
                data = HTML.read_bytes()
            except OSError as exc:
                self.json_response(500, {"error": "Dashboard HTML unavailable", "detail": str(exc)})
                return
            self.send_payload(200, "text/html; charset=utf-8", data)
            return

        if path == "/optimizer.js":
            try:
                code = OPTIMIZER_JS.read_bytes()
            except OSError:
                self.json_response(404, {"error": "Optimizer frontend not available"})
                return
            self.send_payload(200, "application/javascript; charset=utf-8", code)
            return

        if path == "/api/refresh-status":
            if self.server.dataset_mode != "expanded":
                self.json_response(200, {"state": "not_enabled", "stage": "Demo dataset"})
                return
            try:
                status = json.loads(REFRESH_STATUS.read_text(encoding="utf-8"))
                if not isinstance(status, dict):
                    raise ValueError("Invalid status format")
            except (OSError, ValueError):
                status = {"state": "idle", "stage": "No automated refresh recorded"}
            # A killed process should never leave the UI permanently spinning.
            if status.get("state") == "running":
                try:
                    pid = int(status["pid"])
                    cmdline = (Path("/proc") / str(pid) / "cmdline").read_bytes()
                    if b"refresh_expanded_data.py" not in cmdline:
                        status["state"] = "interrupted"
                        status["stage"] = "Previous refresh was interrupted"
                except (OSError, ValueError, KeyError, TypeError):
                    status["state"] = "interrupted"
                    status["stage"] = "Previous refresh was interrupted"
            latest = None
            try:
                if EXPANDED_BUNDLE.is_file():
                    payload = json.loads(EXPANDED_BUNDLE.read_text(encoding="utf-8"))
                    latest = payload.get("published_at_utc") or payload["incentives"].get("collected_at_utc")
                elif self.server.data_files["incentives"].is_file():
                    saved = json.loads(self.server.data_files["incentives"].read_text(encoding="utf-8"))
                    latest = saved.get("collected_at_utc")
            except (OSError, ValueError, TypeError, KeyError):
                pass
            # Return only validated UI fields, not process identifiers or paths.
            self.json_response(200, {
                "state": status.get("state", "idle"),
                "stage": str(status.get("stage") or "")[:140],
                "last_updated_utc": latest,
                "last_success_utc": status.get("last_success_utc"),
                "last_failure_utc": status.get("last_failure_utc"),
            })
            return

        if path == "/api/results":
            # Once created by the refresher, this one file contains all
            # four validated data components. Atomic os.replace means a
            # concurrent hourly refresh cannot mix old and new snapshots.
            if self.server.dataset_mode == "expanded" and EXPANDED_BUNDLE.is_file():
                try:
                    bundle = json.loads(EXPANDED_BUNDLE.read_text(encoding="utf-8"))
                    if not isinstance(bundle, dict) or bundle.get("dataset_mode") != "expanded":
                        raise ValueError("Unexpected expanded dashboard bundle type")
                    for key in ("backtest", "history", "incentives", "pairs"):
                        block = bundle.get(key)
                        if not isinstance(block, dict) or block.get("chain_id") != 8453:
                            raise ValueError(f"Malformed Base Mainnet bundle component: {key}")
                    if not isinstance(bundle["backtest"].get("results"), list):
                        raise ValueError("Bundle has no backtest results")
                    for key in ("history", "incentives", "pairs"):
                        if not isinstance(bundle[key].get("pools"), list):
                            raise ValueError(f"Bundle has no {key} pools")
                except (OSError, ValueError, TypeError, KeyError) as exc:
                    self.json_response(
                        500, {"error": "Cannot read atomic expanded dashboard snapshot", "detail": str(exc)}
                    )
                    return
                self.json_response(200, bundle)
                return
            files = self.server.data_files
            if not files["backtest"].is_file():
                self.json_response(
                    404,
                    {
                        "error": "Backtest results not found",
                        "instruction": "python scripts/backtest_pool_fees.py",
                    },
                )
                return
            try:
                raw = json.loads(files["backtest"].read_text(encoding="utf-8"))
                if raw.get("chain_id") != 8453:
                    raise ValueError("Expected Base chain ID 8453")
                if not isinstance(raw.get("results"), list):
                    raise ValueError("Backtest JSON has no results list")
            except (OSError, ValueError, KeyError, TypeError) as exc:
                self.json_response(
                    500, {"error": "Cannot parse local backtest JSON", "detail": str(exc)}
                )
                return
            # Reward history is optional for older data sets. Serve only the
            # specific, known local artifact; do not expose arbitrary files.
            history = None
            if files["history"].is_file():
                try:
                    history = json.loads(files["history"].read_text(encoding="utf-8"))
                    if history.get("chain_id") != 8453:
                        raise ValueError("History is not from Base Mainnet")
                    if not isinstance(history.get("pools"), list):
                        raise ValueError("History must contain a pools list")
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    self.json_response(
                        500, {"error": "Cannot parse reward history", "detail": str(exc)}
                    )
                    return
            incentives = None
            if files["incentives"].is_file():
                try:
                    incentives = json.loads(files["incentives"].read_text(encoding="utf-8"))
                    if incentives.get("chain_id") != 8453:
                        raise ValueError("Incentives are not from Base Mainnet")
                    if not isinstance(incentives.get("pools"), list):
                        raise ValueError("Incentives must contain a pools list")
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    self.json_response(
                        500, {"error": "Cannot parse incentives JSON", "detail": str(exc)}
                    )
                    return
            pairs = None
            if files["pairs"].is_file():
                try:
                    pairs = json.loads(files["pairs"].read_text(encoding="utf-8"))
                    if pairs.get("chain_id") != 8453:
                        raise ValueError("Pool pairs are not from Base Mainnet")
                    if not isinstance(pairs.get("pools"), list):
                        raise ValueError("Pool pairs require a pools list")
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    self.json_response(
                        500, {"error": "Cannot parse pool pairs JSON", "detail": str(exc)}
                    )
                    return
            self.json_response(200, {
                "backtest": raw, "history": history,
                "incentives": incentives, "pairs": pairs,
                "dataset_mode": self.server.dataset_mode,
            })
            return

        self.json_response(404, {"error": "Unknown endpoint"})

    def do_POST(self):
        self.json_response(405, {"error": "Read-only demo"})

    def log_message(self, fmt, *args):
        print("[%s] %s" % (self.log_date_time_string(), fmt % args), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765, help="Loopback port")
    parser.add_argument(
        "--dataset", choices=tuple(DATASETS), default="demo",
        help="Select demo (original 7 pools) or expanded (16-pool local research preview)",
    )
    args = parser.parse_args()
    if not (1024 <= args.port <= 65535):
        parser.error("--port must be between 1024 and 65535")
    dataset_files = DATASETS[args.dataset]
    if args.dataset == "expanded":
        missing = [
            str(file.relative_to(ROOT))
            for file in dataset_files.values() if not file.is_file()
        ]
        if missing:
            parser.error(
                "Expanded research preview not ready. Missing files: " +
                ", ".join(missing)
            )
    server = ThreadingHTTPServer(("127.0.0.1", args.port), DashboardHandler)
    server.data_files = dataset_files
    server.dataset_mode = args.dataset
    print(f"AeroPredict AI | local read-only dashboard | {args.dataset} dataset", flush=True)
    print(f"Windows browser URL: http://localhost:{args.port}/", flush=True)
    print(f"Reading results from: {dataset_files['backtest']}", flush=True)
    print(f"Reading reward histories from: {dataset_files['history']}", flush=True)
    print(f"Reading incentives from: {dataset_files['incentives']}", flush=True)
    print(f"Reading pool trading pairs from: {dataset_files['pairs']}", flush=True)
    print("Dashboard is bound to 127.0.0.1 only. Ctrl+C to stop.", flush=True)
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        print("\nDashboard server stopped.", flush=True)


if __name__ == "__main__":
    try:
        main()
    except OSError as exc:
        print(f"ERROR: Unable to start local dashboard: {exc}", file=sys.stderr)
        sys.exit(1)
