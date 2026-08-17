import base64
import io
import requests
import replicate
import os
from typing import Optional, Dict, Any
import time
from utils import load_config
import fal_client
from PIL import Image


def submit_fal_request(prompt: str, config: dict) -> Optional[str]:
    try:
        handler = fal_client.submit(
            config["model"],
            arguments={
                "prompt": prompt,
                "image_size": config["image_size"],
                "num_images": config["num_images"],
                "num_inference_steps": config["num_inference_steps"],
                "enable_safety_checker": config["enable_safety_checker"],
            },
        )

        result = handler.get()
        if result and isinstance(result, dict) and "images" in result:
            images = result["images"]
            if isinstance(images, list) and images:
                return images[0].get("url")

        return None
    except Exception as e:
        print(f"Error in FAL AI API request: {e}")
        return None


def fal_flux_api(prompt: str, max_retries: int = 3) -> Optional[bytes]:
    config = load_config()
    fal_config = config["fal_flux_api"]

    for attempt in range(max_retries):
        try:
            image_url = submit_fal_request(prompt, fal_config)
            if image_url:
                response = requests.get(image_url)
                response.raise_for_status()
                return response.content
            else:
                raise ValueError("No image URL returned from FAL AI API")
        except Exception as e:
            if attempt < max_retries - 1:
                print(
                    f"Error in FAL AI API request (attempt {attempt + 1}/{max_retries}): {e}"
                )
                print("Retrying...")
                time.sleep(1)  # Wait for 1 second before retrying
            else:
                print(f"Error in FAL AI API request after {max_retries} attempts: {e}")
    return None


# Dimensiones canónicas por aspect ratio (ancho x alto)
ASPECT_RATIO_SIZES = {
    "16:9": (1280, 720),
    "9:16": (720, 1280),
    "1:1":  (1024, 1024),
    "4:3":  (1024, 768),
    "3:4":  (768, 1024),
}


def _crop_to_fill(img: "Image.Image", target_w: int, target_h: int) -> "Image.Image":
    """Recorta la imagen al ratio exacto sin distorsión (cover mode).

    Escala para que el lado más pequeño cubra el target, luego recorta el centro.
    """
    src_w, src_h = img.size
    scale = max(target_w / src_w, target_h / src_h)
    new_w = int(src_w * scale)
    new_h = int(src_h * scale)
    img = img.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - target_w) // 2
    top  = (new_h - target_h) // 2
    return img.crop((left, top, left + target_w, top + target_h))


def openrouter_image_api(prompt: str, max_retries: int = 3, _style_prefix: str = None) -> Optional[bytes]:
    """Genera una imagen vía OpenRouter chat/completions con modalities:["image"].

    Misma firma que replicate_flux_api / fal_flux_api para encajar como
    image_generator_func en generate_and_download_images sin tocar image_generator.py.
    El aspect ratio y la resolución se leen de config['long_form']['aspect_ratio'].
    _style_prefix: si se pasa (vía functools.partial), reemplaza config.style_prefix.
    """
    config = load_config()
    lf_config = config["long_form"]

    base_url = os.getenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")
    api_key = os.getenv("OPENAI_API_KEY", "")

    aspect_ratio = lf_config.get("aspect_ratio", "16:9")
    target_w, target_h = ASPECT_RATIO_SIZES.get(aspect_ratio, (1280, 720))

    # Usar style_prefix inyectado (named style) o el del config
    style_prefix = _style_prefix if _style_prefix is not None else lf_config.get("style_prefix", "")

    # Añadir hint de ratio al prompt para orientar al modelo
    ratio_hint = f"{aspect_ratio} aspect ratio, {'landscape' if target_w > target_h else 'portrait'}"
    full_prompt = f"{style_prefix} {prompt}, {ratio_hint}".strip()

    payload = {
        "model": lf_config["image_model"],
        "messages": [{"role": "user", "content": full_prompt}],
        "modalities": ["image"],
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    for attempt in range(max_retries):
        try:
            resp = requests.post(
                f"{base_url.rstrip('/')}/chat/completions",
                json=payload,
                headers=headers,
                timeout=120,
            )
            resp.raise_for_status()
            data = resp.json()

            message = data["choices"][0]["message"]
            images = message.get("images")
            if not images:
                raise ValueError(f"No se encontró 'images' en la respuesta. Keys: {list(message.keys())}")

            data_url = images[0]["image_url"]["url"]
            if ";base64," in data_url:
                raw_bytes = base64.b64decode(data_url.split(";base64,", 1)[1])
            else:
                img_resp = requests.get(data_url, timeout=60)
                img_resp.raise_for_status()
                raw_bytes = img_resp.content

            # Normalizar a la resolución objetivo sin distorsionar (cover + crop centrado)
            img = Image.open(io.BytesIO(raw_bytes)).convert("RGB")
            if img.size != (target_w, target_h):
                img = _crop_to_fill(img, target_w, target_h)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue()

        except Exception as e:
            if attempt < max_retries - 1:
                print(f"Error en OpenRouter image API (intento {attempt + 1}/{max_retries}): {e}")
                print("Reintentando en 2s...")
                time.sleep(2)
            else:
                print(f"Error en OpenRouter image API tras {max_retries} intentos: {e}")
    return None


def replicate_flux_api(prompt: str, max_retries: int = 3) -> Optional[bytes]:
    config = load_config()
    replicate_config = config["replicate_flux_api"]

    payload = {
        "prompt": prompt,
        "aspect_ratio": replicate_config["aspect_ratio"],
        "num_inference_steps": replicate_config["num_inference_steps"],
        "disable_safety_checker": replicate_config["disable_safety_checker"],
        "guidance": replicate_config["guidance"],
        "output_quality": replicate_config["output_quality"],
    }

    for attempt in range(max_retries):
        try:
            image_urls = replicate.run(
                config["replicate_flux_api"]["model"], input=payload
            )
            if image_urls and isinstance(image_urls, list) and len(image_urls) > 0:
                image_url = image_urls[0]
                response = requests.get(image_url)
                response.raise_for_status()
                return response.content
            else:
                raise ValueError("No image URL returned from Replicate API")
        except Exception as e:
            if attempt < max_retries - 1:
                print(
                    f"Error in Flux Schnell generation (attempt {
                        attempt + 1}/{max_retries}): {e}"
                )
                print("Retrying...")
                time.sleep(1)  # Wait for 1 second before retrying
            else:
                print(
                    f"Error in Flux Schnell generation after {
                        max_retries} attempts: {e}"
                )
    return None

