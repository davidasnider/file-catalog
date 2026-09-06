import logging
from PIL import Image

logger = logging.getLogger(__name__)


def resize_image_for_vision(
    image: Image.Image, max_pixels: int, context_msg: str = "vision processing"
) -> Image.Image:
    """
    Resizes an image so that its total pixel count does not exceed max_pixels.
    Preserves aspect ratio using Lanczos resampling.
    """
    w, h = image.size
    if w * h > max_pixels:
        scale = (max_pixels / (w * h)) ** 0.5
        new_size = (max(1, int(w * scale)), max(1, int(h * scale)))
        image.thumbnail(new_size, Image.Resampling.LANCZOS)
        logger.info(
            f"Resized image for {context_msg}: {w}x{h} -> {image.size} "
            f"(Max allowed: {max_pixels} pixels)"
        )
    return image
