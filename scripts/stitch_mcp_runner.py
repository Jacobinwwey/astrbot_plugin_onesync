#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import anyio
import requests
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client

DEFAULT_STITCH_URL = "https://stitch.googleapis.com/mcp"


@dataclass
class ToolResult:
    is_error: bool
    text_items: list[str]


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_api_key() -> str:
    key = str(os.environ.get("STITCH_API_KEY", "")).strip()
    if not key:
        raise RuntimeError("STITCH_API_KEY is required in environment")
    return key


async def _call_tool_once(
    *,
    stitch_url: str,
    api_key: str,
    tool: str,
    args: dict[str, Any],
    timeout_s: float,
    sse_timeout_s: float,
) -> ToolResult:
    headers = {"X-Goog-Api-Key": api_key}
    async with streamablehttp_client(
        stitch_url,
        headers=headers,
        timeout=timeout_s,
        sse_read_timeout=sse_timeout_s,
    ) as streams:
        read_stream, write_stream, _ = streams
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.call_tool(tool, args)
            text_items = []
            for item in result.content:
                text = getattr(item, "text", "")
                if text:
                    text_items.append(text)
            return ToolResult(is_error=bool(result.isError), text_items=text_items)


async def _call_tool_with_retries(
    *,
    stitch_url: str,
    api_key: str,
    tool: str,
    args: dict[str, Any],
    timeout_s: float,
    sse_timeout_s: float,
    attempts: int,
    backoff_s: float,
) -> ToolResult:
    last_exc: Exception | None = None
    for idx in range(1, max(1, attempts) + 1):
        try:
            return await _call_tool_once(
                stitch_url=stitch_url,
                api_key=api_key,
                tool=tool,
                args=args,
                timeout_s=timeout_s,
                sse_timeout_s=sse_timeout_s,
            )
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if idx >= attempts:
                break
            await anyio.sleep(backoff_s * idx)
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("unknown MCP call failure")


def _first_json_blob(text_items: list[str]) -> dict[str, Any]:
    for item in text_items:
        text = str(item or "").strip()
        if not text:
            continue
        try:
            parsed = json.loads(text)
        except Exception:
            continue
        if isinstance(parsed, dict):
            return parsed
    return {}


def _screen_id_from_name(name: str) -> str:
    text = str(name or "").strip()
    if "/screens/" not in text:
        return ""
    return text.split("/screens/")[-1].strip()


def _collect_screen_ids(payload: dict[str, Any]) -> list[str]:
    rows = payload.get("screens", [])
    if not isinstance(rows, list):
        return []
    ids: list[str] = []
    seen: set[str] = set()
    for item in rows:
        if not isinstance(item, dict):
            continue
        sid = _screen_id_from_name(item.get("name", ""))
        if not sid or sid in seen:
            continue
        seen.add(sid)
        ids.append(sid)
    return ids


def _download_file(url: str, target_path: Path, timeout_s: float) -> None:
    resp = requests.get(url, timeout=timeout_s)
    resp.raise_for_status()
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_bytes(resp.content)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _build_variant_options(args: argparse.Namespace) -> dict[str, Any]:
    aspects = [
        item.strip().upper()
        for item in str(args.aspects or "").split(",")
        if item.strip()
    ]
    if not aspects:
        aspects = ["LAYOUT", "COLOR_SCHEME"]
    return {
        "variantCount": max(1, min(5, int(args.variant_count))),
        "creativeRange": str(args.creative_range or "EXPLORE").upper(),
        "aspects": aspects,
    }


async def cmd_projects(args: argparse.Namespace) -> int:
    api_key = _require_api_key()
    result = await _call_tool_with_retries(
        stitch_url=args.stitch_url,
        api_key=api_key,
        tool="list_projects",
        args={},
        timeout_s=args.timeout_s,
        sse_timeout_s=args.sse_timeout_s,
        attempts=args.read_retries,
        backoff_s=args.backoff_s,
    )
    payload = _first_json_blob(result.text_items)
    projects = payload.get("projects", [])
    if not isinstance(projects, list):
        projects = []
    if args.limit and args.limit > 0:
        projects = projects[: args.limit]
    print(json.dumps({"projects": projects}, ensure_ascii=False, indent=2))
    return 0


async def cmd_baseline(args: argparse.Namespace) -> int:
    api_key = _require_api_key()
    output_dir = Path(args.output_dir).expanduser() if args.output_dir else Path(f"/tmp/stitch-run-{_utc_stamp()}")
    output_dir.mkdir(parents=True, exist_ok=True)

    summary: dict[str, Any] = {
        "project_id": args.project_id,
        "mode": args.mode,
        "base_screen_id": args.base_screen_id,
        "skip_generate": bool(args.skip_generate),
        "generation_exception": None,
        "generation_is_error": None,
        "generated_output_exists": False,
        "before_count": 0,
        "after_count": 0,
        "new_screen_ids": [],
        "download_policy": args.download,
        "downloaded": [],
        "started_at": _utc_iso(),
    }

    before_result = await _call_tool_with_retries(
        stitch_url=args.stitch_url,
        api_key=api_key,
        tool="list_screens",
        args={"projectId": args.project_id},
        timeout_s=args.timeout_s,
        sse_timeout_s=args.sse_timeout_s,
        attempts=args.read_retries,
        backoff_s=args.backoff_s,
    )
    before_payload = _first_json_blob(before_result.text_items)
    before_ids = _collect_screen_ids(before_payload)
    summary["before_count"] = len(before_ids)
    _write_json(output_dir / "screens_before.json", before_payload)

    if not args.skip_generate:
        destructive_args: dict[str, Any]
        tool_name: str
        if args.mode == "variants":
            if not args.base_screen_id:
                raise RuntimeError("mode=variants requires --base-screen-id")
            tool_name = "generate_variants"
            destructive_args = {
                "projectId": args.project_id,
                "selectedScreenIds": [args.base_screen_id],
                "prompt": args.prompt,
                "variantOptions": _build_variant_options(args),
                "deviceType": args.device_type,
                "modelId": args.model_id,
            }
        else:
            tool_name = "generate_screen_from_text"
            destructive_args = {
                "projectId": args.project_id,
                "prompt": args.prompt,
                "deviceType": args.device_type,
                "modelId": args.model_id,
            }

        try:
            destructive_result = await _call_tool_once(
                stitch_url=args.stitch_url,
                api_key=api_key,
                tool=tool_name,
                args=destructive_args,
                timeout_s=args.timeout_s_destructive,
                sse_timeout_s=args.sse_timeout_s_destructive,
            )
            summary["generation_is_error"] = destructive_result.is_error
            if destructive_result.text_items:
                (output_dir / "generation_output.txt").write_text(
                    "\n".join(destructive_result.text_items),
                    encoding="utf-8",
                )
                summary["generated_output_exists"] = True
        except Exception as exc:  # noqa: BLE001
            summary["generation_exception"] = f"{type(exc).__name__}: {exc}"

    before_set = set(before_ids)
    latest_payload = before_payload
    new_screen_ids: list[str] = []
    for idx in range(1, max(1, args.poll_attempts) + 1):
        if idx > 1:
            await anyio.sleep(args.poll_interval_s)
        try:
            polled = await _call_tool_with_retries(
                stitch_url=args.stitch_url,
                api_key=api_key,
                tool="list_screens",
                args={"projectId": args.project_id},
                timeout_s=args.timeout_s,
                sse_timeout_s=args.sse_timeout_s,
                attempts=args.read_retries,
                backoff_s=args.backoff_s,
            )
            latest_payload = _first_json_blob(polled.text_items)
            current_ids = _collect_screen_ids(latest_payload)
            new_screen_ids = [sid for sid in current_ids if sid not in before_set]
            print(
                f"[poll {idx}/{args.poll_attempts}] screens={len(current_ids)} new={len(new_screen_ids)}",
                flush=True,
            )
            if new_screen_ids:
                break
        except Exception as exc:  # noqa: BLE001
            print(f"[poll {idx}/{args.poll_attempts}] read failure: {type(exc).__name__}", flush=True)

    _write_json(output_dir / "screens_after.json", latest_payload)
    all_after_ids = _collect_screen_ids(latest_payload)
    summary["after_count"] = len(all_after_ids)
    summary["new_screen_ids"] = new_screen_ids

    if args.download == "none":
        fetch_ids: list[str] = []
    elif args.download == "all":
        fetch_ids = all_after_ids
    else:
        fetch_ids = new_screen_ids

    fetched_meta: dict[str, Any] = {}
    for sid in fetch_ids:
        try:
            screen_result = await _call_tool_with_retries(
                stitch_url=args.stitch_url,
                api_key=api_key,
                tool="get_screen",
                args={
                    "name": f"projects/{args.project_id}/screens/{sid}",
                    "projectId": args.project_id,
                    "screenId": sid,
                },
                timeout_s=args.timeout_s,
                sse_timeout_s=args.sse_timeout_s,
                attempts=args.read_retries,
                backoff_s=args.backoff_s,
            )
            screen_payload = _first_json_blob(screen_result.text_items)
            fetched_meta[sid] = screen_payload
            _write_json(output_dir / "screens" / f"{sid}.json", screen_payload)

            shot_url = str(screen_payload.get("screenshot", {}).get("downloadUrl", "")).strip()
            html_url = str(screen_payload.get("htmlCode", {}).get("downloadUrl", "")).strip()

            if shot_url:
                shot_path = output_dir / "screens" / f"{sid}.png"
                _download_file(shot_url, shot_path, timeout_s=args.download_timeout_s)
                summary["downloaded"].append(str(shot_path))
            if html_url:
                html_path = output_dir / "screens" / f"{sid}.html"
                _download_file(html_url, html_path, timeout_s=args.download_timeout_s)
                summary["downloaded"].append(str(html_path))
        except Exception as exc:  # noqa: BLE001
            fetched_meta[sid] = {"error": f"{type(exc).__name__}: {exc}"}

    _write_json(output_dir / "screens_fetched_meta.json", fetched_meta)
    summary["finished_at"] = _utc_iso()
    _write_json(output_dir / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if args.strict and not args.skip_generate and not summary["new_screen_ids"]:
        return 2
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Reliable Stitch MCP runner for listing, generating, and polling screen outputs.",
    )
    parser.add_argument("--stitch-url", default=DEFAULT_STITCH_URL)
    parser.add_argument("--timeout-s", type=float, default=70.0)
    parser.add_argument("--sse-timeout-s", type=float, default=350.0)
    parser.add_argument("--timeout-s-destructive", type=float, default=120.0)
    parser.add_argument("--sse-timeout-s-destructive", type=float, default=650.0)
    parser.add_argument("--read-retries", type=int, default=3)
    parser.add_argument("--backoff-s", type=float, default=3.0)

    sub = parser.add_subparsers(dest="command", required=True)

    p_projects = sub.add_parser("projects", help="List Stitch projects.")
    p_projects.add_argument("--limit", type=int, default=20)

    p_baseline = sub.add_parser("baseline", help="Run one generation call then poll and fetch screens.")
    p_baseline.add_argument("--project-id", required=True)
    p_baseline.add_argument("--mode", choices=["variants", "screen"], default="variants")
    p_baseline.add_argument("--base-screen-id", default="")
    p_baseline.add_argument("--prompt", required=True)
    p_baseline.add_argument("--variant-count", type=int, default=3)
    p_baseline.add_argument("--creative-range", default="EXPLORE")
    p_baseline.add_argument("--aspects", default="LAYOUT,COLOR_SCHEME")
    p_baseline.add_argument("--device-type", default="DESKTOP")
    p_baseline.add_argument("--model-id", default="GEMINI_3_1_PRO")
    p_baseline.add_argument("--poll-attempts", type=int, default=18)
    p_baseline.add_argument("--poll-interval-s", type=float, default=20.0)
    p_baseline.add_argument("--download", choices=["new", "all", "none"], default="new")
    p_baseline.add_argument("--download-timeout-s", type=float, default=90.0)
    p_baseline.add_argument("--output-dir", default="")
    p_baseline.add_argument("--skip-generate", action="store_true")
    p_baseline.add_argument("--strict", action="store_true")

    return parser


async def async_main(argv: list[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "projects":
        return await cmd_projects(args)
    if args.command == "baseline":
        return await cmd_baseline(args)
    raise RuntimeError(f"unsupported command: {args.command}")


def main(argv: list[str] | None = None) -> int:
    try:
        return anyio.run(async_main, argv or sys.argv[1:])
    except KeyboardInterrupt:
        return 130
    except Exception as exc:  # noqa: BLE001
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
