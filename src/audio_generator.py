import os
import re
import tempfile
from typing import List

from dotenv import load_dotenv
from moviepy.editor import AudioFileClip, concatenate_audioclips
from utils import load_config

load_dotenv()

# Voces soportadas por x-ai/grok-voice-tts-1.0 via OpenRouter
TTS_VOICES = ["eve", "ara", "rex", "sal", "leo"]

# Límite de caracteres por petición de la API TTS
TTS_MAX_CHARS = 4096


def _chunk_text(text: str, max_chars: int = TTS_MAX_CHARS) -> List[str]:
    """Divide el texto en chunks <= max_chars respetando fronteras de frase."""
    if len(text) <= max_chars:
        return [text]

    sentences = re.split(r'(?<=[.!?])\s+', text)
    chunks = []
    current = ""
    for sentence in sentences:
        if len(current) + len(sentence) + 1 <= max_chars:
            current = (current + " " + sentence).strip() if current else sentence
        else:
            if current:
                chunks.append(current)
            if len(sentence) > max_chars:
                # Subdividir por comas si la frase sola es demasiado larga
                sub_parts = re.split(r'(?<=,)\s+', sentence)
                sub_chunk = ""
                for part in sub_parts:
                    if len(sub_chunk) + len(part) + 1 <= max_chars:
                        sub_chunk = (sub_chunk + " " + part).strip() if sub_chunk else part
                    else:
                        if sub_chunk:
                            chunks.append(sub_chunk)
                        sub_chunk = part
                current = sub_chunk
            else:
                current = sentence
    if current:
        chunks.append(current)
    return chunks or [text]


def generate_audio(client, text, output_file, voice_name) -> bool:
    """Genera audio narrado desde texto usando la TTS API de OpenRouter (x-ai/grok-voice-tts-1.0).

    Misma firma que la versión original para no romper create_video ni main.py.
    El texto se trocea en chunks de <=4096 chars; si hay varios se concatenan con moviepy.
    """
    config = load_config()
    lf_config = config.get('long_form', {})

    audio_model = lf_config.get('audio_model', 'x-ai/grok-voice-tts-1.0')

    # Usar la voz solicitada si es válida para este modelo, si no la de config
    voice = voice_name if voice_name in TTS_VOICES else lf_config.get('voice', 'eve')

    try:
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
    except Exception:
        pass

    chunks = _chunk_text(text, TTS_MAX_CHARS)
    tmp_files = []

    try:
        for k, chunk in enumerate(chunks):
            try:
                result = client.audio.speech.create(
                    model=audio_model,
                    voice=voice,
                    input=chunk,
                    response_format="mp3",
                )
                tmp_path = output_file.replace('.mp3', f'_part_{k}.mp3')
                with open(tmp_path, 'wb') as f:
                    f.write(result.content)
                tmp_files.append(tmp_path)
                if len(chunks) > 1:
                    print(f"  Chunk de audio {k+1}/{len(chunks)} generado.")

            except Exception as e:
                print(f"Error generando chunk {k+1} de audio: {e}")
                for p in tmp_files:
                    if os.path.exists(p):
                        os.remove(p)
                return False

        # Concatenar chunks si hay más de uno
        if len(tmp_files) == 1:
            os.rename(tmp_files[0], output_file)
        else:
            clips = [AudioFileClip(p) for p in tmp_files]
            final = concatenate_audioclips(clips)
            final.write_audiofile(output_file, logger=None)
            for clip in clips:
                clip.close()
            final.close()
            for p in tmp_files:
                if os.path.exists(p):
                    os.remove(p)

        print(f"Audio guardado en [{output_file}]")
        return True

    except Exception as e:
        print(f"Error generando audio: {e}")
        for p in tmp_files:
            if os.path.exists(p):
                os.remove(p)
        return False
