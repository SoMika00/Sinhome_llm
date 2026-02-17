from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field


d_router = APIRouter(prefix="/encode")


class EncodeRequest(BaseModel):
    message: Optional[str] = None
    messages: List[str] = Field(default_factory=list)
    normalize: bool = True
    batch_size: int = 16


class Vector16Request(BaseModel):
    message: str


def _coerce_texts(req: EncodeRequest) -> List[str]:
    if req.message is not None:
        return [str(req.message)]
    if req.messages:
        return [str(x) for x in req.messages]
    raise HTTPException(status_code=422, detail="encode: fournir 'message' ou 'messages'.")


_MODELS: Dict[str, Any] = {}

_DEFAULT_TORCH_THREADS = 10


def _get_model(model_id: str):
    model = _MODELS.get(model_id)
    if model is not None:
        return model

    try:
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer(model_id, trust_remote_code=True, device="cpu")
        try:
            model.eval()
        except Exception:
            pass
        _MODELS[model_id] = model
        return model
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Impossible de charger le modèle '{model_id}': {e}")


def _apply_threads(threads: int) -> None:
    try:
        import torch

        torch.set_num_threads(int(threads))
    except Exception:
        return


async def _encode(model_id: str, req: EncodeRequest) -> Dict[str, Any]:
    texts = _coerce_texts(req)
    _apply_threads(_DEFAULT_TORCH_THREADS)

    model = _get_model(model_id)

    kwargs: Dict[str, Any] = {
        "batch_size": max(1, int(req.batch_size or 1)),
        "normalize_embeddings": bool(req.normalize),
        "convert_to_numpy": True,
        "show_progress_bar": False,
    }

    try:
        emb = model.encode(texts, **kwargs)
        out = {"model": model_id, "embeddings": emb.tolist()}
        try:
            out["dim"] = int(emb.shape[-1])
        except Exception:
            pass
        return out
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur encodage ({model_id}): {e}")


@d_router.post("/bge-m3")
async def encode_bge_m3(req: EncodeRequest):
    return await _encode("BAAI/bge-m3", req)


@d_router.post("/bge-m3/vector")
async def vector_bge_m3(req: Vector16Request):
    fixed_req = EncodeRequest(
        message=req.message,
        normalize=True,
        batch_size=16,
    )
    out = await _encode("BAAI/bge-m3", fixed_req)
    try:
        vec = out["embeddings"][0]
    except Exception:
        raise HTTPException(status_code=500, detail="Encodage: format embeddings inattendu")
    return {"vector": vec}


@d_router.post("/jina-code")
async def encode_jina_code(req: EncodeRequest):
    return await _encode("jinaai/jina-embeddings-v2-base-code", req)


@d_router.post("/jina-code/vector")
async def vector_jina_code(req: Vector16Request):
    fixed_req = EncodeRequest(
        message=req.message,
        normalize=True,
        batch_size=16,
    )
    out = await _encode("jinaai/jina-embeddings-v2-base-code", fixed_req)
    try:
        vec = out["embeddings"][0]
    except Exception:
        raise HTTPException(status_code=500, detail="Encodage: format embeddings inattendu")
    return {"vector": vec}


@d_router.post("/e5-small")
async def encode_e5_small(req: EncodeRequest):
    return await _encode("intfloat/multilingual-e5-small", req)


@d_router.post("/e5-small/vector")
async def vector_e5_small(req: Vector16Request):
    fixed_req = EncodeRequest(
        message=req.message,
        normalize=True,
        batch_size=16,
    )
    out = await _encode("intfloat/multilingual-e5-small", fixed_req)
    try:
        vec = out["embeddings"][0]
    except Exception:
        raise HTTPException(status_code=500, detail="Encodage: format embeddings inattendu")
    return {"vector": vec}


@d_router.post("/e5-small/vector16")
async def vector16_e5_small(req: Vector16Request):
    fixed_req = EncodeRequest(
        message=req.message,
        normalize=True,
        batch_size=16,
    )
    out = await _encode("intfloat/multilingual-e5-small", fixed_req)
    try:
        vec = out["embeddings"][0]
    except Exception:
        raise HTTPException(status_code=500, detail="Encodage: format embeddings inattendu")
    return {"vector": vec[:16]}
