"""
Fashion image and text embedding service.

Supports:
- FashionCLIP via open_clip (real provider)
- Deterministic normalized hash vectors (mock/CI provider per PLAN.md)
Dimension: 512.
"""

import hashlib
import math

from app.config import get_settings
from app.core.logging import get_logger

logger = get_logger("vision.embeddings")

VECTOR_DIM = 512


def _generate_mock_embedding(seed_str: str) -> list[float]:
    """
    Generate a deterministic, unit-normalized 512-dimensional vector
    based on the hash of the input string/bytes.
    """
    raw_hash = hashlib.sha512(seed_str.encode("utf-8")).digest()
    vec = []
    for i in range(VECTOR_DIM):
        # Derive float pseudo-randomly from hash segments
        idx = (i * 2) % len(raw_hash)
        val = (raw_hash[idx] - 128) / 128.0
        vec.append(val)

    # Unit normalize
    norm = math.sqrt(sum(v * v for v in vec))
    if norm > 0:
        vec = [v / norm for v in vec]
    return vec


class EmbeddingService:
    """Embedding extraction service supporting mock and FashionCLIP providers."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.provider = self.settings.embedding_provider
        self._clip_model = None
        self._clip_preprocess = None
        self._clip_tokenizer = None

    def _init_clip(self) -> None:
        if self._clip_model is None and self.provider == "fashionclip":
            try:
                import open_clip
                model, _, preprocess = open_clip.create_model_and_transforms(
                    "ViT-B-32", pretrained="laion2b_s34b_b79k"
                )
                self._clip_model = model
                self._clip_preprocess = preprocess
                self._clip_tokenizer = open_clip.get_tokenizer("ViT-B-32")
                logger.info("Initialized FashionCLIP embedding model")
            except Exception as e:
                logger.warning(f"Could not load open_clip ({e}); falling back to mock embeddings")
                self.provider = "mock"

    def embed_image(self, image_bytes: bytes) -> list[float]:
        """Generate 512-dim embedding from image bytes."""
        if self.provider == "fashionclip":
            self._init_clip()
            if self._clip_model is not None:
                import io

                import torch
                from PIL import Image

                with Image.open(io.BytesIO(image_bytes)) as img:
                    tensor = self._clip_preprocess(img).unsqueeze(0)
                    with torch.no_grad():
                        features = self._clip_model.encode_image(tensor)
                        features /= features.norm(dim=-1, keepdim=True)
                        return features[0].tolist()

        # Fallback to mock deterministic vector
        h = hashlib.sha256(image_bytes).hexdigest()
        return _generate_mock_embedding(f"img_{h}")

    def embed_text(self, text: str) -> list[float]:
        """Generate 512-dim embedding from text description."""
        if self.provider == "fashionclip":
            self._init_clip()
            if self._clip_model is not None:
                import torch
                tokens = self._clip_tokenizer([text])
                with torch.no_grad():
                    features = self._clip_model.encode_text(tokens)
                    features /= features.norm(dim=-1, keepdim=True)
                    return features[0].tolist()

        return _generate_mock_embedding(f"txt_{text.strip().lower()}")


_embedding_service = None


def get_embedding_service() -> EmbeddingService:
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
    return _embedding_service
