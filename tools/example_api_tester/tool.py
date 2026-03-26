"""
API Tester — make HTTP requests from the Toolbox.

Accepts: method, url, headers (JSON string), body (JSON string)
Returns: status code, response headers, response body
"""

import json
import time
import urllib.request
import urllib.error


def run(params: dict, context: dict) -> dict:
    method = params.get("method", "GET").upper()
    url = params.get("url", "")
    headers_raw = params.get("headers", "{}")
    body_raw = params.get("body", "")

    if not url:
        return {"message": "Error: No URL provided", "data": {}}

    # Parse headers
    try:
        headers = json.loads(headers_raw) if headers_raw.strip() else {}
    except json.JSONDecodeError as e:
        return {"message": f"Invalid headers JSON: {e}", "data": {}}

    # Build request
    body_bytes = body_raw.encode("utf-8") if body_raw.strip() else None
    if body_bytes and "Content-Type" not in headers:
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=body_bytes, headers=headers, method=method)

    start = time.time()
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            elapsed = round(time.time() - start, 3)
            resp_body = resp.read().decode("utf-8", errors="replace")
            resp_headers = dict(resp.headers)
            status = resp.status

            # Try to pretty-print JSON responses
            try:
                parsed = json.loads(resp_body)
                resp_body = json.dumps(parsed, indent=2)
            except (json.JSONDecodeError, ValueError):
                pass

            return {
                "message": f"{method} {url} → {status} ({elapsed}s)",
                "data": {
                    "status": status,
                    "elapsed_seconds": elapsed,
                    "response_headers": resp_headers,
                    "body": resp_body,
                }
            }

    except urllib.error.HTTPError as e:
        elapsed = round(time.time() - start, 3)
        resp_body = e.read().decode("utf-8", errors="replace")
        return {
            "message": f"{method} {url} → {e.code} ({elapsed}s)",
            "data": {
                "status": e.code,
                "elapsed_seconds": elapsed,
                "response_headers": dict(e.headers),
                "body": resp_body,
            }
        }

    except Exception as e:
        elapsed = round(time.time() - start, 3)
        return {
            "message": f"Request failed: {e}",
            "data": {"elapsed_seconds": elapsed, "error": str(e)}
        }
