"""main_long.py — Modo guión largo para faceless-video-generator.

Genera un vídeo de larga duración (hasta ~1h) a partir de un guión propio en .txt.
Usa OpenRouter para todo: imágenes (flux.2-pro vía chat-completions), audio
(x-ai/grok-voice-tts-1.0) y, opcionalmente, el LLM de texto. Sin Whisper; los subtítulos se
generan directamente desde el guión.

Uso:
    python src/main_long.py --script guion.txt [--style anime] [--voice eve] [--title "Mi Vídeo"]
    python src/main_long.py --list-styles     # ver estilos disponibles
"""

import argparse
import json
import os
from functools import partial

from dotenv import load_dotenv
from openai import OpenAI

from api import openrouter_image_api, replicate_flux_api, fal_flux_api
from image_generator import generate_and_download_images
from utils import (
    build_long_storyboard,
    create_resource_dir,
    load_config,
    split_paragraphs,
)
from video_creator import create_video

# ---------------------------------------------------------------------------
# Inicialización
# ---------------------------------------------------------------------------

script_dir = os.path.dirname(os.path.abspath(__file__))
dotenv_path = os.path.join(os.path.dirname(script_dir), ".env")
load_dotenv(dotenv_path)

config = load_config()

client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    base_url=os.getenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1"),
)

# ---------------------------------------------------------------------------
# Catálogo de estilos
# ---------------------------------------------------------------------------

_styles_path = os.path.join(os.path.dirname(script_dir), "assets", "styles.json")
try:
    with open(_styles_path, encoding="utf-8") as _f:
        NAMED_STYLES: dict = json.load(_f)
except Exception:
    NAMED_STYLES = {}

GROK_TTS_VOICES = ["eve", "ara", "rex", "sal", "leo"]
IMAGE_API_MAP = {
    "openrouter": openrouter_image_api,
    "replicate": replicate_flux_api,
    "fal": fal_flux_api,
}


# ---------------------------------------------------------------------------
# Helpers interactivos
# ---------------------------------------------------------------------------

def pick_style_interactive() -> str:
    style_names = list(NAMED_STYLES.keys())
    print("\nElige un estilo de imagen:")
    for i, name in enumerate(style_names, 1):
        # Mostrar las primeras ~60 chars del prompt como vista previa
        preview = NAMED_STYLES[name][:60].rstrip()
        print(f"  {i}. {name:<12}  {preview}…")
    while True:
        try:
            choice = int(input("Número de estilo: "))
            if 1 <= choice <= len(style_names):
                return style_names[choice - 1]
            print("Opción inválida, intenta de nuevo.")
        except ValueError:
            print("Introduce un número.")


def pick_voice_interactive() -> str:
    print("\nElige una voz (grok-voice-tts):")
    for i, v in enumerate(GROK_TTS_VOICES, 1):
        print(f"  {i}. {v}")
    while True:
        try:
            choice = int(input("Número de voz: "))
            if 1 <= choice <= len(GROK_TTS_VOICES):
                return GROK_TTS_VOICES[choice - 1]
            print("Opción inválida, intenta de nuevo.")
        except ValueError:
            print("Introduce un número.")


def resolve_image_generator(image_style: str, image_api: str):
    """Devuelve (image_generator_func, effective_style_for_generator).

    Si image_style es un nombre del catálogo y image_api es openrouter,
    inyecta el prompt completo del estilo vía functools.partial (_style_prefix)
    y devuelve image_style="" para no duplicar el estilo en el prompt.
    Para replicate/fal, pasa el prompt completo como image_style directamente.
    """
    base_func = IMAGE_API_MAP.get(image_api, openrouter_image_api)
    style_prompt = NAMED_STYLES.get(image_style)

    if style_prompt:
        if image_api == "openrouter":
            # Inyectar el prompt de estilo como style_prefix; pasar style="" al generador
            return partial(base_func, _style_prefix=style_prompt), ""
        else:
            # Replicate/FAL: pasar el prompt completo como image_style (se añade al prompt)
            return base_func, style_prompt

    # Estilo libre (texto no catalogado): usar tal cual
    return base_func, image_style or "cinematic"


# ---------------------------------------------------------------------------
# Pipeline principal
# ---------------------------------------------------------------------------

def main(script_path: str, title: str = None, image_style: str = None,
         voice_name: str = None, image_api: str = "openrouter"):
    # 1. Leer guión
    with open(script_path, 'r', encoding='utf-8') as f:
        text = f.read()

    # 2. Derivar título del nombre de archivo si no se pasó
    if not title:
        title = os.path.splitext(os.path.basename(script_path))[0].replace('_', ' ').replace('-', ' ').title()

    # 3. Selección interactiva si no se pasaron opciones
    if not image_style:
        image_style = pick_style_interactive()
    if not voice_name:
        voice_name = pick_voice_interactive()

    image_generator_func, effective_style = resolve_image_generator(image_style, image_api)

    named = "(catálogo)" if image_style in NAMED_STYLES else "(libre)"
    print(f"\n▶  Título:      {title}")
    print(f"▶  Estilo:      {image_style} {named}")
    print(f"▶  Voz:         {voice_name}")
    print(f"▶  API imagen:  {image_api}")

    # 4. Trocear por párrafos → storyboard
    paragraphs = split_paragraphs(text)
    print(f"▶  Párrafos (escenas): {len(paragraphs)}")

    project = build_long_storyboard(paragraphs, title)

    # 5. Crear directorio de recursos
    story_dir = create_resource_dir(script_dir, "LongForm", title)
    audio_dir = os.path.join(story_dir, "audio")
    os.makedirs(audio_dir, exist_ok=True)

    # 6. Asignar paths de audio por escena
    for scene in project['storyboards']:
        scene['audio'] = os.path.join(audio_dir, f"scene_{scene['scene_number']}.mp3")

    # 7. Generar imágenes
    print(f"\n── Generando {len(paragraphs)} imágenes ({image_api} / {image_style}) ──")
    generate_and_download_images(project, story_dir, effective_style, image_generator_func)

    # 8. Guardar storyboard_project.json
    project_json_path = os.path.join(story_dir, "storyboard_project.json")
    with open(project_json_path, 'w', encoding='utf-8') as f:
        json.dump(project, f, ensure_ascii=False, indent=2)
    print(f"Storyboard guardado en {project_json_path}")

    # 9. Ensamblar vídeo
    video_path = os.path.join(story_dir, "story_video.mp4")
    print(f"\n── Ensamblando vídeo → {video_path} ──")
    create_video(client, project, video_path, audio_dir, voice_name, burn_srt_from_script=True)

    print(f"\n✅ ¡Vídeo completado!\n   Sin subtítulos: {video_path}")
    print(f"   Con subtítulos:  {video_path.replace('.mp4', '_subtitle.mp4')}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Genera un vídeo largo (hasta ~1h) desde un guión .txt vía OpenRouter.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("--script", default=None, help="Ruta al archivo .txt con el guión.")
    parser.add_argument("--title", default=None,
                        help="Título del vídeo (por defecto: nombre del archivo).")
    parser.add_argument("--style", default=None, dest="image_style",
                        help=(
                            f"Estilo de imagen. Estilos del catálogo: {', '.join(NAMED_STYLES)}.\n"
                            "También puedes pasar texto libre, p.ej. --style \"oil painting\".\n"
                            "Usa --list-styles para ver la descripción completa de cada estilo."
                        ))
    parser.add_argument("--voice", default=None, dest="voice_name",
                        help=f"Voz para la narración: {', '.join(GROK_TTS_VOICES)}.")
    parser.add_argument("--image-api", default="openrouter", dest="image_api",
                        choices=list(IMAGE_API_MAP.keys()),
                        help="API de generación de imágenes (default: openrouter).")
    parser.add_argument("--list-styles", action="store_true",
                        help="Muestra los estilos disponibles con su descripción completa y sale.")
    args = parser.parse_args()

    if args.list_styles:
        print("\nEstilos disponibles en assets/styles.json:\n")
        for name, prompt in NAMED_STYLES.items():
            print(f"  --style {name}")
            print(f"    {prompt[:120]}…\n")
        raise SystemExit(0)

    if not args.script:
        parser.error("Se requiere --script <ruta al .txt>")

    main(
        script_path=args.script,
        title=args.title,
        image_style=args.image_style,
        voice_name=args.voice_name,
        image_api=args.image_api,
    )
