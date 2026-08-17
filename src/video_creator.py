import os
import subprocess
import tempfile

from moviepy.editor import (
    ImageClip,
    TextClip,
    CompositeVideoClip,
    concatenate_videoclips,
    AudioFileClip
)
from audio_generator import generate_audio
from transitions import zoom
import shortcap

script_dir = os.path.dirname(os.path.abspath(__file__))
font_path = os.path.join(os.path.dirname(script_dir), "font")


# ---------------------------------------------------------------------------
# Modo corto (original): subtítulos con shortcap/Whisper
# ---------------------------------------------------------------------------

def add_subtitles(output_file, output_file_subtitle):
    shortcap.add_captions(
        video_file=output_file,
        output_file=output_file_subtitle,

        font=os.path.join(font_path, "TitanOne.ttf"),
        font_size=70,
        font_color="white",
        stroke_width=3,
        stroke_color="black",
        shadow_strength=1.0,
        shadow_blur=0.1,
        highlight_current_word=True,
        word_highlight_color="yellow",
        line_count=1,
        padding=70,
        position="center",
        use_local_whisper=False,
    )


# ---------------------------------------------------------------------------
# Modo largo: subtítulos desde el guión quemados con ffmpeg
# ---------------------------------------------------------------------------

def burn_srt(video_in: str, srt_path: str, video_out: str) -> None:
    """Quema un archivo SRT sobre el vídeo usando ffmpeg.

    Usa imageio-ffmpeg para localizar el binario de ffmpeg si no está en el PATH.
    """
    try:
        import imageio_ffmpeg
        ffmpeg_bin = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        ffmpeg_bin = "ffmpeg"

    # force_style de subtitles: fuente grande, blanca con contorno negro
    style = (
        "FontName=Arial,FontSize=22,PrimaryColour=&H00FFFFFF,"
        "OutlineColour=&H00000000,BackColour=&H80000000,"
        "Bold=1,Outline=2,Shadow=1,Alignment=2,MarginV=30"
    )

    cmd = [
        ffmpeg_bin, "-y",
        "-i", video_in,
        "-vf", f"subtitles={srt_path}:force_style='{style}'",
        "-c:a", "copy",
        video_out,
    ]
    print(f"Quemando subtítulos: {srt_path} → {video_out}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg subtitles falló:\n{result.stderr}")


def _build_scene_clip(scene: dict) -> object:
    """Construye el clip de vídeo (imagen + audio + zoom) para una escena."""
    audio_clip = AudioFileClip(scene['audio'])
    scene['_audio_duration'] = audio_clip.duration  # guardado para SRT

    image_clip = ImageClip(scene['image']).set_duration(audio_clip.duration)
    video_clip = image_clip.set_audio(audio_clip)

    transition_type = scene.get('transition_type', 'zoom-in')
    if transition_type == 'zoom-in':
        return zoom(video_clip)
    elif transition_type == 'zoom-out':
        return zoom(video_clip, mode='out')
    return video_clip


def _concat_with_ffmpeg(partial_files: list, output_file: str) -> None:
    """Une una lista de mp4 parciales con ffmpeg concat (sin re-encode)."""
    try:
        import imageio_ffmpeg
        ffmpeg_bin = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        ffmpeg_bin = "ffmpeg"

    list_path = output_file.replace('.mp4', '_concat_list.txt')
    with open(list_path, 'w', encoding='utf-8') as f:
        for p in partial_files:
            f.write(f"file '{os.path.abspath(p)}'\n")

    cmd = [
        ffmpeg_bin, "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", list_path,
        "-c", "copy",
        output_file,
    ]
    print(f"Concatenando {len(partial_files)} parciales → {output_file}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    os.remove(list_path)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg concat falló:\n{result.stderr}")


# ---------------------------------------------------------------------------
# Punto de entrada principal
# ---------------------------------------------------------------------------

def create_video(
    client,
    storyboard_project: dict,
    output_file: str,
    audio_dir: str,
    voice_name: str,
    burn_srt_from_script: bool = False,
) -> None:
    """Ensambla el vídeo final.

    burn_srt_from_script=False  → modo corto original (shortcap/Whisper).
    burn_srt_from_script=True   → modo largo: subtítulos desde el guión, batching por lotes.
    """
    from utils import load_config, build_srt_from_storyboard

    if not burn_srt_from_script:
        # ── Modo corto: comportamiento original ────────────────────────────
        clips = []
        for scene in storyboard_project['storyboards']:
            audio_file = scene['audio']
            generate_audio(client, scene['subtitles'], audio_file, voice_name)
            clips.append(_build_scene_clip(scene))

        final_clip = concatenate_videoclips(clips)
        final_clip.write_videofile(output_file, fps=24)
        add_subtitles(output_file, output_file.replace('.mp4', '_subtitle.mp4'))
        return

    # ── Modo largo: batching + subtítulos desde guión ─────────────────────
    config = load_config()
    batch_size = config['long_form'].get('batch_size', 25) or 25

    scenes = storyboard_project['storyboards']
    batches = [scenes[i:i + batch_size] for i in range(0, len(scenes), batch_size)]
    partial_files = []
    base, _ = os.path.splitext(output_file)

    for b_idx, batch in enumerate(batches):
        partial_path = f"{base}_part_{b_idx:03d}.mp4"
        print(f"\n── Lote {b_idx + 1}/{len(batches)} ({len(batch)} escenas) ──")

        clips = []
        for scene in batch:
            audio_file = scene['audio']
            generate_audio(client, scene['subtitles'], audio_file, voice_name)
            clips.append(_build_scene_clip(scene))

        batch_clip = concatenate_videoclips(clips)
        batch_clip.write_videofile(partial_path, fps=24, logger=None)

        # Liberar memoria
        for c in clips:
            try:
                c.close()
            except Exception:
                pass
        try:
            batch_clip.close()
        except Exception:
            pass

        partial_files.append(partial_path)

    # Unir parciales
    if len(partial_files) == 1:
        os.rename(partial_files[0], output_file)
    else:
        _concat_with_ffmpeg(partial_files, output_file)
        for p in partial_files:
            if os.path.exists(p):
                os.remove(p)

    # Generar y quemar SRT desde el guión
    srt_path = output_file.replace('.mp4', '.srt')
    subtitle_path = output_file.replace('.mp4', '_subtitle.mp4')
    build_srt_from_storyboard(storyboard_project, srt_path)
    burn_srt(output_file, srt_path, subtitle_path)
    print(f"\nVídeo con subtítulos: {subtitle_path}")
