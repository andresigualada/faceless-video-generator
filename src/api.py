import requests
import replicate
import os
from typing import Optional, Dict, Any, Callable
import time
from utils import load_config
import fal_client


# Registry of the supported image-generation providers. Adding a new backend
# is a one-line change here plus the matching function below.
IMAGE_PROVIDERS: Dict[str, Callable[[str], Optional[bytes]]] = {}


def register_image_provider(name: str):
    """Decorator that registers an image-generation function under `name`."""
    def _decorator(func: Callable[[str], Optional[bytes]]):
        IMAGE_PROVIDERS[name.lower()] = func
        return func
    return _decorator


def get_image_provider(name: Optional[str] = None) -> Callable[[str], Optional[bytes]]:
    """Return the image-generation function for `name`.

    When `name` is None the value of ``image_generation.provider`` in
    config.json is used (defaulting to "replicate"). Raising a clear error for
    an unknown provider avoids silently falling back to the wrong backend.
    """
    if name is None:
        config = load_config()
        name = config.get("image_generation", {}).get("provider", "replicate")

    key = name.lower()
    if key not in IMAGE_PROVIDERS:
        available = ", ".join(sorted(IMAGE_PROVIDERS)) or "none"
        raise ValueError(
            f"Unknown image provider '{name}'. Available providers: {available}."
        )
    return IMAGE_PROVIDERS[key]


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


@register_image_provider("fal")
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


@register_image_provider("replicate")
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
                    f"Error in Flux Schnell generation "
                    f"(attempt {attempt + 1}/{max_retries}): {e}"
                )
                print("Retrying...")
                time.sleep(1)  # Wait for 1 second before retrying
            else:
                print(
                    f"Error in Flux Schnell generation after "
                    f"{max_retries} attempts: {e}"
                )
    return None

