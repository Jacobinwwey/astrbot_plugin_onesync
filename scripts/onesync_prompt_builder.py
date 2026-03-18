#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_WEBUI_URL = "http://127.0.0.1:8099"
DEFAULT_MANAGER_BY_OS = {
    "ubuntu": "apt_get",
    "debian": "apt_get",
    "centos": "yum",
    "rhel": "yum",
    "rocky": "dnf",
    "alma": "dnf",
    "fedora": "dnf",
    "arch": "pacman",
    "manjaro": "pacman",
    "opensuse": "zypper",
    "sles": "zypper",
    "windows": "winget",
    "macos": "brew",
}


def _to_bool_text(value: bool) -> str:
    return "true" if value else "false"


def _yaml_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return _to_bool_text(value)
    if isinstance(value, (int, float)):
        return str(value)
    text = "" if value is None else str(value)
    if text == "":
        return '""'
    # JSON string is valid YAML string and handles escaping safely.
    return json.dumps(text, ensure_ascii=False)


def _normalize_strategy(value: str) -> str:
    strategy = (value or "").strip().lower()
    alias = {
        "cmd": "command",
        "command": "command",
        "cargo_path_git": "cargo_path_git",
        "git_cargo": "cargo_path_git",
        "system_package": "system_package",
        "package": "system_package",
        "pkg": "system_package",
        "system_pkg": "system_package",
    }
    return alias.get(strategy, "system_package")


@dataclass
class Profile:
    lang: str
    webui_url: str
    webui_password: str
    target_config_mode: str
    poll_interval_minutes: int
    default_check_interval_hours: float
    auto_update_on_schedule: bool
    notify_admin_on_schedule: bool
    notify_on_schedule_noop: bool
    admin_sid_list: list[str]
    os_profile: str
    scenario: str
    targets: list[dict[str, Any]]


def infer_manager(os_profile: str) -> str:
    return DEFAULT_MANAGER_BY_OS.get((os_profile or "").strip().lower(), "apt_get")


def default_target(
    *,
    software_name: str,
    strategy: str,
    os_profile: str,
    manager: str,
    repo_path: str,
    binary_path: str,
    upstream_repo: str,
    check_interval_hours: float,
    current_version_cmd: str,
    latest_version_cmd: str,
    latest_version_pattern: str,
    update_commands: list[str],
    verify_cmd: str,
) -> dict[str, Any]:
    target_name = (software_name or "").strip() or "mysoftware"
    normalized = _normalize_strategy(strategy)
    if normalized == "cargo_path_git":
        repo = repo_path or f"/path/to/{target_name}"
        binary = binary_path or f"/path/to/bin/{target_name}"
        upstream = upstream_repo or f"https://github.com/example/{target_name}.git"
        return {
            "name": target_name,
            "strategy": "cargo_path_git",
            "enabled": True,
            "check_interval_hours": check_interval_hours,
            "repo_path": repo,
            "binary_path": binary,
            "upstream_repo": upstream,
            "build_commands": ["cargo install --path {repo_path}"],
            "verify_cmd": verify_cmd or "{binary_path} --version",
        }

    if normalized == "command":
        updates = update_commands or [f"echo TODO: define update command for {target_name}"]
        return {
            "name": target_name,
            "strategy": "command",
            "enabled": True,
            "check_interval_hours": check_interval_hours,
            "current_version_cmd": current_version_cmd or f"{target_name} --version",
            "latest_version_cmd": latest_version_cmd or "",
            "latest_version_pattern": latest_version_pattern or "",
            "update_commands": updates,
            "verify_cmd": verify_cmd or f"{target_name} --version",
        }

    mgr = manager or infer_manager(os_profile)
    return {
        "name": target_name,
        "strategy": "system_package",
        "enabled": True,
        "check_interval_hours": check_interval_hours,
        "manager": mgr,
        "package_name": target_name,
        "require_sudo": mgr in {"apt_get", "yum", "dnf", "pacman", "zypper"},
    }


def parse_target_file(path: str) -> list[dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"targets-json file not found: {path}")
    raw = p.read_text(encoding="utf-8")
    parsed = json.loads(raw)

    targets: list[dict[str, Any]] = []
    if isinstance(parsed, list):
        for item in parsed:
            if isinstance(item, dict):
                targets.append(dict(item))
    elif isinstance(parsed, dict):
        for name, cfg in parsed.items():
            if not isinstance(cfg, dict):
                continue
            item = dict(cfg)
            item.setdefault("name", str(name))
            targets.append(item)
    else:
        raise ValueError("targets-json must be a JSON object or array")

    normalized: list[dict[str, Any]] = []
    for item in targets:
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        current = dict(item)
        current["name"] = name
        current["strategy"] = _normalize_strategy(str(current.get("strategy", "system_package")))
        current.setdefault("enabled", True)
        current.setdefault("check_interval_hours", 12)
        normalized.append(current)

    if not normalized:
        raise ValueError("targets-json produced no valid targets")
    return normalized


def yaml_targets_block(targets: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for target in targets:
        name = str(target.get("name", "")).strip()
        strategy = _normalize_strategy(str(target.get("strategy", "system_package")))
        enabled = bool(target.get("enabled", True))
        interval = float(target.get("check_interval_hours", 12))

        lines.append(f"- name: {name}")
        lines.append(f"  strategy: {strategy}")
        lines.append(f"  enabled: {_to_bool_text(enabled)}")
        lines.append(f"  check_interval_hours: {interval:g}")

        for key in sorted(target.keys()):
            if key in {"name", "strategy", "enabled", "check_interval_hours"}:
                continue
            value = target[key]
            if isinstance(value, list):
                lines.append(f"  {key}:")
                if not value:
                    lines.append("    []")
                else:
                    for item in value:
                        lines.append(f"    - {_yaml_scalar(item)}")
            elif isinstance(value, dict):
                # keep extensibility while avoiding nested complexity in prompt output
                lines.append(f"  {key}: {_yaml_scalar(json.dumps(value, ensure_ascii=False))}")
            else:
                lines.append(f"  {key}: {_yaml_scalar(value)}")
    return "\n".join(lines)


def render_prompt_a(profile: Profile) -> str:
    targets_yaml = yaml_targets_block(profile.targets)
    if profile.lang == "en":
        return f"""You are my OneSync configuration execution assistant.
Please bootstrap and apply OneSync configuration end-to-end.

Goal:
1) Generate valid JSON payload for POST /api/config (outer shape must be {{\"config\": {{...}}}}).
2) Generate a bash one-click script that:
   - writes onesync_config.json
   - logs in via /api/login if WEBUI_PASSWORD is not empty
   - POSTs /api/config
   - verifies with GET /api/config and GET /api/overview
3) Output exactly 3 sections:
   - JSON_PAYLOAD
   - BASH_ONE_CLICK
   - ASSUMPTIONS
4) No extra commentary; JSON must have no comments/trailing commas.

Input:
WEBUI_URL={profile.webui_url}
WEBUI_PASSWORD={profile.webui_password}
TARGET_CONFIG_MODE={profile.target_config_mode}
POLL_INTERVAL_MINUTES={profile.poll_interval_minutes}
DEFAULT_CHECK_INTERVAL_HOURS={profile.default_check_interval_hours:g}
AUTO_UPDATE_ON_SCHEDULE={_to_bool_text(profile.auto_update_on_schedule)}
NOTIFY_ADMIN_ON_SCHEDULE={_to_bool_text(profile.notify_admin_on_schedule)}
NOTIFY_ON_SCHEDULE_NOOP={_to_bool_text(profile.notify_on_schedule_noop)}
ADMIN_SID_LIST={','.join(profile.admin_sid_list)}
TARGETS_YAML:
{targets_yaml}
"""

    return f"""你是 OneSync 配置执行助手。请帮我完成 OneSync 的初始化配置与下发。

目标：
1) 生成可直接 POST 到 /api/config 的 JSON（外层必须是 {{\"config\": {{...}}}}）。
2) 生成一段 bash 一键脚本，自动：
   - 写入 onesync_config.json
   - 如果 WEBUI_PASSWORD 非空则调用 /api/login 获取 token
   - 调用 /api/config 提交配置
   - 调用 /api/config 与 /api/overview 验证生效
3) 输出分为 3 个区块：
   - JSON_PAYLOAD
   - BASH_ONE_CLICK
   - ASSUMPTIONS
4) 不要输出多余解释；JSON 不允许注释和尾逗号。

输入参数：
WEBUI_URL={profile.webui_url}
WEBUI_PASSWORD={profile.webui_password}
TARGET_CONFIG_MODE={profile.target_config_mode}
POLL_INTERVAL_MINUTES={profile.poll_interval_minutes}
DEFAULT_CHECK_INTERVAL_HOURS={profile.default_check_interval_hours:g}
AUTO_UPDATE_ON_SCHEDULE={_to_bool_text(profile.auto_update_on_schedule)}
NOTIFY_ADMIN_ON_SCHEDULE={_to_bool_text(profile.notify_admin_on_schedule)}
NOTIFY_ON_SCHEDULE_NOOP={_to_bool_text(profile.notify_on_schedule_noop)}
ADMIN_SID_LIST={','.join(profile.admin_sid_list)}
TARGETS_YAML:
{targets_yaml}
"""


def render_prompt_b(profile: Profile) -> str:
    target = profile.targets[0]
    raw_lines = yaml_targets_block([target]).splitlines()
    normalized_lines: list[str] = []
    for idx, line in enumerate(raw_lines):
        current = line
        if idx == 0 and current.startswith("- "):
            current = current[2:]
        elif current.startswith("  "):
            current = current[2:]
        normalized_lines.append(current)
    target_yaml = "\n".join(f"  {line}" for line in normalized_lines)

    if profile.lang == "en":
        return f"""You are my OneSync config merge assistant.
Add one new software target while preserving all existing settings and targets.

Execution rules:
1) Read current config from GET {profile.webui_url}/api/config.
2) Merge my new target incrementally (do not wipe unrelated targets).
3) Output:
   - UPDATED_JSON_PAYLOAD (for POST /api/config)
   - BASH_APPLY_PATCH (one-click script)
   - CHANGE_SUMMARY (what changed)
4) If target name already exists, update that target in place instead of duplicating.

Input:
WEBUI_URL={profile.webui_url}
WEBUI_PASSWORD={profile.webui_password}
NEW_TARGET:
{target_yaml}
"""

    return f"""你是 OneSync 配置助手。请在“保留现有配置不丢失”的前提下，为 OneSync 新增一个软件目标。

执行规则：
1) 先通过 GET {profile.webui_url}/api/config 读取现有配置。
2) 按我的目标参数进行“增量合并”，不要覆盖无关目标。
3) 输出：
   - UPDATED_JSON_PAYLOAD（用于 POST /api/config）
   - BASH_APPLY_PATCH（一键执行脚本）
   - CHANGE_SUMMARY（说明新增了哪些字段）
4) 如检测到同名目标，按“更新该目标”处理，不新增重复条目。

输入参数：
WEBUI_URL={profile.webui_url}
WEBUI_PASSWORD={profile.webui_password}
NEW_TARGET:
{target_yaml}
"""


def render_prompt_c(profile: Profile) -> str:
    if profile.lang == "en":
        return f"""You are my OneSync troubleshooting assistant.
Output a runnable plan in order: diagnose -> fix -> verify.

Required diagnostics:
1) GET {profile.webui_url}/api/health
2) GET {profile.webui_url}/openapi.json and confirm `/api/config` exists
3) GET {profile.webui_url}/api/config
4) If /api/config is 404, provide minimum fix sequence (restart service, confirm web_admin_url, Ctrl+F5)

Output format:
- DIAGNOSIS
- FIX_COMMANDS
- VERIFY_COMMANDS
- ROLLBACK_PLAN

Environment:
WEBUI_URL={profile.webui_url}
SERVICE_NAME=astrbot.service
"""

    return f"""你是 OneSync 故障诊断助手。请按“先诊断、后修复、再验证”的顺序输出可执行方案。

必须执行的诊断检查：
1) GET {profile.webui_url}/api/health
2) GET {profile.webui_url}/openapi.json 并确认是否有 /api/config
3) GET {profile.webui_url}/api/config
4) 如果 /api/config 返回 404，给出最小修复步骤（重启服务、确认 web_admin_url、Ctrl+F5）

输出格式：
- DIAGNOSIS
- FIX_COMMANDS
- VERIFY_COMMANDS
- ROLLBACK_PLAN

环境参数：
WEBUI_URL={profile.webui_url}
SERVICE_NAME=astrbot.service
"""


def parse_admin_sid_list(raw: str) -> list[str]:
    if not raw.strip():
        return []
    return [part.strip() for part in raw.replace("\n", ",").split(",") if part.strip()]


def ask(prompt: str, default: str) -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{prompt}{suffix}: ").strip()
    return value if value else default


def ask_bool(prompt: str, default: bool) -> bool:
    default_text = "y" if default else "n"
    raw = ask(f"{prompt} (y/n)", default_text).strip().lower()
    return raw in {"y", "yes", "1", "true"}


def build_profile(args: argparse.Namespace) -> Profile:
    lang = args.lang
    webui_url = args.webui_url
    webui_password = args.webui_password
    mode = args.target_config_mode
    os_profile = args.os_profile

    if args.interactive:
        lang = ask("Language (zh/en)", lang)
        webui_url = ask("WebUI URL", webui_url)
        webui_password = ask("WebUI password (empty allowed)", webui_password)
        mode = ask("target_config_mode (human/developer)", mode)
        os_profile = ask("OS profile (ubuntu/debian/fedora/windows/macos...)", os_profile)

    targets: list[dict[str, Any]]
    if args.targets_json:
        targets = parse_target_file(args.targets_json)
    else:
        software_name = args.software_name
        strategy = args.strategy
        manager = args.manager
        repo_path = args.repo_path
        binary_path = args.binary_path
        upstream_repo = args.upstream_repo
        check_interval_h = args.target_check_interval_hours
        current_cmd = args.current_version_cmd
        latest_cmd = args.latest_version_cmd
        latest_pattern = args.latest_version_pattern
        verify_cmd = args.verify_cmd
        update_commands = list(args.update_command or [])

        if args.interactive:
            software_name = ask("Primary software name", software_name)
            strategy = ask("Strategy (system_package/cargo_path_git/command)", strategy)
            check_interval_h = float(ask("Target check interval hours", str(check_interval_h)))
            if _normalize_strategy(strategy) == "system_package":
                manager = ask("Package manager (apt_get/yum/dnf/pacman/zypper/choco/winget/brew)", manager or infer_manager(os_profile))
            elif _normalize_strategy(strategy) == "cargo_path_git":
                repo_path = ask("repo_path", repo_path)
                binary_path = ask("binary_path", binary_path)
                upstream_repo = ask("upstream_repo", upstream_repo)
            else:
                current_cmd = ask("current_version_cmd", current_cmd)
                latest_cmd = ask("latest_version_cmd", latest_cmd)
                verify_cmd = ask("verify_cmd", verify_cmd)
                update_raw = ask("update command (single command for quick setup)", update_commands[0] if update_commands else "")
                update_commands = [update_raw] if update_raw else []

        targets = [
            default_target(
                software_name=software_name,
                strategy=strategy,
                os_profile=os_profile,
                manager=manager,
                repo_path=repo_path,
                binary_path=binary_path,
                upstream_repo=upstream_repo,
                check_interval_hours=check_interval_h,
                current_version_cmd=current_cmd,
                latest_version_cmd=latest_cmd,
                latest_version_pattern=latest_pattern,
                update_commands=update_commands,
                verify_cmd=verify_cmd,
            ),
        ]

    poll_interval = args.poll_interval_minutes
    default_check = args.default_check_interval_hours
    auto_update = args.auto_update_on_schedule
    notify_admin = args.notify_admin_on_schedule
    notify_noop = args.notify_on_schedule_noop
    admin_sid_list = parse_admin_sid_list(args.admin_sid_list)

    if args.interactive:
        poll_interval = int(ask("poll_interval_minutes", str(poll_interval)))
        default_check = float(ask("default_check_interval_hours", str(default_check)))
        auto_update = ask_bool("auto_update_on_schedule", auto_update)
        notify_admin = ask_bool("notify_admin_on_schedule", notify_admin)
        notify_noop = ask_bool("notify_on_schedule_noop", notify_noop)
        admin_sid_list = parse_admin_sid_list(ask("admin_sid_list (comma separated)", ",".join(admin_sid_list)))

    mode_norm = (mode or "human").strip().lower()
    if mode_norm not in {"human", "developer"}:
        mode_norm = "human"

    lang_norm = (lang or "zh").strip().lower()
    if lang_norm not in {"zh", "en"}:
        lang_norm = "zh"

    return Profile(
        lang=lang_norm,
        webui_url=webui_url,
        webui_password=webui_password,
        target_config_mode=mode_norm,
        poll_interval_minutes=max(1, int(poll_interval)),
        default_check_interval_hours=max(0.0, float(default_check)),
        auto_update_on_schedule=bool(auto_update),
        notify_admin_on_schedule=bool(notify_admin),
        notify_on_schedule_noop=bool(notify_noop),
        admin_sid_list=admin_sid_list,
        os_profile=os_profile,
        scenario=args.scenario,
        targets=targets,
    )


def build_output(profile: Profile) -> str:
    scenario = profile.scenario
    blocks: list[str] = []

    if scenario in {"bootstrap", "suite"}:
        title = "### Prompt A: Bootstrap and apply" if profile.lang == "en" else "### Prompt A：初始化并下发"
        blocks.append(title)
        blocks.append("")
        blocks.append("```text")
        blocks.append(render_prompt_a(profile).rstrip())
        blocks.append("```")

    if scenario in {"add", "suite"}:
        title = "### Prompt B: Incremental target merge" if profile.lang == "en" else "### Prompt B：增量新增目标"
        blocks.append("")
        blocks.append(title)
        blocks.append("")
        blocks.append("```text")
        blocks.append(render_prompt_b(profile).rstrip())
        blocks.append("```")

    if scenario in {"diagnose", "suite"}:
        title = "### Prompt C: Diagnose and repair" if profile.lang == "en" else "### Prompt C：诊断与修复"
        blocks.append("")
        blocks.append(title)
        blocks.append("")
        blocks.append("```text")
        blocks.append(render_prompt_c(profile).rstrip())
        blocks.append("```")

    return "\n".join(blocks).strip() + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate copy-ready AI prompts for OneSync one-click configuration",
    )
    parser.add_argument("--lang", choices=["zh", "en"], default="zh", help="Prompt language")
    parser.add_argument(
        "--scenario",
        choices=["bootstrap", "add", "diagnose", "suite"],
        default="suite",
        help="Prompt scenario output",
    )
    parser.add_argument("--interactive", action="store_true", help="Ask minimal questions interactively")

    parser.add_argument("--webui-url", default=DEFAULT_WEBUI_URL, help="OneSync WebUI URL")
    parser.add_argument("--webui-password", default="", help="OneSync WebUI password (optional)")
    parser.add_argument("--target-config-mode", choices=["human", "developer"], default="human")
    parser.add_argument("--poll-interval-minutes", type=int, default=10)
    parser.add_argument("--default-check-interval-hours", type=float, default=12)

    parser.add_argument("--auto-update-on-schedule", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--notify-admin-on-schedule", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--notify-on-schedule-noop", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--admin-sid-list", default="", help="Comma-separated admin SID list")

    parser.add_argument("--os-profile", default="ubuntu", help="OS profile for manager inference")
    parser.add_argument("--targets-json", default="", help="JSON file containing targets (array or object)")

    parser.add_argument("--software-name", default="zeroclaw")
    parser.add_argument("--strategy", default="system_package")
    parser.add_argument("--manager", default="")
    parser.add_argument("--target-check-interval-hours", type=float, default=12)

    parser.add_argument("--repo-path", default="")
    parser.add_argument("--binary-path", default="")
    parser.add_argument("--upstream-repo", default="")

    parser.add_argument("--current-version-cmd", default="")
    parser.add_argument("--latest-version-cmd", default="")
    parser.add_argument("--latest-version-pattern", default="")
    parser.add_argument("--verify-cmd", default="")
    parser.add_argument(
        "--update-command",
        action="append",
        default=[],
        help="Repeatable update command, used for command strategy",
    )

    parser.add_argument("--output", default="", help="Write prompt content to a file")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        profile = build_profile(args)
        content = build_output(profile)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.output:
        out = Path(args.output)
        out.write_text(content, encoding="utf-8")
        print(f"prompt written: {out}")
    else:
        print(content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
