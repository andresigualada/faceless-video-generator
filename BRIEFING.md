# Briefing: Storytime Video Generator

## Visión general

Herramienta en Python para generar **storytimes en formato vídeo largo (1–1.5h)** a partir de un guión completo, usando IA para narración, generación de imágenes y efectos visuales. Orientado a contenido de YouTube con soporte para formatos cortos (Shorts/Reels).

Todo el acceso a modelos de IA (LLM, imágenes, TTS) se centraliza a través de **LiteLLM** para abstraer el proveedor (OpenRouter por defecto) y poder cambiar de modelo o proveedor sin modificar el código.

---

## Flujo principal

```
Prompt / Guión externo
        │
        ▼
[1] Script de guión        → guion_original.txt + guion_anotado.txt
        │
        ▼
[2] Script de storytime    → imágenes por capítulo + narración TTS → storytime_16x9.mp4
        │
        ├──▶ [3] Script de short    → storytime_16x9.mp4→ short_9x16.mp4
        │
        └──▶ [4] Script de upload   → YouTube (con capítulos, thumbnail, metadatos)
```

---

## Módulos

### Módulo 1 — Generación de guión (`scripts/generate_script.py`)

**Entrada:**
- `--prompt "tema o idea"` → genera el guión de cero con un LLM
- `--source guion_en.txt --lang es` → traduce/adapta un guión existente en otro idioma

**Salida — dos archivos:**

| Archivo | Contenido |
|---|---|
| `guion_original.txt` | Texto limpio, dividido en capítulos (`## Capítulo N — Título`) |
| `guion_anotado.txt` | Misma estructura + anotaciones TTS para pausas, énfasis y dramatización |

**Anotaciones TTS en `guion_anotado.txt`:**

Marcado compatible con SSML o con el formato del modelo TTS elegido. Ejemplos orientativos:

```
[pausa_corta]      → 0.5s de silencio
[pausa_larga]      → 1.5s de silencio
[enfasis]texto[/enfasis]   → mayor énfasis en la palabra
[lento]texto[/lento]       → ritmo más pausado
[dramatico]texto[/dramatico] → tono más grave/intenso
## Capítulo 3 — El descubrimiento [duracion_objetivo: 8min]
```

**Parámetros adicionales:**
- `--chapters N` → número de capítulos objetivo
- `--duration 60` → duración total objetivo en minutos (el LLM ajusta la densidad del guión)
- `--tone neutral|dramatic|educational` → tono general de la narración
- `--model <litellm_model_id>` → modelo LLM a usar (default: config)
- `--lang es|en|...` → idioma de salida

---

### Módulo 2 — Generación de storytime 16:9 (`scripts/generate_storytime.py`)

Genera el vídeo largo a partir del `guion_anotado.txt`.

**Estructura del vídeo:**
- Una imagen por capítulo (generada con IA, siguiendo la temática del capítulo)
- La imagen se "mueve" durante toda la narración del capítulo mediante efectos visuales
- Narración TTS del capítulo completo como audio
- Subtítulos incrustados generados desde el propio guión (sin Whisper)

**Efectos visuales por capítulo (Ken Burns y otros):**

| Efecto | Descripción |
|---|---|
| `ken_burns_in` | Zoom lento hacia adentro (acercamiento gradual) |
| `ken_burns_out` | Zoom lento hacia afuera |
| `pan_left` / `pan_right` | Desplazamiento horizontal lento |
| `pan_up` / `pan_down` | Desplazamiento vertical lento |
| `fade_in` / `fade_out` | Aparición/desaparición desde negro |
| `static` | Sin movimiento (imagen fija) |

El efecto puede asignarse automáticamente (rotación predefinida) o anotarse en el guión (`[efecto: ken_burns_in]`).

**Generación de imágenes:**
- Una imagen por capítulo vía LiteLLM → OpenRouter (modelo configurable, p.ej. `black-forest-labs/flux.2-pro`)
- El prompt de imagen se deriva automáticamente del texto del capítulo (resumido por LLM) más el estilo visual global
- Estilos predefinidos en `assets/styles.json` (anime, realistic, cinematic, etc.) seleccionables con `--style`
- Resolución: 1920×1080 (16:9)

**Parámetros:**
- `--script guion_anotado.txt`
- `--style anime|realistic|cinematic|...`
- `--voice <voice_id>` → voz del modelo TTS
- `--tts-model <litellm_model_id>` → modelo TTS
- `--image-model <litellm_model_id>` → modelo de imagen
- `--output storytime.mp4`
- `--subtitles` → incrustar subtítulos (flag, default: on)
- `--subtitle-style "FontSize=24,..."` → estilo ASS/SRT para ffmpeg

**Salida:**
- `storytime_16x9.mp4` → vídeo completo sin subtítulos
- `storytime_16x9_sub.mp4` → vídeo completo con subtítulos incrustados (ffmpeg)
- `storytime_16x9.srt` → archivo de subtítulos separado
- `storyboard.json` → estado completo del proyecto (reanudable)
- `chapters.txt` → timestamps de capítulos (para YouTube)

---

### Módulo 3 — Generación de Short 9:16 (`scripts/generate_short.py`)

Genera un vídeo corto a partir de un storytime ya creado o directamente desde el guión.

**Lógica:**
- Toma la imagen del capítulo 1 (u otro especificado) del `storyboard.json`
- Recorta y reencuadra a 9:16 (1080×1920) con recorte centrado
- Toma los primeros ~30s de narración del capítulo (configurable)
- Aplica **fade in** al inicio y **fade out** al final del audio y del vídeo
- Incrusta texto en pantalla: título del vídeo o gancho (configurable)
- Subtítulos incrustados del fragmento

**Parámetros:**
- `--storyboard storyboard.json` → lee imágenes/audio ya generados
- `--chapter 1` → capítulo del que tomar la imagen y audio (default: 1)
- `--duration 30` → duración en segundos (default: 30)
- `--hook "¿Sabías que...?"` → texto del gancho superpuesto
- `--output short.mp4`
- `--fade 1.5` → duración en segundos del fade in/out

---

### Módulo 4 — Upload a YouTube (`scripts/upload_youtube.py`)

**Funcionalidades:**
- Subida del vídeo con metadatos completos: título, descripción, tags, categoría, privacidad
- Inserción automática de **capítulos** en la descripción usando los timestamps de `chapters.txt`
- Subida del thumbnail generado (imagen del capítulo 1 o thumbnail específico)
- Programación de publicación (`--publish-at "2026-06-15 18:00"`)

**Parámetros:**
- `--video storytime_16x9_sub.mp4`
- `--title "Título del vídeo"`
- `--description descripcion.txt`
- `--chapters chapters.txt`
- `--thumbnail thumbnail.jpg`
- `--tags "tag1,tag2,tag3"`
- `--privacy public|unlisted|private`
- `--publish-at "YYYY-MM-DD HH:MM"`

---

### Módulo 5 — Generación de Thumbnail (`scripts/generate_thumbnail.py`)

Genera una imagen de thumbnail con gancho visual a partir del guión.

**Lógica:**
- Genera una imagen IA con el prompt visual del capítulo más impactante del guión
- Superpone texto del gancho en la imagen (configurable: posición, fuente, color, sombra)
- Exporta en 1280×720 (ratio YouTube)

**Parámetros:**
- `--script guion_original.txt` → el LLM elige el momento más impactante
- `--hook "texto del gancho"` → texto superpuesto (opcional; si no se pasa, el LLM lo sugiere)
- `--style <estilo>` → mismo sistema de estilos que el storytime
- `--output thumbnail.jpg`

---

## Pautas técnicas

### Stack

| Capa | Tecnología |
|---|---|
| Lenguaje | Python 3.11+ |
| Acceso a modelos IA | **LiteLLM** (abstracción sobre OpenRouter y otros proveedores) |
| Composición de vídeo | **moviepy** (clips, efectos) + **ffmpeg** (concat, subtítulos, re-encode) |
| Efectos visuales | **OpenCV (cv2)** — transformaciones affine para Ken Burns/pans |
| Imagen | LiteLLM → OpenRouter → `black-forest-labs/flux.2-pro` (u otro) |
| TTS | LiteLLM → OpenRouter → `x-ai/grok-voice-tts-1.0` (u otro) |
| LLM (guiones) | LiteLLM → OpenRouter → `google/gemini-2.5-flash` (u otro) |
| Subtítulos | SRT generado desde el guión + quemado con ffmpeg `subtitles` filter |
| YouTube | `google-api-python-client` (YouTube Data API v3) |
| Config | `config.json` + `.env` para API keys |
| CLI | `argparse` en cada script |

### LiteLLM como capa de abstracción

Todos los accesos a IA pasan por LiteLLM:

```python
# LLM (guiones, prompts de imagen)
from litellm import completion
response = completion(model="openrouter/google/gemini-2.5-flash", messages=[...])

# TTS
from litellm import speech
audio = speech(model="openrouter/x-ai/grok-voice-tts-1.0", input=text, voice="eve")

# Imagen (vía completion con modalities)
response = completion(model="openrouter/black-forest-labs/flux.2-pro",
                      messages=[...], modalities=["image"])
```

Cambiar de proveedor = cambiar el prefijo del modelo en `config.json`. Sin tocar código.

### Estructura de carpetas

```
storytime-generator/
├── scripts/
│   ├── generate_script.py
│   ├── generate_storytime.py
│   ├── generate_short.py
│   ├── generate_thumbnail.py
│   └── upload_youtube.py
├── src/
│   ├── script_generator.py   # lógica LLM para guiones
│   ├── image_generator.py    # generación de imágenes vía LiteLLM
│   ├── audio_generator.py    # TTS vía LiteLLM
│   ├── video_composer.py     # moviepy: Ken Burns, fades, pans, ensamblado
│   ├── subtitle_builder.py   # SRT desde guión + quemado ffmpeg
│   ├── thumbnail_builder.py  # generación de thumbnail
│   └── utils.py              # config, chunking, helpers
├── assets/
│   └── styles.json           # catálogo de estilos visuales
├── data/                     # salidas generadas (gitignored)
├── config.json
├── .env
└── requirements.txt
```

### `config.json` (estructura orientativa)

```json
{
  "models": {
    "llm":   "openrouter/google/gemini-2.5-flash",
    "image": "openrouter/black-forest-labs/flux.2-pro",
    "tts":   "openrouter/x-ai/grok-voice-tts-1.0"
  },
  "tts": {
    "voice": "eve",
    "max_chars_per_chunk": 4000
  },
  "video": {
    "aspect_ratio_long": "16:9",
    "aspect_ratio_short": "9:16",
    "resolution_long":  [1920, 1080],
    "resolution_short": [1080, 1920],
    "fps": 24,
    "effect_duration_min": 5,
    "default_effect": "ken_burns_in",
    "subtitle_style": "FontName=Arial,FontSize=28,Bold=1,PrimaryColour=&H00FFFFFF,Outline=2"
  },
  "script": {
    "default_chapters": 10,
    "default_duration_min": 60,
    "default_tone": "dramatic"
  }
}
```

---

## Consideraciones de escalado

- **Reanudabilidad**: el `storyboard.json` persiste el estado completo entre etapas. Si el proceso falla (p.ej. en el capítulo 7 de 20), se puede reanudar desde ese punto sin regenerar lo anterior.
- **Vídeos de 1–1.5h**: el ensamblado por lotes (batch de N capítulos → mp4 parcial) más `ffmpeg concat` sin re-encode evita agotar RAM con moviepy.
- **Costes**: para guiones de 1h, la mayor parte del coste es TTS (>20.000 palabras). LiteLLM permite auditar el uso por proveedor.
- **Extensibilidad**: añadir un nuevo proveedor (ElevenLabs para TTS, Midjourney para imágenes) = añadir el prefijo LiteLLM correspondiente en `config.json`.
