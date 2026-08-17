# Feature: Modo "guión largo" (vídeos de ~1h) vía OpenRouter

## Estado general: ✅ Implementado — pendiente verificación end-to-end

---

## Contexto

El proyecto genera **shorts** (~14 escenas, ~1 min) con historia generada por LLM. Este modo nuevo,
paralelo y sin tocar el modo corto, permite:

1. Pasar un **guión propio en un `.txt` plano**.
2. Producir **vídeos largos (hasta ~1h)** con audio narrado y subtítulos incrustados.
3. Generar **una imagen por párrafo** del guión.
4. Usar **OpenRouter para todo** (imagen, audio, texto) con una sola API key.

Problemas del diseño actual que este modo resuelve:
- TTS `tts-1` tiene límite ~4096 chars/petición → trocear y concatenar.
- Whisper API (subtítulos) tiene límite 25 MB → se generan subtítulos **desde el guión** (sin Whisper).
- `moviepy` + cientos de clips agota RAM → render por **lotes** + `ffmpeg concat`.

---

## Fases

### ✅ Fase 0 — Config
**Archivo:** `config.json`

Añadir sección `long_form`:
```json
"long_form": {
  "image_model": "google/gemini-2.5-flash-image-preview",
  "audio_model": "gpt-audio",
  "voice": "alloy",
  "aspect_ratio": "9:16",
  "seed": 42,
  "style_prefix": "cinematic, consistent art style, coherent characters,",
  "max_chars_per_paragraph": 1500,
  "max_chars_per_audio_chunk": 1000,
  "subtitle_max_words_per_line": 8,
  "batch_size": 25
}
```

**Estado:** ✅ Completado

---

### ✅ Fase 1 — Helpers de texto y storyboard
**Archivo:** `src/utils.py`

Añadir:
- `split_paragraphs(text: str) -> List[str]`
  - `re.split(r'\n\s*\n', text)`, strip, descartar vacíos.
  - Subdividir por frases los párrafos > `max_chars_per_paragraph`.
- `build_long_storyboard(paragraphs: List[str], title: str) -> Dict`
  - Reutiliza `create_empty_storyboard(title)` (utils.py:80).
  - Por párrafo `i`: `{scene_number: i+1, description: párrafo, subtitles: párrafo,
    image: None, audio: None, transition_type: "zoom-in"/"zoom-out" alternando}`.
  - Añadir `project["characters"] = []`.
- `build_srt_from_storyboard(project: Dict, srt_path: str) -> str`
  - Adapta `convert_to_timestamped_subtitles` (utils.py:121) usando `scene['_audio_duration']`
    (duración real del audio) en lugar del `scene_duration=10` fijo.
  - Partir `subtitles` en líneas de ≤ `subtitle_max_words_per_line` palabras.
  - Repartir duración proporcional al nº de caracteres de cada línea.
  - Reutilizar `format_timedelta` (utils.py:143) y `save_timestamped_subtitles` (utils.py:150) sin cambios.

**Estado:** ✅ Completado

---

### ✅ Fase 2 — Generación de imágenes vía OpenRouter
**Archivo:** `src/api.py`

Añadir `openrouter_image_api(prompt: str, max_retries: int = 3) -> Optional[bytes]`
- Misma firma que `replicate_flux_api` → encaja como `image_generator_func` sin tocar `image_generator.py`.
- POST a `{OPENAI_BASE_URL}/chat/completions` con `Authorization: Bearer {OPENAI_API_KEY}`.
  Body: `{model: image_model, modalities:["image","text"], messages:[{role:"user", content: style_prefix + " " + prompt}], image_config:{aspect_ratio}}`.
- Extraer data URI: `resp["choices"][0]["message"]["images"][0]["image_url"]["url"]`.
- Quitar prefijo `data:image/png;base64,`, `base64.b64decode` → devolver `bytes`.
- Re-escalar con PIL a 720×1280 para normalizar resolución entre escenas.
- Reintentos con backoff (patrón `replicate_flux_api`).

**Prueba aislada:** `openrouter_image_api("a red apple")` → PNG válido.

**Estado:** ✅ Completado

---

### ✅ Fase 3 — Generación de audio vía OpenRouter gpt-audio
**Archivo:** `src/audio_generator.py`

Reescribir `generate_audio(client, text, output_file, voice_name) -> bool` (misma firma).
- Leer `audio_model` / `voice` de `config['long_form']`.
- Helper `_chunk_text(text, max_chars)` → chunks ≤ `max_chars_per_audio_chunk` por frontera de frase.
- Por chunk:
  ```python
  resp = client.chat.completions.create(
      model=audio_model,
      modalities=["text", "audio"],
      audio={"voice": voice, "format": "mp3"},
      messages=[{"role": "user", "content": chunk}])
  b64 = resp.choices[0].message.audio.data  # o resp.model_dump()
  ```
- Concatenar mp3 con `concatenate_audioclips` de moviepy → `write_audiofile(output_file)`.
- Actualizar lista de voces en `pick_voice_name()` (utils.py:168) al set de `gpt-audio`.

**Prueba aislada:** `generate_audio(client, "Hola mundo", "/tmp/t.mp3", "alloy")` → mp3 reproducible.

> ⚠️ Verificar que `gpt-audio` está disponible en la cuenta OpenRouter antes de escalar.

**Estado:** ✅ Completado

---

### ✅ Fase 4 — Subtítulos desde guión + batching de memoria
**Archivo:** `src/video_creator.py`

Cambios:
1. `create_video(...)` → añadir parámetro `burn_srt_from_script: bool = False`.
   - En el bucle, tras `audio_clip = AudioFileClip(audio_file)`, guardar `scene['_audio_duration'] = audio_clip.duration`.
   - Cuando `True`: en lugar de `add_subtitles`/shortcap, llamar a `build_srt_from_storyboard` + `burn_srt`.
   - `add_subtitles`/shortcap quedan **intactas** para el modo corto.

2. `burn_srt(video_in: str, srt_path: str, video_out: str)` (nueva):
   - Quemar con **ffmpeg** vía `subprocess`:
     `ffmpeg -i video_in -vf subtitles=srt_path:force_style='FontSize=24,PrimaryColour=&HFFFFFF,OutlineColour=&H000000,Outline=2' -c:a copy video_out`

3. **Batching para 1h** (parámetro `batch_size` de config):
   - Procesar escenas en lotes de `batch_size` → mp4 parcial por lote con `write_videofile(logger=None)`.
   - Cerrar clips (`clip.close()`, `audio_clip.close()`) tras cada lote.
   - Unir parciales con `ffmpeg -f concat -safe 0 -i list.txt -c copy final.mp4` (sin re-encode).
   - Quemar SRT sobre el vídeo final concatenado.
   - `batch_size: 0` = sin batching (comportamiento del modo corto).

**Estado:** ✅ Completado

---

### ✅ Fase 5 — Orquestación y CLI
**Archivo:** `src/main_long.py` (CREAR)

Punto de entrada del modo largo. Flujo:
1. `argparse`: `--script guion.txt [--style cinematic] [--voice alloy] [--title "..."]`.
2. Leer `.txt` UTF-8; derivar `title` del nombre de archivo si no se pasa.
3. `paragraphs = split_paragraphs(text)`.
4. `story_dir = create_resource_dir(script_dir, "LongForm", title)` + crear `audio_dir`.
5. `project = build_long_storyboard(paragraphs, title)`.
6. `generate_and_download_images(project, story_dir, image_style, openrouter_image_api)` (reutiliza).
7. Asignar `scene['audio'] = audio_dir/scene_{n}.mp3` (replica main.py:117).
8. Guardar `storyboard_project.json`.
9. `create_video(client, project, video_path, audio_dir, voice_name, burn_srt_from_script=True)`.

Crear cliente OpenAI con `base_url` + `api_key` de `.env` (patrón main.py:33-38).

**Estado:** ✅ Completado

---

## Verificación end-to-end

1. **Smoke tests por componente** (fases 2 y 3):
   - `openrouter_image_api("a red apple")` → PNG guardado y abierto.
   - `generate_audio(client, "Hola mundo", "/tmp/t.mp3", "alloy")` → mp3 reproducible.

2. **Mini-guión** (3 párrafos):
   ```
   python src/main_long.py --script mini.txt --style cinematic
   ```
   Verificar: 3 PNG en `story_dir`, 3 mp3 en `audio/`, `storyboard_project.json` con `_audio_duration`,
   `story_video.mp4` + `.srt` + `_subtitle.mp4`. Comprobar sincronía subtítulos/voz, transiciones zoom alternando.

3. **Escala** (~40-60 párrafos): validar batching/memoria y tiempo de render.

4. **Consistencia visual**: seed + `style_prefix` fijos → imágenes comparten estilo.

---

## Archivos críticos

| Archivo | Acción |
|---|---|
| `config.json` | Añadir sección `long_form` |
| `src/utils.py` | Añadir `split_paragraphs`, `build_long_storyboard`, `build_srt_from_storyboard` |
| `src/api.py` | Añadir `openrouter_image_api` |
| `src/audio_generator.py` | Reescribir `generate_audio` para gpt-audio + chunking |
| `src/video_creator.py` | Añadir `burn_srt`, batching, flag `burn_srt_from_script` |
| `src/main_long.py` | CREAR — orquestación + CLI |
| `requirements.txt` | Sin cambios (todas las deps ya están) |
