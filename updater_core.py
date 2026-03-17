from __future__ import annotations

import asyncio
import os
import re
import shlex
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from astrbot.core.utils.version_comparator import VersionComparator

DEFAULT_VERSION_PATTERN = r"(\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.\-]+)?)"
DEFAULT_GITHUB_MIRROR_PREFIXES = [
    "",
    "https://edgeone.gh-proxy.com/",
    "https://hk.gh-proxy.com/",
    "https://gh-proxy.com/",
    "https://gh.llkk.cc/",
    "https://ghfast.top/",
]
DEFAULT_REMOTE_PROBE_TIMEOUT_S = 15
DEFAULT_REMOTE_PROBE_PARALLELISM = 4
DEFAULT_REMOTE_PROBE_CACHE_TTL_MINUTES = 30.0


def _to_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        norm = value.strip().lower()
        if norm in {"1", "true", "yes", "on"}:
            return True
        if norm in {"0", "false", "no", "off"}:
            return False
    return default


def _to_int(value: Any, default: int, min_value: int | None = None) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = default
    if min_value is not None and parsed < min_value:
        return min_value
    return parsed


def _to_float(value: Any, default: float, min_value: float | None = None) -> float:
    try:
        parsed = float(value)
    except Exception:
        parsed = default
    if min_value is not None and parsed < min_value:
        return min_value
    return parsed


def _safe_str(value: Any) -> str:
    return str(value if value is not None else "")


def _normalize_version(value: str) -> str:
    text = _safe_str(value).strip()
    if text.lower().startswith("v") and len(text) > 1 and text[1].isdigit():
        return text[1:]
    return text


def compare_versions(a: str, b: str) -> int:
    a_norm = _normalize_version(a)
    b_norm = _normalize_version(b)
    try:
        return VersionComparator.compare_version(a_norm, b_norm)
    except Exception:
        if a_norm == b_norm:
            return 0
        return -1 if a_norm < b_norm else 1


class _SafeFormatMap(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def render_template(template: str, data: dict[str, Any]) -> str:
    return _safe_str(template).format_map(_SafeFormatMap(data))


def ensure_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, (list, tuple, set)):
        result: list[str] = []
        for item in value:
            text = _safe_str(item).strip()
            if text:
                result.append(text)
        return result
    return []


def dedupe_keep_order(values: list[str]) -> list[str]:
    result: list[str] = []
    seen = set()
    for item in values:
        raw = _safe_str(item)
        text = raw.strip()
        # 空前缀有特殊语义：直连上游，不应被过滤掉。
        if raw == "" or text == "":
            if "" in seen:
                continue
            seen.add("")
            result.append("")
            continue
        if text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def extract_version(text: str, pattern: str | None = None) -> str:
    content = _safe_str(text)
    regex = re.compile(pattern or DEFAULT_VERSION_PATTERN)
    match = regex.search(content)
    if not match:
        raise ValueError(f"cannot extract version from text: {content!r}")
    if "version" in regex.groupindex:
        version = _safe_str(match.group("version")).strip()
    elif match.groups():
        version = _safe_str(match.group(1)).strip()
    else:
        version = _safe_str(match.group(0)).strip()
    if not version:
        raise ValueError(f"extracted empty version from text: {content!r}")
    return version


@dataclass
class ExecResult:
    command: str
    exit_code: int
    stdout: str
    stderr: str
    duration_s: float
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


@dataclass
class CheckResult:
    target: str
    ok: bool
    current_version: str = ""
    latest_version: str = ""
    needs_update: bool = False
    message: str = ""
    diagnostics: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class UpdateResult:
    target: str
    ok: bool
    changed: bool
    old_version: str = ""
    new_version: str = ""
    message: str = ""
    diagnostics: list[str] = field(default_factory=list)


class StrategyError(RuntimeError):
    pass


@dataclass
class RemoteProbeResult:
    remote: str
    ok: bool
    latency_ms: int
    exit_code: int
    stdout: str
    stderr: str


@dataclass
class RemoteProbeCacheEntry:
    created_at: float
    results: list[RemoteProbeResult]


_REMOTE_PROBE_CACHE: dict[str, RemoteProbeCacheEntry] = {}


class CommandRunner:
    @staticmethod
    def _ensure_runtime_path(env: dict[str, str]) -> None:
        raw_path = _safe_str(env.get("PATH", ""))
        path_entries = [item for item in raw_path.split(":") if item]
        seen = set(path_entries)

        home_dir = _safe_str(env.get("HOME", "")).strip()
        if not home_dir:
            try:
                home_dir = os.path.expanduser("~")
            except Exception:
                home_dir = ""

        candidates: list[str] = []
        if home_dir:
            candidates.extend(
                [
                    os.path.join(home_dir, ".cargo", "bin"),
                    os.path.join(home_dir, ".local", "bin"),
                ],
            )
        candidates.extend(["/usr/local/bin", "/usr/bin", "/bin"])

        prepend: list[str] = []
        for candidate in candidates:
            path = _safe_str(candidate).strip()
            if not path or path in seen:
                continue
            if not os.path.isdir(path):
                continue
            prepend.append(path)
            seen.add(path)

        if prepend:
            env["PATH"] = ":".join(prepend + path_entries) if path_entries else ":".join(prepend)

    async def run(
        self,
        command: str,
        *,
        timeout_s: int = 600,
        cwd: str | None = None,
        env_update: dict[str, str] | None = None,
    ) -> ExecResult:
        env = os.environ.copy()
        if env_update:
            env.update({str(k): str(v) for k, v in env_update.items()})
        self._ensure_runtime_path(env)

        started = time.monotonic()
        proc = await asyncio.create_subprocess_exec(
            "/bin/bash",
            "-c",
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=env,
        )
        timed_out = False
        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(),
                timeout=float(timeout_s),
            )
        except asyncio.TimeoutError:
            timed_out = True
            proc.kill()
            stdout_b, stderr_b = await proc.communicate()

        elapsed = time.monotonic() - started
        code = proc.returncode if proc.returncode is not None else 124
        if timed_out:
            code = 124

        return ExecResult(
            command=command,
            exit_code=int(code),
            stdout=stdout_b.decode("utf-8", errors="replace"),
            stderr=stderr_b.decode("utf-8", errors="replace"),
            duration_s=elapsed,
            timed_out=timed_out,
        )


class BaseStrategy:
    def __init__(
        self,
        runner: CommandRunner,
        logger: Callable[[str], None] | None = None,
    ) -> None:
        self.runner = runner
        self._logger = logger

    def _log(self, msg: str) -> None:
        if self._logger:
            self._logger(msg)

    async def check(
        self,
        target_name: str,
        target_cfg: dict[str, Any],
        runtime_ctx: dict[str, Any],
    ) -> CheckResult:
        raise NotImplementedError

    async def update(
        self,
        target_name: str,
        target_cfg: dict[str, Any],
        runtime_ctx: dict[str, Any],
        *,
        dry_run: bool = False,
        force: bool = False,
    ) -> UpdateResult:
        raise NotImplementedError


class CommandStrategy(BaseStrategy):
    async def _read_version(
        self,
        cmd: str,
        *,
        timeout_s: int,
        pattern: str | None,
        runtime_ctx: dict[str, Any],
    ) -> tuple[str, ExecResult]:
        rendered = render_template(cmd, runtime_ctx)
        result = await self.runner.run(rendered, timeout_s=timeout_s)
        if not result.ok:
            raise StrategyError(
                f"command failed ({result.exit_code}): {rendered}\n{result.stderr.strip()}",
            )
        version = extract_version(result.stdout or result.stderr, pattern)
        return version, result

    async def check(
        self,
        target_name: str,
        target_cfg: dict[str, Any],
        runtime_ctx: dict[str, Any],
    ) -> CheckResult:
        diagnostics: list[str] = []
        current_cmd = _safe_str(target_cfg.get("current_version_cmd")).strip()
        latest_cmd = _safe_str(target_cfg.get("latest_version_cmd")).strip()
        check_timeout = int(target_cfg.get("check_timeout_s", 120))
        current_pattern = _safe_str(target_cfg.get("current_version_pattern")).strip() or None
        latest_pattern = _safe_str(target_cfg.get("latest_version_pattern")).strip() or None

        if not current_cmd:
            return CheckResult(
                target=target_name,
                ok=False,
                message="missing current_version_cmd",
            )

        try:
            current_version, cur_res = await self._read_version(
                current_cmd,
                timeout_s=check_timeout,
                pattern=current_pattern,
                runtime_ctx=runtime_ctx,
            )
            diagnostics.append(
                f"current_version_cmd ok in {cur_res.duration_s:.2f}s",
            )
        except Exception as exc:
            return CheckResult(
                target=target_name,
                ok=False,
                message=f"failed to read current version: {exc}",
            )

        if not latest_cmd:
            return CheckResult(
                target=target_name,
                ok=True,
                current_version=current_version,
                latest_version="",
                needs_update=False,
                message="latest_version_cmd is not configured",
                diagnostics=diagnostics,
            )

        try:
            latest_version, lat_res = await self._read_version(
                latest_cmd,
                timeout_s=check_timeout,
                pattern=latest_pattern,
                runtime_ctx=runtime_ctx,
            )
            diagnostics.append(
                f"latest_version_cmd ok in {lat_res.duration_s:.2f}s",
            )
        except Exception as exc:
            return CheckResult(
                target=target_name,
                ok=False,
                current_version=current_version,
                message=f"failed to read latest version: {exc}",
                diagnostics=diagnostics,
            )

        needs_update = compare_versions(current_version, latest_version) == -1
        return CheckResult(
            target=target_name,
            ok=True,
            current_version=current_version,
            latest_version=latest_version,
            needs_update=needs_update,
            message="check completed",
            diagnostics=diagnostics,
        )

    async def update(
        self,
        target_name: str,
        target_cfg: dict[str, Any],
        runtime_ctx: dict[str, Any],
        *,
        dry_run: bool = False,
        force: bool = False,
    ) -> UpdateResult:
        diagnostics: list[str] = []
        update_timeout = int(target_cfg.get("update_timeout_s", 900))
        update_commands = ensure_str_list(target_cfg.get("update_commands"))
        verify_cmd = _safe_str(target_cfg.get("verify_cmd")).strip()
        verify_timeout = int(target_cfg.get("verify_timeout_s", 120))

        check_result = await self.check(target_name, target_cfg, runtime_ctx)
        diagnostics.extend(check_result.diagnostics)
        if not check_result.ok:
            return UpdateResult(
                target=target_name,
                ok=False,
                changed=False,
                old_version=check_result.current_version,
                message=check_result.message,
                diagnostics=diagnostics,
            )
        if not force and not check_result.needs_update and check_result.latest_version:
            return UpdateResult(
                target=target_name,
                ok=True,
                changed=False,
                old_version=check_result.current_version,
                new_version=check_result.current_version,
                message="already up to date",
                diagnostics=diagnostics,
            )
        if not update_commands:
            return UpdateResult(
                target=target_name,
                ok=False,
                changed=False,
                old_version=check_result.current_version,
                message="missing update_commands",
                diagnostics=diagnostics,
            )

        old_version = check_result.current_version
        if dry_run:
            for cmd in update_commands:
                diagnostics.append(f"dry-run skipped: {render_template(cmd, runtime_ctx)}")
        else:
            for cmd in update_commands:
                rendered = render_template(cmd, runtime_ctx)
                result = await self.runner.run(rendered, timeout_s=update_timeout)
                diagnostics.append(
                    f"update command exit={result.exit_code} duration={result.duration_s:.2f}s cmd={rendered}",
                )
                if not result.ok:
                    message = f"update command failed: {rendered}"
                    if result.stderr.strip():
                        message = f"{message} | stderr: {result.stderr.strip()}"
                    return UpdateResult(
                        target=target_name,
                        ok=False,
                        changed=False,
                        old_version=old_version,
                        message=message,
                        diagnostics=diagnostics,
                    )

            if verify_cmd:
                rendered = render_template(verify_cmd, runtime_ctx)
                verify_result = await self.runner.run(rendered, timeout_s=verify_timeout)
                diagnostics.append(
                    f"verify command exit={verify_result.exit_code} duration={verify_result.duration_s:.2f}s cmd={rendered}",
                )
                if not verify_result.ok:
                    return UpdateResult(
                        target=target_name,
                        ok=False,
                        changed=False,
                        old_version=old_version,
                        message=f"verify command failed: {rendered}",
                        diagnostics=diagnostics,
                    )

        current_cmd = _safe_str(target_cfg.get("current_version_cmd")).strip()
        current_pattern = _safe_str(target_cfg.get("current_version_pattern")).strip() or None
        if not current_cmd:
            return UpdateResult(
                target=target_name,
                ok=True,
                changed=True,
                old_version=old_version,
                new_version="",
                message="update command finished (current_version_cmd not configured)",
                diagnostics=diagnostics,
            )

        try:
            new_version, cur_res = await self._read_version(
                current_cmd,
                timeout_s=int(target_cfg.get("check_timeout_s", 120)),
                pattern=current_pattern,
                runtime_ctx=runtime_ctx,
            )
            diagnostics.append(
                f"read new version ok in {cur_res.duration_s:.2f}s",
            )
        except Exception as exc:
            return UpdateResult(
                target=target_name,
                ok=False,
                changed=False,
                old_version=old_version,
                message=f"update finished but failed to read current version: {exc}",
                diagnostics=diagnostics,
            )

        changed = old_version != new_version
        return UpdateResult(
            target=target_name,
            ok=True,
            changed=changed,
            old_version=old_version,
            new_version=new_version,
            message="update completed",
            diagnostics=diagnostics,
        )


class CargoPathGitStrategy(CommandStrategy):
    def _build_remote_probe_cache_key(
        self,
        target_name: str,
        remotes: list[str],
        timeout_s: int,
    ) -> str:
        joined = "\n".join(remotes)
        return f"{target_name}|{timeout_s}|{joined}"

    async def _probe_single_remote(
        self,
        remote: str,
        *,
        timeout_s: int,
        semaphore: asyncio.Semaphore,
    ) -> RemoteProbeResult:
        cmd = f"git ls-remote --tags --refs {shlex.quote(remote)}"
        async with semaphore:
            result = await self.runner.run(cmd, timeout_s=timeout_s)
        latency_ms = max(0, int(round(result.duration_s * 1000)))
        return RemoteProbeResult(
            remote=remote,
            ok=result.ok,
            latency_ms=latency_ms,
            exit_code=result.exit_code,
            stdout=result.stdout,
            stderr=result.stderr,
        )

    async def _probe_remote_candidates(
        self,
        target_name: str,
        remotes: list[str],
        target_cfg: dict[str, Any],
        *,
        fallback_timeout_s: int,
        diagnostics: list[str],
    ) -> list[RemoteProbeResult]:
        if not remotes:
            return []

        probe_enabled = _to_bool(target_cfg.get("probe_remotes", True), True)
        if not probe_enabled:
            diagnostics.append("remote probe disabled by config")
            return []

        timeout_s = _to_int(
            target_cfg.get("probe_timeout_s", DEFAULT_REMOTE_PROBE_TIMEOUT_S),
            DEFAULT_REMOTE_PROBE_TIMEOUT_S,
            1,
        )
        timeout_s = min(timeout_s, max(1, int(fallback_timeout_s)))

        parallelism = _to_int(
            target_cfg.get("probe_parallelism", DEFAULT_REMOTE_PROBE_PARALLELISM),
            DEFAULT_REMOTE_PROBE_PARALLELISM,
            1,
        )
        parallelism = max(1, min(parallelism, 16))

        cache_ttl_minutes = _to_float(
            target_cfg.get(
                "probe_cache_ttl_minutes",
                DEFAULT_REMOTE_PROBE_CACHE_TTL_MINUTES,
            ),
            DEFAULT_REMOTE_PROBE_CACHE_TTL_MINUTES,
            0.0,
        )
        cache_key = self._build_remote_probe_cache_key(target_name, remotes, timeout_s)
        now = time.monotonic()
        cache_entry = _REMOTE_PROBE_CACHE.get(cache_key)
        if cache_entry and cache_ttl_minutes > 0:
            ttl_s = cache_ttl_minutes * 60.0
            if (now - cache_entry.created_at) <= ttl_s:
                diagnostics.append(
                    (
                        "remote probe cache hit: "
                        f"{len(cache_entry.results)} results, "
                        f"age={now - cache_entry.created_at:.1f}s"
                    ),
                )
                return list(cache_entry.results)

        semaphore = asyncio.Semaphore(parallelism)
        tasks = [
            self._probe_single_remote(
                remote,
                timeout_s=timeout_s,
                semaphore=semaphore,
            )
            for remote in remotes
        ]
        results = await asyncio.gather(*tasks)

        index_map = {remote: idx for idx, remote in enumerate(remotes)}

        def sort_key(item: RemoteProbeResult) -> tuple[int, int, int]:
            # 先按可用性，再按延迟，再按原始顺序稳定排序。
            return (
                0 if item.ok else 1,
                item.latency_ms if item.ok else 10**9,
                index_map.get(item.remote, 10**9),
            )

        sorted_results = sorted(results, key=sort_key)
        ok_count = sum(1 for item in sorted_results if item.ok)
        diagnostics.append(
            (
                "remote probe completed: "
                f"candidates={len(remotes)} ok={ok_count} fail={len(remotes) - ok_count} "
                f"parallelism={parallelism} timeout_s={timeout_s}"
            ),
        )
        for item in sorted_results:
            if item.ok:
                diagnostics.append(
                    f"probe ok remote={item.remote} latency_ms={item.latency_ms}",
                )
            else:
                diagnostics.append(
                    (
                        f"probe fail remote={item.remote} exit={item.exit_code} "
                        f"stderr={_safe_str(item.stderr).strip()}"
                    ),
                )

        _REMOTE_PROBE_CACHE[cache_key] = RemoteProbeCacheEntry(
            created_at=now,
            results=list(sorted_results),
        )
        return sorted_results

    async def _ensure_safe_directory(
        self,
        repo_path: str,
        timeout_s: int,
    ) -> ExecResult:
        command = (
            "git config --global --add safe.directory "
            f"{shlex.quote(repo_path)}"
        )
        return await self.runner.run(command, timeout_s=timeout_s)

    @staticmethod
    def _is_dubious_ownership(stderr: str) -> bool:
        return "dubious ownership" in _safe_str(stderr).lower()

    @staticmethod
    def _is_missing_remote_ref(stderr: str) -> bool:
        lower = _safe_str(stderr).lower()
        return "couldn't find remote ref" in lower or "cannot find remote ref" in lower

    @staticmethod
    def _is_ff_only_rejected(stderr: str) -> bool:
        lower = _safe_str(stderr).lower()
        return (
            "not possible to fast-forward" in lower
            or "diverging branches can't be fast-forwarded" in lower
        )

    @staticmethod
    def _should_retry_cargo_install_with_force(command: str, stderr: str) -> bool:
        cmd_low = _safe_str(command).strip().lower()
        if not cmd_low.startswith("cargo install"):
            return False
        if " --force" in f" {cmd_low} ":
            return False
        return "already exists in destination" in _safe_str(stderr).lower()

    @staticmethod
    def _git_repo_command(
        repo_path: str,
        git_args: str,
        *,
        safe_directory: bool,
    ) -> str:
        if safe_directory:
            return (
                "git "
                f"-c safe.directory={shlex.quote(repo_path)} "
                f"-C {shlex.quote(repo_path)} {git_args}"
            )
        return f"git -C {shlex.quote(repo_path)} {git_args}"

    async def _detect_branch(
        self,
        repo_path: str,
        timeout_s: int,
        *,
        safe_directory: bool = False,
    ) -> str:
        command = self._git_repo_command(
            repo_path,
            "rev-parse --abbrev-ref HEAD",
            safe_directory=safe_directory,
        )
        result = await self.runner.run(command, timeout_s=timeout_s)
        if (
            not result.ok
            and not safe_directory
            and self._is_dubious_ownership(result.stderr)
        ):
            retry_cmd = self._git_repo_command(
                repo_path,
                "rev-parse --abbrev-ref HEAD",
                safe_directory=True,
            )
            retry = await self.runner.run(retry_cmd, timeout_s=timeout_s)
            if retry.ok:
                result = retry
        if not result.ok:
            raise StrategyError(
                f"failed to detect git branch: {result.stderr.strip()}",
            )
        branch = result.stdout.strip()
        if not branch or branch == "HEAD":
            raise StrategyError("detected detached HEAD; please set branch in target config")
        return branch

    async def _detect_remote_default_branch(
        self,
        remote: str,
        timeout_s: int,
    ) -> str:
        cmd = f"git ls-remote --symref {shlex.quote(remote)} HEAD"
        res = await self.runner.run(cmd, timeout_s=timeout_s)
        if not res.ok:
            raise StrategyError(
                f"failed to detect remote default branch: {res.stderr.strip()}",
            )
        for line in _safe_str(res.stdout).splitlines():
            line = line.strip()
            if not line.startswith("ref: ") or "HEAD" not in line:
                continue
            if "refs/heads/" not in line:
                continue
            after = line.split("refs/heads/", 1)[1]
            branch = after.split()[0].split("\t")[0].strip()
            if branch:
                return branch
        raise StrategyError("remote default branch not found in ls-remote output")

    @staticmethod
    def _cleanup_temp_repo(
        temp_repo_path: str,
        diagnostics: list[str],
    ) -> None:
        path = _safe_str(temp_repo_path).strip()
        if not path:
            return
        try:
            shutil.rmtree(path, ignore_errors=True)
            diagnostics.append(f"temp clone cleanup done: {path}")
        except Exception as exc:
            diagnostics.append(f"temp clone cleanup failed: {exc}")

    async def _clone_repo_for_build(
        self,
        target_name: str,
        remotes: list[str],
        branch_candidates: list[str],
        *,
        timeout_s: int,
        diagnostics: list[str],
    ) -> tuple[str, str, str]:
        if not remotes:
            raise StrategyError("no remotes for clone fallback")
        if not branch_candidates:
            raise StrategyError("no branch candidates for clone fallback")

        safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "-", target_name).strip("-") or "target"
        clone_errors: list[str] = []

        for remote in remotes:
            for branch in branch_candidates:
                tmp_dir = tempfile.mkdtemp(prefix=f"onesync-{safe_name}-")
                clone_cmd = (
                    "git clone --depth 1 "
                    f"--branch {shlex.quote(branch)} "
                    f"{shlex.quote(remote)} {shlex.quote(tmp_dir)}"
                )
                res = await self.runner.run(clone_cmd, timeout_s=timeout_s)
                diagnostics.append(
                    (
                        f"clone fallback remote={remote} branch={branch} "
                        f"exit={res.exit_code} duration={res.duration_s:.2f}s"
                    ),
                )
                if res.ok:
                    return tmp_dir, remote, branch

                stderr_text = _safe_str(res.stderr).strip()
                clone_errors.append(f"{remote}@{branch}: {stderr_text}")
                self._cleanup_temp_repo(tmp_dir, diagnostics)
                if self._is_missing_remote_ref(stderr_text):
                    continue
                break

        raise StrategyError(
            "clone fallback failed: " + " | ".join(clone_errors),
        )

    def _build_remote_candidates(self, target_cfg: dict[str, Any]) -> list[str]:
        remotes = ensure_str_list(target_cfg.get("remote_candidates"))
        upstream_repo = _safe_str(target_cfg.get("upstream_repo")).strip()
        mirror_prefixes = ensure_str_list(target_cfg.get("mirror_prefixes"))

        append_default_mirrors = _to_bool(
            target_cfg.get("append_default_mirror_prefixes", True),
            True,
        )
        if (
            append_default_mirrors
            and upstream_repo.startswith("https://github.com/")
        ):
            mirror_prefixes = dedupe_keep_order(
                mirror_prefixes + DEFAULT_GITHUB_MIRROR_PREFIXES,
            )

        if upstream_repo and not mirror_prefixes:
            mirror_prefixes = [""]
        for prefix in mirror_prefixes:
            if not upstream_repo:
                continue
            if prefix:
                remotes.append(prefix + upstream_repo)
            else:
                remotes.append(upstream_repo)

        deduped: list[str] = []
        seen = set()
        for remote in remotes:
            if remote in seen:
                continue
            seen.add(remote)
            deduped.append(remote)
        return deduped

    def _pick_latest_tag(self, ls_remote_stdout: str) -> str:
        versions: list[str] = []
        for line in _safe_str(ls_remote_stdout).splitlines():
            parts = line.strip().split()
            if len(parts) < 2:
                continue
            ref = parts[1]
            if "refs/tags/" not in ref:
                continue
            tag = ref.split("refs/tags/")[-1].strip()
            if not tag:
                continue
            try:
                versions.append(extract_version(tag))
            except Exception:
                continue

        if not versions:
            raise StrategyError("no semantic-version tags found in remote refs")

        best: str | None = None
        for version in versions:
            if best is None:
                best = version
                continue
            if compare_versions(best, version) == -1:
                best = version
        if best is None:
            raise StrategyError("cannot select latest tag")
        return best

    async def check(
        self,
        target_name: str,
        target_cfg: dict[str, Any],
        runtime_ctx: dict[str, Any],
    ) -> CheckResult:
        diagnostics: list[str] = []
        repo_path = _safe_str(target_cfg.get("repo_path")).strip()
        binary_path = _safe_str(target_cfg.get("binary_path")).strip()
        check_timeout = int(target_cfg.get("check_timeout_s", 120))
        current_pattern = _safe_str(target_cfg.get("current_version_pattern")).strip() or None

        if not repo_path:
            return CheckResult(target=target_name, ok=False, message="missing repo_path")
        if not binary_path:
            return CheckResult(target=target_name, ok=False, message="missing binary_path")

        auto_safe_dir = bool(target_cfg.get("auto_add_safe_directory", True))
        if auto_safe_dir:
            safe_res = await self._ensure_safe_directory(repo_path, timeout_s=check_timeout)
            diagnostics.append(
                f"safe.directory add exit={safe_res.exit_code} duration={safe_res.duration_s:.2f}s",
            )

        current_cmd = _safe_str(target_cfg.get("current_version_cmd")).strip()
        if not current_cmd:
            current_cmd = f"{shlex.quote(binary_path)} --version"
            target_cfg = dict(target_cfg)
            target_cfg["current_version_cmd"] = current_cmd
            target_cfg["current_version_pattern"] = current_pattern or DEFAULT_VERSION_PATTERN

        try:
            current_version, cur_res = await self._read_version(
                current_cmd,
                timeout_s=check_timeout,
                pattern=current_pattern,
                runtime_ctx=runtime_ctx,
            )
            diagnostics.append(
                f"current version: {current_version} ({cur_res.duration_s:.2f}s)",
            )
        except Exception as exc:
            return CheckResult(
                target=target_name,
                ok=False,
                message=f"failed to read current version: {exc}",
            )

        remotes = self._build_remote_candidates(target_cfg)
        if not remotes:
            return CheckResult(
                target=target_name,
                ok=False,
                current_version=current_version,
                message="missing remote_candidates and upstream_repo",
                diagnostics=diagnostics,
            )

        probe_results = await self._probe_remote_candidates(
            target_name,
            remotes,
            target_cfg,
            fallback_timeout_s=check_timeout,
            diagnostics=diagnostics,
        )

        ordered_remotes: list[str]
        if probe_results:
            ordered_remotes = [item.remote for item in probe_results]
        else:
            ordered_remotes = list(remotes)
        best_remote = ordered_remotes[0] if ordered_remotes else ""

        latest_version = ""
        latest_errors: list[str] = []
        if probe_results:
            for probe in probe_results:
                if not probe.ok:
                    latest_errors.append(
                        f"{probe.remote}: {probe.stderr.strip() or 'probe failed'}",
                    )
                    continue
                try:
                    latest_version = self._pick_latest_tag(probe.stdout)
                    diagnostics.append(
                        f"latest tag from {probe.remote}: {latest_version}",
                    )
                    break
                except Exception as exc:
                    latest_errors.append(f"{probe.remote}: {exc}")
        else:
            for remote in ordered_remotes:
                cmd = f"git ls-remote --tags --refs {shlex.quote(remote)}"
                result = await self.runner.run(cmd, timeout_s=check_timeout)
                diagnostics.append(
                    f"ls-remote remote={remote} exit={result.exit_code} duration={result.duration_s:.2f}s",
                )
                if not result.ok:
                    latest_errors.append(f"{remote}: {result.stderr.strip()}")
                    continue
                try:
                    latest_version = self._pick_latest_tag(result.stdout)
                    diagnostics.append(f"latest tag from {remote}: {latest_version}")
                    break
                except Exception as exc:
                    latest_errors.append(f"{remote}: {exc}")

        if not latest_version:
            return CheckResult(
                target=target_name,
                ok=False,
                current_version=current_version,
                message=f"failed to resolve latest version from remotes: {' | '.join(latest_errors)}",
                diagnostics=diagnostics,
                extra={
                    "ordered_remotes": ordered_remotes,
                    "best_remote": best_remote,
                },
            )

        needs_update = compare_versions(current_version, latest_version) == -1
        check_message = "check completed"
        if best_remote:
            check_message = f"check completed (best_remote={best_remote})"
        return CheckResult(
            target=target_name,
            ok=True,
            current_version=current_version,
            latest_version=latest_version,
            needs_update=needs_update,
            message=check_message,
            diagnostics=diagnostics,
            extra={
                "ordered_remotes": ordered_remotes,
                "best_remote": best_remote,
            },
        )

    async def update(
        self,
        target_name: str,
        target_cfg: dict[str, Any],
        runtime_ctx: dict[str, Any],
        *,
        dry_run: bool = False,
        force: bool = False,
    ) -> UpdateResult:
        diagnostics: list[str] = []
        repo_path = _safe_str(target_cfg.get("repo_path")).strip()
        if not repo_path:
            return UpdateResult(
                target=target_name,
                ok=False,
                changed=False,
                message="missing repo_path",
            )

        check_result = await self.check(target_name, target_cfg, runtime_ctx)
        diagnostics.extend(check_result.diagnostics)
        if not check_result.ok:
            return UpdateResult(
                target=target_name,
                ok=False,
                changed=False,
                old_version=check_result.current_version,
                message=check_result.message,
                diagnostics=diagnostics,
            )

        if not force and not check_result.needs_update:
            return UpdateResult(
                target=target_name,
                ok=True,
                changed=False,
                old_version=check_result.current_version,
                new_version=check_result.current_version,
                message="already up to date",
                diagnostics=diagnostics,
            )

        old_version = check_result.current_version
        update_timeout = int(target_cfg.get("update_timeout_s", 1200))
        auto_safe_dir = _to_bool(target_cfg.get("auto_add_safe_directory", True), True)
        repo_safe_override = auto_safe_dir
        if auto_safe_dir:
            safe_res = await self._ensure_safe_directory(repo_path, timeout_s=update_timeout)
            diagnostics.append(
                f"safe.directory add exit={safe_res.exit_code} duration={safe_res.duration_s:.2f}s",
            )
            if not safe_res.ok:
                diagnostics.append(
                    "safe.directory global add failed; fallback to per-command safe.directory",
                )
        configured_branch = _safe_str(target_cfg.get("branch")).strip()
        detected_branch = ""
        if not configured_branch:
            try:
                detected_branch = await self._detect_branch(
                    repo_path,
                    timeout_s=update_timeout,
                    safe_directory=repo_safe_override,
                )
                diagnostics.append(f"detected git branch: {detected_branch}")
            except Exception as exc:
                return UpdateResult(
                    target=target_name,
                    ok=False,
                    changed=False,
                    old_version=old_version,
                    message=f"cannot detect branch: {exc}",
                    diagnostics=diagnostics,
                )
        branch_candidates = dedupe_keep_order(
            [
                configured_branch,
                detected_branch,
                _safe_str(target_cfg.get("default_branch", "")).strip(),
                "main",
                "master",
            ],
        )

        remotes = ensure_str_list(check_result.extra.get("ordered_remotes"))
        if not remotes:
            remotes = self._build_remote_candidates(target_cfg)
        if not remotes:
            return UpdateResult(
                target=target_name,
                ok=False,
                changed=False,
                old_version=old_version,
                message="missing remote candidates",
                diagnostics=diagnostics,
            )

        if not configured_branch:
            try:
                remote_default_branch = await self._detect_remote_default_branch(
                    remotes[0],
                    timeout_s=update_timeout,
                )
                diagnostics.append(
                    f"remote default branch from {remotes[0]}: {remote_default_branch}",
                )
                branch_candidates = dedupe_keep_order(
                    [remote_default_branch] + branch_candidates,
                )
            except Exception as exc:
                diagnostics.append(f"remote default branch detect skipped: {exc}")

        if not branch_candidates:
            return UpdateResult(
                target=target_name,
                ok=False,
                changed=False,
                old_version=old_version,
                message="cannot resolve any git branch candidates",
                diagnostics=diagnostics,
            )
        diagnostics.append(
            "branch candidates: "
            + ", ".join(candidate for candidate in branch_candidates if candidate),
        )
        pull_rebase_fallback = _to_bool(
            target_cfg.get("pull_rebase_fallback", False),
            False,
        )
        clone_build_fallback = _to_bool(
            target_cfg.get("clone_build_fallback", True),
            True,
        )

        pull_errors: list[str] = []
        pulled = False
        pulled_branch = ""
        pulled_remote = ""
        build_repo_path = repo_path
        temp_repo_path = ""
        for remote in remotes:
            for branch_candidate in branch_candidates:
                pull_cmd = self._git_repo_command(
                    repo_path,
                    (
                        "pull --ff-only "
                        f"{shlex.quote(remote)} {shlex.quote(branch_candidate)}"
                    ),
                    safe_directory=repo_safe_override,
                )
                diagnostics.append(f"attempt pull: {pull_cmd}")
                if dry_run:
                    pulled = True
                    pulled_branch = branch_candidate
                    pulled_remote = remote
                    diagnostics.append("dry-run: pull skipped")
                    break
                pull_res = await self.runner.run(pull_cmd, timeout_s=update_timeout)
                diagnostics.append(
                    (
                        f"pull remote={remote} branch={branch_candidate} "
                        f"exit={pull_res.exit_code} duration={pull_res.duration_s:.2f}s"
                    ),
                )
                if pull_res.ok:
                    pulled = True
                    pulled_branch = branch_candidate
                    pulled_remote = remote
                    break
                stderr_text = pull_res.stderr.strip()
                pull_errors.append(f"{remote}@{branch_candidate}: {stderr_text}")
                if self._is_missing_remote_ref(stderr_text):
                    diagnostics.append(
                        (
                            "pull fallback triggered by missing remote ref: "
                            f"remote={remote} branch={branch_candidate}"
                        ),
                    )
                    continue
                if pull_rebase_fallback and self._is_ff_only_rejected(stderr_text):
                    rebase_cmd = self._git_repo_command(
                        repo_path,
                        (
                            "pull --rebase "
                            f"{shlex.quote(remote)} {shlex.quote(branch_candidate)}"
                        ),
                        safe_directory=repo_safe_override,
                    )
                    diagnostics.append(
                        (
                            "pull rebase fallback: "
                            f"remote={remote} branch={branch_candidate}"
                        ),
                    )
                    rebase_res = await self.runner.run(rebase_cmd, timeout_s=update_timeout)
                    diagnostics.append(
                        (
                            f"pull --rebase remote={remote} branch={branch_candidate} "
                            f"exit={rebase_res.exit_code} duration={rebase_res.duration_s:.2f}s"
                        ),
                    )
                    if rebase_res.ok:
                        pulled = True
                        pulled_branch = branch_candidate
                        pulled_remote = remote
                        break
                    pull_errors.append(
                        f"{remote}@{branch_candidate} rebase: {rebase_res.stderr.strip()}",
                    )
                break
            if pulled:
                break

        if not pulled:
            if clone_build_fallback:
                try:
                    temp_repo_path, cloned_remote, cloned_branch = await self._clone_repo_for_build(
                        target_name,
                        remotes,
                        branch_candidates,
                        timeout_s=update_timeout,
                        diagnostics=diagnostics,
                    )
                    build_repo_path = temp_repo_path
                    pulled = True
                    pulled_remote = cloned_remote
                    pulled_branch = cloned_branch
                    diagnostics.append(
                        (
                            "clone-build fallback selected: "
                            f"remote={cloned_remote} branch={cloned_branch} path={temp_repo_path}"
                        ),
                    )
                except Exception as exc:
                    pull_errors.append(str(exc))
            if not pulled:
                self._cleanup_temp_repo(temp_repo_path, diagnostics)
                return UpdateResult(
                    target=target_name,
                    ok=False,
                    changed=False,
                    old_version=old_version,
                    message=f"all git pull attempts failed: {' | '.join(pull_errors)}",
                    diagnostics=diagnostics,
                )

        if pulled_remote and pulled_branch:
            diagnostics.append(
                f"pull success remote={pulled_remote} branch={pulled_branch}",
            )

        build_commands = ensure_str_list(target_cfg.get("build_commands"))
        if not build_commands:
            build_commands = ["cargo install --path {repo_path}"]

        cmd_ctx = dict(runtime_ctx)
        cmd_ctx["repo_path"] = build_repo_path
        cmd_ctx["branch"] = pulled_branch or branch_candidates[0]

        for command in build_commands:
            rendered = render_template(command, cmd_ctx)
            diagnostics.append(f"build command: {rendered}")
            if dry_run:
                diagnostics.append("dry-run: build command skipped")
                continue
            build_res = await self.runner.run(rendered, timeout_s=update_timeout)
            diagnostics.append(
                f"build exit={build_res.exit_code} duration={build_res.duration_s:.2f}s cmd={rendered}",
            )
            if not build_res.ok:
                if self._should_retry_cargo_install_with_force(rendered, build_res.stderr):
                    retry_cmd = f"{rendered} --force"
                    diagnostics.append(f"build retry with --force: {retry_cmd}")
                    retry_res = await self.runner.run(retry_cmd, timeout_s=update_timeout)
                    diagnostics.append(
                        (
                            f"build retry exit={retry_res.exit_code} "
                            f"duration={retry_res.duration_s:.2f}s cmd={retry_cmd}"
                        ),
                    )
                    if retry_res.ok:
                        continue
                    build_res = retry_res
                self._cleanup_temp_repo(temp_repo_path, diagnostics)
                stderr_text = build_res.stderr.strip()
                message = f"build command failed: {rendered}"
                if stderr_text:
                    message += f" | stderr: {stderr_text}"
                return UpdateResult(
                    target=target_name,
                    ok=False,
                    changed=False,
                    old_version=old_version,
                    message=message,
                    diagnostics=diagnostics,
                )

        verify_cmd = _safe_str(target_cfg.get("verify_cmd")).strip()
        if verify_cmd:
            rendered = render_template(verify_cmd, cmd_ctx)
            diagnostics.append(f"verify command: {rendered}")
            if dry_run:
                diagnostics.append("dry-run: verify command skipped")
            else:
                verify_res = await self.runner.run(
                    rendered,
                    timeout_s=int(target_cfg.get("verify_timeout_s", 120)),
                )
                diagnostics.append(
                    f"verify exit={verify_res.exit_code} duration={verify_res.duration_s:.2f}s",
                )
                if not verify_res.ok:
                    self._cleanup_temp_repo(temp_repo_path, diagnostics)
                    return UpdateResult(
                        target=target_name,
                        ok=False,
                        changed=False,
                        old_version=old_version,
                        message=f"verify command failed: {rendered}",
                        diagnostics=diagnostics,
                    )

        new_check = await self.check(target_name, target_cfg, runtime_ctx)
        diagnostics.extend(new_check.diagnostics)
        if not new_check.ok:
            self._cleanup_temp_repo(temp_repo_path, diagnostics)
            return UpdateResult(
                target=target_name,
                ok=False,
                changed=False,
                old_version=old_version,
                message=f"update finished but post-check failed: {new_check.message}",
                diagnostics=diagnostics,
            )

        changed = old_version != new_check.current_version
        message = "update completed"
        if new_check.latest_version and compare_versions(
            new_check.current_version,
            new_check.latest_version,
        ) == -1:
            message = (
                f"update completed but still behind latest: "
                f"{new_check.current_version} < {new_check.latest_version}"
            )

        self._cleanup_temp_repo(temp_repo_path, diagnostics)
        return UpdateResult(
            target=target_name,
            ok=True,
            changed=changed,
            old_version=old_version,
            new_version=new_check.current_version,
            message=message,
            diagnostics=diagnostics,
        )


def build_strategy(
    strategy_name: str,
    runner: CommandRunner,
    logger: Callable[[str], None] | None = None,
) -> BaseStrategy:
    normalized = _safe_str(strategy_name).strip().lower()
    if normalized in {"command", "cmd"}:
        return CommandStrategy(runner, logger=logger)
    if normalized in {"cargo_path_git", "git_cargo"}:
        return CargoPathGitStrategy(runner, logger=logger)
    raise StrategyError(f"unsupported strategy: {strategy_name}")
