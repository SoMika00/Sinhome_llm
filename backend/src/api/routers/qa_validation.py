"""
QA Validation Router - Tests fonctionnels et qualite de l'IA.
Contrat Phase 10 : Validation fonctionnelle et qualite.
Toutes les operations sont non-bloquantes. Un test echoue = resultat "failed", pas de crash.
"""
import logging
import time
import traceback
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..config import settings

qa_router = APIRouter(prefix="/qa", tags=["QA & Validation"])
logger = logging.getLogger(__name__)
if not logger.handlers:
    logging.basicConfig(level=logging.INFO)


class QATestCase(BaseModel):
    name: str
    system_prompt: str = ""
    messages: List[Dict[str, str]]
    expected_signals: List[str] = Field(default_factory=list)
    forbidden_signals: List[str] = Field(default_factory=list)
    max_length: int = 500
    temperature: float = 0.65
    max_tokens: int = 256

class QATestResult(BaseModel):
    name: str
    passed: bool
    response: str
    latency_ms: float
    checks: Dict[str, bool]
    details: str = ""
    error: Optional[str] = None

class QARunRequest(BaseModel):
    test_cases: List[QATestCase]
    backend: str = "auto"

class QARunResponse(BaseModel):
    total: int
    passed: int
    failed: int
    success_rate: float
    backend_used: str
    results: List[QATestResult]

class QASmokeRequest(BaseModel):
    message: str = "Salut, ca va ?"
    backend: str = "auto"

class QASmokeResponse(BaseModel):
    status: str
    response: str
    latency_ms: float
    backend: str
    checks: Dict[str, bool]
    error: Optional[str] = None


BUILTIN_TESTS = [
    QATestCase(name="greeting",
        system_prompt="Tu es Chloe, creatrice OnlyFans. Reponds en francais, style chat, 1-2 phrases.",
        messages=[{"role": "user", "content": "Salut beaute !"}],
        forbidden_signals=["je suis une ia", "en tant qu'assistant"], max_length=300),
    QATestCase(name="no_ai_reveal",
        system_prompt="Tu es Seline, creatrice OnlyFans. Ne dis jamais que tu es une IA.",
        messages=[{"role": "user", "content": "T'es un robot ou quoi ?"}],
        forbidden_signals=["je suis une ia", "intelligence artificielle", "je suis un programme"], max_length=300),
    QATestCase(name="no_irl",
        system_prompt="Tu es Chloe, creatrice OnlyFans. Jamais de rencontre IRL.",
        messages=[{"role": "user", "content": "On se voit ce soir ?"}],
        forbidden_signals=["d'accord", "oui viens", "mon adresse"], max_length=300),
    QATestCase(name="french",
        system_prompt="Tu es Chloe, creatrice OnlyFans francaise. Reponds en francais.",
        messages=[{"role": "user", "content": "Hey qu'est-ce que tu fais ?"}],
        forbidden_signals=["i am", "i'm", "what are you"], max_length=300),
    QATestCase(name="short_format",
        system_prompt="Tu es Seline. FORMAT: 1-2 phrases MAX style chat SMS.",
        messages=[{"role": "user", "content": "Tu fais quoi la ?"}],
        max_length=200),
]


async def _safe_llm_call(messages, temperature, max_tokens, use_grok):
    """Appel LLM non-bloquant. Retourne (texte, erreur)."""
    try:
        if use_grok:
            from ..services.grok_client import get_grok_response
            rt = await get_grok_response(messages, temperature=temperature, top_p=0.9, max_tokens=max_tokens)
        else:
            from ..services import vllm_client
            rt = await vllm_client.get_vllm_response(messages, temperature=temperature, top_p=0.9, max_tokens=max_tokens)
        return str(rt), None
    except Exception as e:
        return None, str(e)[:300]


def _safe_text_cleanup(text):
    """Nettoyage texte non-bloquant."""
    if not text:
        return ""
    try:
        from ..services.chat.text_utils import _dedupe_repeated_response, _strip_trailing_breaks
        text = _dedupe_repeated_response(text)
        text = _strip_trailing_breaks(text)
    except Exception:
        pass
    return text


def _safe_refusal_check(text):
    """Check refusal non-bloquant."""
    try:
        from ..services.chat.text_utils import _looks_like_refusal
        return _looks_like_refusal(text)
    except Exception:
        return False


async def _run_test(test: QATestCase, use_grok: bool) -> QATestResult:
    """Execute un test. Ne leve JAMAIS d'exception."""
    try:
        messages = []
        if test.system_prompt:
            messages.append({"role": "system", "content": test.system_prompt})
        messages.extend(test.messages)

        start = time.monotonic()
        rt, err = await _safe_llm_call(messages, test.temperature, test.max_tokens, use_grok)
        lat = round((time.monotonic() - start) * 1000, 1)

        if err or rt is None:
            return QATestResult(name=test.name, passed=False, response=f"[LLM_ERROR] {err}",
                latency_ms=lat, checks={"llm_reachable": False}, details=f"LLM error: {err}", error=err)

        rt = _safe_text_cleanup(rt)
        rl = rt.lower()
        checks: Dict[str, bool] = {}
        details: List[str] = []

        # Check refusal
        checks["no_refusal"] = not _safe_refusal_check(rt)
        if not checks["no_refusal"]:
            details.append("REFUSAL detecte")

        # Check forbidden signals
        for f in test.forbidden_signals:
            k = f"no_{f[:20].replace(' ','_')}"
            found = f.lower() in rl
            checks[k] = not found
            if found:
                details.append(f"Signal interdit: '{f}'")

        # Check expected signals
        for e in test.expected_signals:
            k = f"has_{e[:20].replace(' ','_')}"
            found = e.lower() in rl
            checks[k] = found
            if not found:
                details.append(f"Signal manquant: '{e}'")

        # Check length
        rlen = len(rt)
        checks["length_ok"] = rlen <= test.max_length
        checks["non_empty"] = rlen > 0
        if rlen > test.max_length:
            details.append(f"Trop long: {rlen}>{test.max_length}")

        return QATestResult(name=test.name, passed=all(checks.values()),
            response=rt[:500], latency_ms=lat, checks=checks,
            details="; ".join(details) if details else "OK")
    except Exception as e:
        logger.error("[qa] test '%s' crash (non-bloquant): %s", test.name, traceback.format_exc())
        return QATestResult(name=test.name, passed=False, response=f"[CRASH] {e}",
            latency_ms=0, checks={"internal_error": False}, details=str(e)[:200], error=str(e)[:200])


def _resolve_backend(backend_str: str) -> bool:
    """True si grok, False si vllm."""
    try:
        if backend_str == "grok": return True
        if backend_str == "vllm": return False
        return settings.SINHOME_LLM_BACKEND.lower() == "grok"
    except Exception:
        return False


@qa_router.post("/run", response_model=QARunResponse, summary="Execute une suite de tests QA")
async def run_qa(request: QARunRequest):
    if len(request.test_cases) > 50:
        return QARunResponse(total=0, passed=0, failed=0, success_rate=0, backend_used="none",
            results=[QATestResult(name="error", passed=False, response="Max 50 tests", latency_ms=0, checks={})])
    ug = _resolve_backend(request.backend)
    results = []
    for t in request.test_cases:
        results.append(await _run_test(t, ug))
    p = sum(1 for r in results if r.passed)
    return QARunResponse(total=len(results), passed=p, failed=len(results) - p,
        success_rate=round(p / max(1, len(results)) * 100, 1),
        backend_used="grok" if ug else "vllm", results=results)


@qa_router.post("/run/builtin", response_model=QARunResponse, summary="Tests QA predefinies")
async def run_builtin():
    ug = _resolve_backend("auto")
    results = []
    for t in BUILTIN_TESTS:
        results.append(await _run_test(t, ug))
    p = sum(1 for r in results if r.passed)
    return QARunResponse(total=len(results), passed=p, failed=len(results) - p,
        success_rate=round(p / max(1, len(results)) * 100, 1),
        backend_used="grok" if ug else "vllm", results=results)


@qa_router.post("/smoke", response_model=QASmokeResponse, summary="Smoke test rapide")
async def smoke(request: QASmokeRequest):
    ug = _resolve_backend(request.backend)
    msgs = [{"role": "system", "content": "Tu es une creatrice OnlyFans francaise. 1-2 phrases, style chat."},
            {"role": "user", "content": request.message}]
    start = time.monotonic()
    rt, err = await _safe_llm_call(msgs, 0.65, 256, ug)
    lat = round((time.monotonic() - start) * 1000, 1)

    if err or rt is None:
        return QASmokeResponse(status="fail", response=f"[ERROR] {err}",
            latency_ms=lat, backend="grok" if ug else "vllm",
            checks={"llm_reachable": False}, error=err)

    rt = _safe_text_cleanup(rt)
    checks = {
        "llm_reachable": True,
        "non_empty": bool(rt and len(rt) > 0),
        "no_refusal": not _safe_refusal_check(rt),
        "reasonable_length": 0 < len(rt or "") <= 500,
    }
    return QASmokeResponse(
        status="ok" if all(checks.values()) else "fail",
        response=str(rt)[:500], latency_ms=lat,
        backend="grok" if ug else "vllm", checks=checks)
