from __future__ import annotations

import asyncio
import secrets
from pathlib import Path
from typing import Any

from astrbot.api import logger

try:
    import uvicorn
    from fastapi import FastAPI, Request
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse
    from fastapi.staticfiles import StaticFiles

    FASTAPI_AVAILABLE = True
except Exception:
    FASTAPI_AVAILABLE = False
    logger.warning(
        "[onesync] FastAPI/uvicorn is unavailable; WebUI will be disabled.",
    )


class OneSyncWebUIServer:
    """Embedded WebUI server for OneSync plugin."""

    def __init__(self, plugin: Any):
        self.plugin = plugin
        self.config = plugin.config
        self.app: Any = None
        self.server: Any = None
        self._server_task: asyncio.Task | None = None
        self.public_url: str = ""
        self._auth_enabled = False
        self._auth_token: str | None = None

        if FASTAPI_AVAILABLE:
            self._setup_app()

    def _web_cfg(self) -> dict[str, Any]:
        cfg = self.config.get("web_admin", {})
        if isinstance(cfg, dict):
            return cfg
        return {}

    def _setup_app(self) -> None:
        self.app = FastAPI(
            title="OneSync WebUI",
            description="OneSync software updater dashboard",
            version="0.1.0",
        )
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        password = str(self._web_cfg().get("password", "") or "").strip()
        if password:
            self._auth_enabled = True
            self._auth_token = secrets.token_hex(24)

        @self.app.middleware("http")
        async def auth_middleware(request: Request, call_next):
            if not self._auth_enabled:
                return await call_next(request)
            path = request.url.path
            if path in {"/api/auth-info", "/api/login"}:
                return await call_next(request)
            if not path.startswith("/api"):
                return await call_next(request)

            token = request.query_params.get("token", "")
            if not token:
                auth_header = request.headers.get("Authorization", "")
                if auth_header.startswith("Bearer "):
                    token = auth_header[7:]
            if not self._auth_token or not secrets.compare_digest(token, self._auth_token):
                return JSONResponse(
                    {"ok": False, "message": "Unauthorized. Please login first."},
                    status_code=401,
                )
            return await call_next(request)

        self._register_routes()

        web_dir = Path(__file__).resolve().parent / "webui"
        if web_dir.exists():
            self.app.mount("/", StaticFiles(directory=str(web_dir), html=True), name="webui")

    def _register_routes(self) -> None:
        @self.app.get("/api/auth-info")
        async def auth_info():
            return {"ok": True, "auth_required": self._auth_enabled}

        @self.app.post("/api/login")
        async def login(payload: dict[str, Any]):
            if not self._auth_enabled:
                return {"ok": True, "auth_required": False, "token": "no-auth"}
            raw_password = str(self._web_cfg().get("password", "") or "")
            provided = str(payload.get("password", "") or "")
            if secrets.compare_digest(provided, raw_password):
                return {"ok": True, "auth_required": True, "token": self._auth_token}
            return JSONResponse({"ok": False, "message": "Password is incorrect."}, status_code=401)

        @self.app.get("/api/health")
        async def health():
            return {"ok": True, "webui_url": self.public_url, "auth_required": self._auth_enabled}

        @self.app.get("/api/overview")
        async def overview():
            return self.plugin.webui_get_overview_payload()

        @self.app.get("/api/inventory/overview")
        async def inventory_overview():
            return self.plugin.webui_get_inventory_payload()

        @self.app.get("/api/skills/overview")
        async def skills_overview():
            return self.plugin.webui_get_skills_payload()

        @self.app.get("/api/skills/sources")
        async def skills_sources():
            return self.plugin.webui_get_skill_sources_payload()

        @self.app.get("/api/skills/sources/{source_id}")
        async def skill_source_detail(source_id: str):
            ret = self.plugin.webui_get_skill_source_payload(source_id)
            if not ret.get("ok"):
                return JSONResponse(ret, status_code=404)
            return ret

        @self.app.get("/api/skills/deploy-targets/{target_id}")
        async def skill_deploy_target_detail(target_id: str):
            ret = self.plugin.webui_get_deploy_target_payload(target_id)
            if not ret.get("ok"):
                return JSONResponse(ret, status_code=404)
            return ret

        @self.app.post("/api/skills/import")
        async def skills_import(payload: dict[str, Any]):
            return await self.plugin.webui_import_skills(payload)

        @self.app.post("/api/skills/sources/{source_id}/sync")
        async def skill_source_sync(source_id: str, payload: dict[str, Any]):
            _ = payload
            ret = self.plugin.webui_sync_skill_source(source_id)
            if not ret.get("ok"):
                return JSONResponse(ret, status_code=404)
            return ret

        @self.app.post("/api/skills/sources/sync-all")
        async def skill_source_sync_all(payload: dict[str, Any]):
            _ = payload
            ret = self.plugin.webui_sync_all_skill_sources()
            if not ret.get("ok"):
                return JSONResponse(ret, status_code=400)
            return ret

        @self.app.post("/api/skills/sources/{source_id}/deploy")
        async def skill_source_deploy(source_id: str, payload: dict[str, Any]):
            ret = self.plugin.webui_deploy_skill_source(source_id, payload)
            if not ret.get("ok"):
                return JSONResponse(ret, status_code=400)
            return ret

        @self.app.post("/api/skills/deploy-targets/repair-all")
        async def skill_deploy_targets_repair_all(payload: dict[str, Any]):
            ret = self.plugin.webui_repair_all_deploy_targets(payload)
            if not ret.get("ok"):
                return JSONResponse(ret, status_code=400)
            return ret

        @self.app.post("/api/skills/deploy-targets/{target_id}")
        async def skill_deploy_target_update(target_id: str, payload: dict[str, Any]):
            ret = self.plugin.webui_update_deploy_target(target_id, payload)
            if not ret.get("ok"):
                return JSONResponse(ret, status_code=400)
            return ret

        @self.app.post("/api/skills/deploy-targets/{target_id}/repair")
        async def skill_deploy_target_repair(target_id: str, payload: dict[str, Any]):
            ret = self.plugin.webui_repair_deploy_target(target_id, payload)
            if not ret.get("ok"):
                return JSONResponse(ret, status_code=400)
            return ret

        @self.app.post("/api/skills/deploy-targets/{target_id}/reproject")
        async def skill_deploy_target_reproject(target_id: str, payload: dict[str, Any]):
            ret = self.plugin.webui_reproject_deploy_target(target_id, payload)
            if not ret.get("ok"):
                return JSONResponse(ret, status_code=400)
            return ret

        @self.app.post("/api/skills/doctor")
        async def skills_doctor():
            return self.plugin.webui_doctor_skills()

        @self.app.get("/api/inventory/software")
        async def inventory_software():
            snapshot = self.plugin.webui_get_inventory_payload()
            return {
                "ok": bool(snapshot.get("ok", True)),
                "generated_at": snapshot.get("generated_at"),
                "counts": snapshot.get("counts", {}),
                "items": snapshot.get("software_rows", []),
                "warnings": snapshot.get("warnings", []),
            }

        @self.app.get("/api/inventory/skills")
        async def inventory_skills():
            snapshot = self.plugin.webui_get_inventory_payload()
            return {
                "ok": bool(snapshot.get("ok", True)),
                "generated_at": snapshot.get("generated_at"),
                "counts": snapshot.get("counts", {}),
                "items": snapshot.get("skill_rows", []),
                "warnings": snapshot.get("warnings", []),
            }

        @self.app.get("/api/inventory/bindings")
        async def inventory_bindings_list():
            snapshot = self.plugin.webui_get_inventory_payload()
            return {
                "ok": bool(snapshot.get("ok", True)),
                "generated_at": snapshot.get("generated_at"),
                "counts": snapshot.get("counts", {}),
                "items": snapshot.get("binding_rows", []),
                "binding_map": snapshot.get("binding_map", {}),
                "binding_map_by_scope": snapshot.get("binding_map_by_scope", {}),
                "warnings": snapshot.get("warnings", []),
            }

        @self.app.post("/api/inventory/scan")
        async def inventory_scan():
            return await self.plugin.webui_scan_inventory()

        @self.app.post("/api/inventory/bindings")
        async def inventory_bindings(payload: dict[str, Any]):
            ret = self.plugin.webui_update_inventory_bindings(payload)
            if not ret.get("ok"):
                return JSONResponse(ret, status_code=400)
            return ret

        @self.app.get("/api/config")
        async def get_config():
            return self.plugin.webui_get_config_payload()

        @self.app.post("/api/config")
        async def update_config(payload: dict[str, Any]):
            ret = self.plugin.webui_update_config(payload)
            if not ret.get("ok"):
                return JSONResponse(ret, status_code=400)
            return ret

        @self.app.get("/api/jobs/latest")
        async def latest_job():
            latest = self.plugin.webui_get_latest_job()
            return {"ok": True, "job": latest}

        @self.app.get("/api/jobs/{job_id}")
        async def get_job(job_id: str):
            job = self.plugin.webui_get_job(job_id)
            if not job:
                return JSONResponse({"ok": False, "message": "job not found"}, status_code=404)
            return {"ok": True, "job": job}

        @self.app.get("/api/debug/logs")
        async def debug_logs(
            since_id: int = 0,
            limit: int = 200,
            level: str = "all",
            keyword: str = "",
            source_group: str = "all",
        ):
            return self.plugin.webui_get_debug_logs(
                since_id=since_id,
                limit=limit,
                level=level,
                keyword=keyword,
                source_group=source_group,
            )

        @self.app.post("/api/debug/clear")
        async def clear_debug_logs():
            return self.plugin.webui_clear_debug_logs()

        @self.app.post("/api/run")
        async def run_now(payload: dict[str, Any]):
            scope = str(payload.get("scope", "all") or "all").strip().lower()
            targets = payload.get("targets", [])
            ret = await self.plugin.webui_start_run(scope=scope, targets=targets)
            if not ret.get("ok"):
                status = 409 if ret.get("status") == "busy" else 400
                return JSONResponse(ret, status_code=status)
            return ret

    async def start(self) -> None:
        if not FASTAPI_AVAILABLE or self.app is None:
            return
        if self._server_task and not self._server_task.done():
            return

        cfg = self._web_cfg()
        host = str(cfg.get("host", "127.0.0.1") or "127.0.0.1").strip() or "127.0.0.1"
        try:
            port = int(cfg.get("port", 8099))
        except Exception:
            port = 8099
        if port < 1 or port > 65535:
            port = 8099

        uv_config = uvicorn.Config(
            self.app,
            host=host,
            port=port,
            log_level="warning",
            access_log=False,
        )
        self.server = uvicorn.Server(uv_config)
        self._server_task = asyncio.create_task(
            self.server.serve(),
            name="onesync-webui-server",
        )

        display_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
        self.public_url = f"http://{display_host}:{port}"
        logger.info(
            "[onesync] webui started: bind=%s:%s url=%s auth_enabled=%s",
            host,
            port,
            self.public_url,
            self._auth_enabled,
        )

    async def stop(self) -> None:
        if self.server is not None:
            self.server.should_exit = True

        if self._server_task is not None:
            try:
                await asyncio.wait_for(self._server_task, timeout=8)
            except asyncio.TimeoutError:
                self._server_task.cancel()
                try:
                    await self._server_task
                except asyncio.CancelledError:
                    pass
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logger.warning("[onesync] webui server task stop error: %s", exc)

        self._server_task = None
        self.server = None
        self.public_url = ""
