"""
Fan Tracking Router - Score d'interet des fans.
Contrat Phase 7 : Suivi comportemental.

Par defaut use_ai=false (chemin regex seul, rapide, zero risque).
Le scoring IA est optionnel et doit etre active explicitement.
"""
import asyncio
import json
import logging
import re
import traceback
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

fan_router = APIRouter(prefix="/fan", tags=["Fan Tracking"])
logger = logging.getLogger(__name__)
if not logger.handlers:
    logging.basicConfig(level=logging.INFO)

# Timeout court pour le scoring IA (pas de boucle, 1 seul appel)
_AI_TIMEOUT_S = 8


# -- Schemas ------------------------------------------------------------------

class InterestScoreRequest(BaseModel):
    session_id: Optional[str] = None
    fan_id: Optional[str] = None
    history: List[Dict[str, Any]] = Field(default_factory=list)
    purchases: List[Dict[str, Any]] = Field(default_factory=list)
    last_activity_iso: Optional[str] = None
    use_ai: bool = Field(False, description="False par defaut. Active le scoring IA (1 appel, timeout 8s).")


class InterestScoreResponse(BaseModel):
    fan_id: Optional[str] = None
    session_id: Optional[str] = None
    score: float = Field(0, description="Score global 0-100")
    engagement_score: float = 0
    purchase_score: float = 0
    recency_score: float = 0
    ai_score: Optional[float] = Field(None, description="Score IA si active et reussi, sinon null")
    segment: str = "cold"
    signals: List[str] = Field(default_factory=list)
    recommended_action: str = ""
    scoring_method: str = Field("regex", description="'ai' ou 'regex'")
    error: Optional[str] = None


class BulkInterestRequest(BaseModel):
    fans: List[InterestScoreRequest]


class BulkInterestResponse(BaseModel):
    results: List[InterestScoreResponse]
    errors_count: int = 0


# -- Signaux regex (chemin principal, rapide, fiable) -------------------------

POS_SIGNALS = [
    (r"\b(j'?ai envie|je veux|montre|envoie|photo|vid[eé]o|pack|ppv|contenu)\b", "intent_purchase", 8),
    (r"\b(combien|prix|co[uû]t|tarif)\b", "asks_price", 10),
    (r"\b(excit[eé]|chaud|bande|mouill|envie de toi)\b", "high_arousal", 6),
    (r"\b(t'?es (trop )?belle|magnifique|canon|bombe)\b", "compliment", 4),
    (r"\b(je reviens|[aà] (tout|toute|ce soir|demain))\b", "return_intent", 5),
]
NEG_SIGNALS = [
    (r"\b(gratuit|free|gratos|pas payer)\b", "freeloader", -8),
    (r"\b(arnaque|scam|fake|robot|ia|bot)\b", "suspicious", -10),
    (r"\b(bye|ciao|au revoir|j'?arr[eê]te)\b", "leaving", -5),
    (r"\b(non merci|pas int[eé]ress|bof)\b", "disengaged", -6),
]


def _regex_engagement(history: List[Dict[str, Any]]) -> tuple:
    """Score regex pur. Rapide, deterministe, jamais d'erreur."""
    try:
        if not history:
            return 0.0, []
        signals, raw = [], 0.0
        user_msgs = [m for m in history if m.get("role") == "user"]
        mc = len(user_msgs)
        if mc >= 20:
            raw += 25
            signals.append("high_volume")
        elif mc >= 10:
            raw += 15
            signals.append("medium_volume")
        elif mc >= 5:
            raw += 8
        else:
            raw += 3
        if user_msgs:
            avg = sum(len(str(m.get("content", ""))) for m in user_msgs) / max(1, len(user_msgs))
            if avg > 100:
                raw += 10
                signals.append("long_messages")
            elif avg > 40:
                raw += 5
        for m in user_msgs:
            c = str(m.get("content", "")).lower()
            for pat, sig, pts in POS_SIGNALS:
                try:
                    if re.search(pat, c, re.IGNORECASE) and sig not in signals:
                        signals.append(sig)
                        raw += pts
                except Exception:
                    pass
            for pat, sig, pts in NEG_SIGNALS:
                try:
                    if re.search(pat, c, re.IGNORECASE) and sig not in signals:
                        signals.append(sig)
                        raw += pts
                except Exception:
                    pass
        return max(0.0, min(100.0, raw)), signals
    except Exception as e:
        logger.warning("[fan] regex error (non-bloquant): %s", e)
        return 10.0, ["regex_error"]


def _purchase_score(purchases: List[Dict[str, Any]]) -> float:
    """Score achat. Toujours un float, jamais d'exception."""
    try:
        if not purchases:
            return 0.0
        total = 0.0
        for p in purchases:
            try:
                total += float(p.get("amount", 0))
            except (ValueError, TypeError):
                pass
        return min(100.0, min(50.0, total * 2) + min(50.0, len(purchases) * 10))
    except Exception:
        return 0.0


def _recency_score(iso: Optional[str]) -> float:
    """Score recence. Toujours un float, jamais d'exception."""
    try:
        if not iso:
            return 50.0
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
        h = (now - dt).total_seconds() / 3600
        if h < 1:
            return 100.0
        if h < 6:
            return 85.0
        if h < 24:
            return 70.0
        if h < 72:
            return 50.0
        if h < 168:
            return 30.0
        return max(5.0, 30.0 - (h - 168) / 24)
    except Exception:
        return 50.0


def _extract_json_from_llm(raw: str) -> Optional[dict]:
    """
    Extraction robuste de JSON depuis une reponse LLM potentiellement sale.
    Gere: backticks, texte autour, guillemets unicode, accolades imbriquees.
    Retourne None si impossible a parser.
    """
    if not raw or not isinstance(raw, str):
        return None
    try:
        # Nettoyer les backticks markdown
        cleaned = raw.strip()
        cleaned = re.sub(r'```json\s*', '', cleaned)
        cleaned = re.sub(r'```\s*', '', cleaned)
        cleaned = cleaned.strip()

        # Remplacer guillemets unicode par des guillemets ASCII
        cleaned = cleaned.replace('\u201c', '"').replace('\u201d', '"')
        cleaned = cleaned.replace('\u2018', "'").replace('\u2019', "'")

        # Tenter le parse direct
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        # Extraire le premier bloc JSON avec accolades
        brace_depth = 0
        start = -1
        for i, ch in enumerate(cleaned):
            if ch == '{':
                if brace_depth == 0:
                    start = i
                brace_depth += 1
            elif ch == '}':
                brace_depth -= 1
                if brace_depth == 0 and start >= 0:
                    candidate = cleaned[start:i + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        # Tenter de corriger les trailing commas
                        fixed = re.sub(r',\s*}', '}', candidate)
                        fixed = re.sub(r',\s*]', ']', fixed)
                        try:
                            return json.loads(fixed)
                        except json.JSONDecodeError:
                            pass
                    start = -1

        # Dernier recours: regex simple pour score numerique
        score_match = re.search(r'"score"\s*:\s*(\d+(?:\.\d+)?)', cleaned)
        if score_match:
            return {"score": float(score_match.group(1)), "signals": [], "action": ""}

        return None
    except Exception:
        return None


def _segment(score: float) -> str:
    if score >= 75:
        return "vip"
    if score >= 50:
        return "hot"
    if score >= 25:
        return "warm"
    return "cold"


def _action(seg: str, signals: List[str]) -> str:
    if "intent_purchase" in signals or "asks_price" in signals or "ready_to_buy" in signals:
        return "CLOSING: Intention d'achat. Proposer PPV/pack maintenant."
    if seg == "vip":
        return "FIDELISATION: Contenu exclusif, attention personnalisee, upsell."
    if seg == "hot":
        return "TEASING: Intensifier sexting, preparer la vente."
    if seg == "warm":
        return "ENGAGEMENT: Relance contextualisee, creer du lien."
    if "freeloader" in signals:
        return "QUALIFICATION: Probable freeloader. Tester ou ignorer."
    if "suspicious" in signals:
        return "PRUDENCE: Fan doute. Rassurer sans insister."
    return "HOOK: Fan froid. Relance legere, question ouverte."


async def _single_ai_call(history: List[Dict[str, Any]]) -> Optional[tuple]:
    """
    UN SEUL appel LLM, timeout court, pas de retry, pas de boucle.
    Retourne (score, signals, action) ou None.
    """
    if not history or len(history) < 3:
        return None

    try:
        from ..config import settings
        use_grok = settings.SINHOME_LLM_BACKEND.lower() == "grok"
    except Exception:
        return None

    recent = history[-10:]
    conv_lines = []
    for m in recent:
        role = "FAN" if m.get("role") == "user" else "MODEL"
        content = str(m.get("content", ""))[:120]
        conv_lines.append(f"{role}: {content}")
    conv_text = "\n".join(conv_lines)

    scoring_prompt = [
        {"role": "system", "content": (
            "Analyse cette conv OnlyFans. Reponds UNIQUEMENT en JSON brut (pas de backticks):\n"
            '{"score":NUMBER,"signals":["mot1","mot2"],"action":"phrase"}\n'
            "score: 0=froid 50=interesse 75=chaud 100=acheteur"
        )},
        {"role": "user", "content": conv_text},
    ]

    try:
        if use_grok:
            from ..services.grok_client import get_grok_response
            raw = await asyncio.wait_for(
                get_grok_response(scoring_prompt, temperature=0.1, max_tokens=100),
                timeout=_AI_TIMEOUT_S,
            )
        else:
            from ..services import vllm_client
            raw = await asyncio.wait_for(
                vllm_client.get_vllm_response(scoring_prompt, temperature=0.1, max_tokens=100),
                timeout=_AI_TIMEOUT_S,
            )
    except asyncio.TimeoutError:
        logger.warning("[fan] AI scoring timeout (%ds)", _AI_TIMEOUT_S)
        return None
    except Exception as e:
        logger.warning("[fan] AI scoring call failed: %s", str(e)[:100])
        return None

    data = _extract_json_from_llm(str(raw))
    if data is None:
        logger.warning("[fan] AI scoring: JSON extraction failed from: %s", str(raw)[:150])
        return None

    try:
        ai_sc = float(data.get("score", 50))
        ai_sc = max(0, min(100, ai_sc))
        ai_signals = data.get("signals") or []
        if not isinstance(ai_signals, list):
            ai_signals = []
        ai_signals = [str(s) for s in ai_signals[:10]]
        ai_action = str(data.get("action", ""))[:200]
        return ai_sc, ai_signals, ai_action
    except Exception:
        return None


async def _score_one(req: InterestScoreRequest) -> InterestScoreResponse:
    """Score un fan. JAMAIS d'exception, JAMAIS de boucle."""
    try:
        # Toujours calculer les 3 scores de base (regex, achat, recence)
        eng, signals = _regex_engagement(req.history)
        pur = _purchase_score(req.purchases)
        rec = _recency_score(req.last_activity_iso)

        ai_sc = None
        method = "regex"

        # Scoring IA : 1 seul appel, seulement si explicitement demande
        if req.use_ai and len(req.history) >= 3:
            try:
                ai_result = await _single_ai_call(req.history)
                if ai_result is not None:
                    ai_sc, ai_signals, ai_action = ai_result
                    for s in ai_signals:
                        if s not in signals:
                            signals.append(s)
                    # Moyenne ponderee IA (60%) + regex (40%)
                    eng = ai_sc * 0.6 + eng * 0.4
                    method = "ai"
            except Exception as e:
                logger.warning("[fan] AI scoring skip: %s", str(e)[:100])

        gl = round(min(100.0, max(0.0, eng * 0.45 + pur * 0.35 + rec * 0.20)), 1)
        seg = _segment(gl)
        act = (ai_action if method == "ai" and ai_action else _action(seg, signals))

        return InterestScoreResponse(
            fan_id=req.fan_id, session_id=req.session_id, score=gl,
            engagement_score=round(eng, 1), purchase_score=round(pur, 1),
            recency_score=round(rec, 1),
            ai_score=round(ai_sc, 1) if ai_sc is not None else None,
            segment=seg, signals=signals,
            recommended_action=act, scoring_method=method,
        )
    except Exception as e:
        logger.error("[fan] scoring failure: %s\n%s", e, traceback.format_exc())
        return InterestScoreResponse(
            fan_id=req.fan_id, session_id=req.session_id,
            score=10.0, engagement_score=10.0, purchase_score=0.0, recency_score=50.0,
            segment="cold", signals=["scoring_error"],
            scoring_method="error_fallback",
            recommended_action="ERREUR SCORING: Traiter manuellement.",
            error=str(e)[:200],
        )


@fan_router.post("/interest_score", response_model=InterestScoreResponse,
                 summary="Score d'interet d'un fan (regex par defaut, IA optionnelle)")
async def interest_score(request: InterestScoreRequest):
    logger.info("[fan/interest_score] fan=%s msgs=%d ai=%s",
                request.fan_id or "?", len(request.history), request.use_ai)
    return await _score_one(request)


@fan_router.post("/interest_score/bulk", response_model=BulkInterestResponse,
                 summary="Score bulk (max 200)")
async def bulk_interest(request: BulkInterestRequest):
    if len(request.fans) > 200:
        return BulkInterestResponse(results=[], errors_count=1)
    results = []
    errs = 0
    for f in request.fans:
        r = await _score_one(f)
        if r.error:
            errs += 1
        results.append(r)
    return BulkInterestResponse(results=results, errors_count=errs)
