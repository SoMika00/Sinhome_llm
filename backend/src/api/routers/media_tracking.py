"""
Media Tracking Router - Anti-redondance et recommandation de medias.
Contrat Phase 6 : Recommandation et anti-redondance des medias.
Stockage in-memory (dict). Peut etre connecte a la DB PostgreSQL plus tard.
Toutes les operations sont non-bloquantes (try/except partout).
"""
import logging
import traceback
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

media_tracker_router = APIRouter(prefix="/media", tags=["Media Tracking"])
logger = logging.getLogger(__name__)
if not logger.handlers:
    logging.basicConfig(level=logging.INFO)

# Stockage in-memory : {fan_id: {media_id: {meta}}}
# A migrer vers PostgreSQL (seline_db) quand le CRM sera connecte
_sent_media: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(dict)


class MediaSentRecord(BaseModel):
    fan_id: str
    media_id: str
    media_type: str = "photo"
    media_tags: List[str] = Field(default_factory=list)
    context: str = ""

class MediaSentResponse(BaseModel):
    fan_id: str
    media_id: str
    recorded: bool
    already_sent_before: bool
    times_sent: int
    error: Optional[str] = None

class CheckDuplicateRequest(BaseModel):
    fan_id: str
    media_ids: List[str]

class CheckDuplicateResponse(BaseModel):
    fan_id: str
    results: Dict[str, bool]
    duplicates: List[str]
    safe_to_send: List[str]
    error: Optional[str] = None

class RecommendRequest(BaseModel):
    fan_id: str
    available_media: List[Dict[str, Any]]
    max_results: int = Field(5, ge=1, le=20)
    exclude_sent: bool = True

class RecommendResponse(BaseModel):
    fan_id: str
    recommended: List[Dict[str, Any]]
    excluded_count: int
    error: Optional[str] = None

class FanMediaHistory(BaseModel):
    fan_id: str
    sent_media: Dict[str, Dict[str, Any]]
    total_sent: int

class ImportMediaHistoryRequest(BaseModel):
    fan_id: str
    sent_media: Dict[str, Dict[str, Any]]


@media_tracker_router.post("/sent", response_model=MediaSentResponse, summary="Enregistre un envoi de media")
async def record_sent(record: MediaSentRecord):
    try:
        fh = _sent_media[record.fan_id]
        already = record.media_id in fh
        now = datetime.now(timezone.utc).isoformat()
        if already:
            fh[record.media_id]["count"] = fh[record.media_id].get("count", 1) + 1
            fh[record.media_id]["last_sent_at"] = now
        else:
            fh[record.media_id] = {
                "media_type": record.media_type, "tags": record.media_tags,
                "context": record.context, "first_sent_at": now,
                "last_sent_at": now, "count": 1,
            }
        return MediaSentResponse(fan_id=record.fan_id, media_id=record.media_id,
            recorded=True, already_sent_before=already, times_sent=fh[record.media_id]["count"])
    except Exception as e:
        logger.error("[media/sent] error: %s", traceback.format_exc())
        return MediaSentResponse(fan_id=record.fan_id, media_id=record.media_id,
            recorded=False, already_sent_before=False, times_sent=0, error=str(e)[:200])


@media_tracker_router.post("/check_duplicates", response_model=CheckDuplicateResponse, summary="Verifie les doublons")
async def check_dups(request: CheckDuplicateRequest):
    try:
        fh = _sent_media.get(request.fan_id, {})
        results, dups, safe = {}, [], []
        for mid in request.media_ids:
            is_dup = mid in fh
            results[mid] = is_dup
            (dups if is_dup else safe).append(mid)
        return CheckDuplicateResponse(fan_id=request.fan_id, results=results, duplicates=dups, safe_to_send=safe)
    except Exception as e:
        logger.error("[media/check_duplicates] error: %s", traceback.format_exc())
        return CheckDuplicateResponse(fan_id=request.fan_id, results={},
            duplicates=[], safe_to_send=list(request.media_ids), error=str(e)[:200])


@media_tracker_router.post("/recommend", response_model=RecommendResponse, summary="Recommande les medias a envoyer")
async def recommend(request: RecommendRequest):
    try:
        fh = _sent_media.get(request.fan_id, {})
        exc = 0
        cands = []
        for m in request.available_media:
            mid = m.get("media_id", "")
            if request.exclude_sent and mid in fh:
                exc += 1
                continue
            cands.append(m)
        cands.sort(key=lambda x: float(x.get("priority", 0)), reverse=True)
        return RecommendResponse(fan_id=request.fan_id, recommended=cands[:request.max_results], excluded_count=exc)
    except Exception as e:
        logger.error("[media/recommend] error: %s", traceback.format_exc())
        return RecommendResponse(fan_id=request.fan_id,
            recommended=request.available_media[:request.max_results], excluded_count=0, error=str(e)[:200])


@media_tracker_router.get("/history/{fan_id}", response_model=FanMediaHistory, summary="Historique medias d'un fan")
async def get_history(fan_id: str):
    try:
        fh = _sent_media.get(fan_id, {})
        return FanMediaHistory(fan_id=fan_id, sent_media=dict(fh), total_sent=len(fh))
    except Exception as e:
        logger.error("[media/history] error: %s", traceback.format_exc())
        return FanMediaHistory(fan_id=fan_id, sent_media={}, total_sent=0)


@media_tracker_router.post("/import", summary="Import historique depuis CRM")
async def import_history(request: ImportMediaHistoryRequest):
    try:
        fh = _sent_media[request.fan_id]
        imported = 0
        for mid, data in request.sent_media.items():
            if mid not in fh:
                fh[mid] = data
                imported += 1
            elif data.get("count", 1) > fh[mid].get("count", 1):
                fh[mid] = data
        return {"fan_id": request.fan_id, "imported": imported, "total": len(fh)}
    except Exception as e:
        logger.error("[media/import] error: %s", traceback.format_exc())
        return {"fan_id": request.fan_id, "imported": 0, "total": 0, "error": str(e)[:200]}


@media_tracker_router.delete("/history/{fan_id}", summary="Reset historique d'un fan")
async def clear_history(fan_id: str):
    try:
        count = len(_sent_media.pop(fan_id, {}))
        return {"fan_id": fan_id, "cleared": count}
    except Exception as e:
        logger.error("[media/delete] error: %s", traceback.format_exc())
        return {"fan_id": fan_id, "cleared": 0, "error": str(e)[:200]}
