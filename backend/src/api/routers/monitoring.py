"""
Monitoring Router - Metriques et sante du systeme.
Contrat Phase 1/11 : Monitoring minimal et continu.
Toutes les operations sont non-bloquantes (try/except partout).
"""
import asyncio
import logging
import time
import traceback
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..config import settings

monitoring_router = APIRouter(prefix="/monitoring", tags=["Monitoring"])
logger = logging.getLogger(__name__)
if not logger.handlers:
    logging.basicConfig(level=logging.INFO)


class _Metrics:
    """Compteurs in-memory, reset au redemarrage du container."""
    def __init__(self):
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.total_requests = 0
        self.total_errors = 0
        self.total_refusals_caught = 0
        self.total_chinese_retries = 0
        self.total_dup_retries = 0
        self.endpoint_counts: Dict[str, int] = {}
        self.last_request_at: Optional[str] = None
        self.avg_latency_ms = 0.0
        self._latency_sum = 0.0
        self._latency_count = 0

    def record_request(self, endpoint: str, latency_ms: float = 0.0):
        try:
            self.total_requests += 1
            self.endpoint_counts[endpoint] = self.endpoint_counts.get(endpoint, 0) + 1
            self.last_request_at = datetime.now(timezone.utc).isoformat()
            if latency_ms > 0:
                self._latency_sum += latency_ms
                self._latency_count += 1
                self.avg_latency_ms = round(self._latency_sum / self._latency_count, 1)
        except Exception:
            pass

    def record_error(self):
        try: self.total_errors += 1
        except Exception: pass
    def record_refusal(self):
        try: self.total_refusals_caught += 1
        except Exception: pass
    def record_chinese_retry(self):
        try: self.total_chinese_retries += 1
        except Exception: pass
    def record_dup_retry(self):
        try: self.total_dup_retries += 1
        except Exception: pass

    def to_dict(self):
        try:
            return {
                "started_at": self.started_at, "total_requests": self.total_requests,
                "total_errors": self.total_errors, "total_refusals_caught": self.total_refusals_caught,
                "total_chinese_retries": self.total_chinese_retries,
                "total_dup_retries": self.total_dup_retries,
                "endpoint_counts": dict(self.endpoint_counts),
                "last_request_at": self.last_request_at,
                "avg_latency_ms": self.avg_latency_ms,
            }
        except Exception:
            return {"error": "metrics_corrupted", "started_at": self.started_at}

metrics = _Metrics()


class ComponentStatus(BaseModel):
    name: str
    status: str  # ok, degraded, down
    latency_ms: Optional[float] = None
    details: Optional[str] = None

class HealthResponse(BaseModel):
    status: str  # healthy, degraded, unhealthy
    timestamp: str
    uptime_since: str
    llm_backend: str
    model_name: str
    components: list[ComponentStatus]
    metrics: Dict[str, Any]


async def _check_vllm() -> ComponentStatus:
    """Verifie vLLM. Ne leve JAMAIS d'exception."""
    try:
        url = f"{settings.VLLM_API_BASE_URL}/models"
        start = time.monotonic()
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
            lat = round((time.monotonic() - start) * 1000, 1)
            if resp.status_code == 200:
                return ComponentStatus(name="vllm", status="ok", latency_ms=lat)
            return ComponentStatus(name="vllm", status="degraded", latency_ms=lat, details=f"HTTP {resp.status_code}")
    except httpx.ConnectError:
        return ComponentStatus(name="vllm", status="down", details="Connection refused")
    except httpx.TimeoutException:
        return ComponentStatus(name="vllm", status="down", details="Timeout 10s")
    except Exception as e:
        return ComponentStatus(name="vllm", status="down", details=str(e)[:200])

async def _check_grok() -> ComponentStatus:
    """Verifie Grok. Ne leve JAMAIS d'exception."""
    try:
        if not settings.GROK:
            return ComponentStatus(name="grok", status="degraded", details="API key absente")
        url = f"{settings.GROK_API_BASE_URL}/v1/models"
        headers = {"Authorization": f"Bearer {settings.GROK}"}
        start = time.monotonic()
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=headers)
            lat = round((time.monotonic() - start) * 1000, 1)
            if resp.status_code == 200:
                return ComponentStatus(name="grok", status="ok", latency_ms=lat)
            return ComponentStatus(name="grok", status="degraded", latency_ms=lat, details=f"HTTP {resp.status_code}")
    except Exception as e:
        return ComponentStatus(name="grok", status="down", details=str(e)[:200])

async def _check_db() -> ComponentStatus:
    """Verifie la connectivite DB (si configuree). Non-bloquant."""
    try:
        db_url = settings.DATABASE_URL if hasattr(settings, 'DATABASE_URL') else None
        if not db_url:
            return ComponentStatus(name="database", status="degraded", details="Non configuree")
        # Simple TCP check sur le port DB
        import socket
        host = settings.DB_HOST if hasattr(settings, 'DB_HOST') else "172.17.0.1"
        port = int(settings.DB_PORT) if hasattr(settings, 'DB_PORT') else 5432
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        start = time.monotonic()
        result = sock.connect_ex((host, port))
        lat = round((time.monotonic() - start) * 1000, 1)
        sock.close()
        if result == 0:
            return ComponentStatus(name="database", status="ok", latency_ms=lat)
        return ComponentStatus(name="database", status="down", details=f"Port {port} ferme")
    except Exception as e:
        return ComponentStatus(name="database", status="down", details=str(e)[:200])


@monitoring_router.get("/health", response_model=HealthResponse, summary="Health check detaille")
async def health_check():
    try:
        components = await asyncio.gather(
            _check_vllm(), _check_grok(), _check_db(),
            return_exceptions=True,
        )
        # Convertir les exceptions en ComponentStatus
        safe_components = []
        for c in components:
            if isinstance(c, Exception):
                safe_components.append(ComponentStatus(name="unknown", status="down", details=str(c)[:200]))
            else:
                safe_components.append(c)

        all_ok = all(c.status == "ok" for c in safe_components)
        any_down = any(c.status == "down" for c in safe_components)
        gs = "healthy" if all_ok else ("unhealthy" if any_down else "degraded")

        return HealthResponse(
            status=gs, timestamp=datetime.now(timezone.utc).isoformat(),
            uptime_since=metrics.started_at, llm_backend=settings.SINHOME_LLM_BACKEND,
            model_name=settings.VLLM_MODEL_NAME, components=safe_components,
            metrics=metrics.to_dict(),
        )
    except Exception as e:
        logger.error("[monitoring/health] error: %s", traceback.format_exc())
        return HealthResponse(
            status="unhealthy", timestamp=datetime.now(timezone.utc).isoformat(),
            uptime_since=metrics.started_at, llm_backend="unknown", model_name="unknown",
            components=[ComponentStatus(name="self", status="down", details=str(e)[:200])],
            metrics={"error": str(e)[:200]},
        )

@monitoring_router.get("/metrics", summary="Metriques brutes")
async def get_metrics():
    return metrics.to_dict()

@monitoring_router.post("/metrics/reset", summary="Reset metriques")
async def reset_metrics():
    global metrics
    metrics = _Metrics()
    return {"status": "ok"}
