from __future__ import annotations

import argparse
import json
import time

import httpx


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Curx ingestion smoke test.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8020")
    parser.add_argument("--username", required=True)
    parser.add_argument("--access-key", required=True)
    parser.add_argument("--timeout-seconds", type=int, default=45)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    with httpx.Client(base_url=args.base_url, timeout=20) as client:
        login = client.post(
            "/api/auth/bind",
            json={"username": args.username, "access_key": args.access_key},
        )
        login.raise_for_status()
        workspace = client.get("/api/workspace")
        workspace.raise_for_status()
        space_id = workspace.json()["spaces"][0]["id"]
        content = (
            "# 电池安全规范\n\n"
            "## 充电截止电压\n\n"
            "标准充电截止电压为 4.20V，允许误差为 ±0.05V。\n\n"
            "## 过压保护\n\n"
            "检测到超过 4.25V 时必须停止充电并记录故障。"
        )
        created = client.post(
            f"/api/knowledge-spaces/{space_id}/sources/text",
            json={
                "title": "Curx 阶段二验收规范",
                "source_type": "markdown",
                "content": content,
                "tags": ["验收", "battery"],
            },
        )
        created.raise_for_status()
        submission = created.json()
        job_id = submission["job"]["id"]
        deadline = time.monotonic() + args.timeout_seconds
        job = submission["job"]
        while job["status"] not in {"indexed", "failed", "cancelled"}:
            if time.monotonic() >= deadline:
                raise TimeoutError("The ingestion job did not reach a terminal state.")
            time.sleep(0.5)
            response = client.get(f"/api/ingestion-jobs/{job_id}")
            response.raise_for_status()
            job = response.json()

        detail_response = client.get(f"/api/sources/{submission['source']['id']}")
        detail_response.raise_for_status()
        detail = detail_response.json()
        result = {
            "http_status": created.status_code,
            "deduplicated": submission["deduplicated"],
            "source_id": submission["source"]["id"],
            "job_id": job_id,
            "job_status": job["status"],
            "event_statuses": [event["status"] for event in job["events"]],
            "error_code": job["error_code"],
            "document_version": detail["current_version"],
            "chunk_count": detail["documents"][0]["chunk_count"],
        }
        print(json.dumps(result, ensure_ascii=False))
        if job["status"] != "indexed":
            raise SystemExit(1)


if __name__ == "__main__":
    main()
