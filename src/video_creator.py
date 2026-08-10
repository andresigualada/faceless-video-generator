from moviepy.editor import (
    ImageClip,
    TextClip,
    CompositeVideoClip,
    CompositeAudioClip,
    concatenate_videoclips,
    concatenate_audioclips,
    AudioFileClip
)
from audio_generator import generate_audio
from transitions import zoom
from utils import load_config
import os
import shortcap

script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
font_path = os.path.join(project_root, "font")


def _resolve_asset(path):
    """Resolve an asset path from config to an existing file, or None.

    Relative paths are resolved against the project root so that config values
    like ``assets/music/background.mp3`` work regardless of the working
    directory. Returns None when the path is empty or the file is missing, so
    optional audio features degrade gracefully instead of crashing.
    """
    if not path:
        return None
    candidate = path if os.path.isabs(path) else os.path.join(project_root, path)
    return candidate if os.path.exists(candidate) else None


def _loop_audio(clip, duration):
    """Return an audio clip covering exactly `duration` seconds."""
    if clip.duration >= duration:
        return clip.subclip(0, duration)
    try:
        from moviepy.audio.fx.audio_loop import audio_loop
        return audio_loop(clip, duration=duration)
    except Exception:
        # Manual loop fallback if the fx helper is unavailable.
        n = int(duration // clip.duration) + 1
        return concatenate_audioclips([clip] * n).subclip(0, duration)


def _apply_audio_mix(final_clip, scene_durations, config):
    """Layer optional background music (ducked) and transition SFX under the
    narration. No-op when both features are disabled or their files are absent,
    keeping the default behaviour identical to before.
    """
    layers = [final_clip.audio]

    # Background music: looped to the video length and mixed in at a low
    # volume so it sits *under* the voice-over (simple constant ducking).
    music_cfg = config.get("background_music", {})
    music_path = _resolve_asset(music_cfg.get("path"))
    if music_cfg.get("enabled") and music_path:
        try:
            music = AudioFileClip(music_path)
            music = _loop_audio(music, final_clip.duration).volumex(
                music_cfg.get("volume", 0.12)
            )
            layers.append(music)
            print(f"Background music added: {os.path.basename(music_path)}")
        except Exception as e:
            print(f"Skipping background music: {e}")

    # Transition sound effects: a short SFX placed at the start of every scene
    # after the first (i.e. on each visual transition).
    sfx_cfg = config.get("sound_effects", {})
    sfx_path = _resolve_asset(sfx_cfg.get("transition_path"))
    if sfx_cfg.get("enabled") and sfx_path:
        try:
            volume = sfx_cfg.get("volume", 0.5)
            start = 0.0
            for idx, dur in enumerate(scene_durations):
                if idx > 0:
                    sfx = (
                        AudioFileClip(sfx_path)
                        .volumex(volume)
                        .set_start(start)
                    )
                    layers.append(sfx)
                start += dur
            print("Transition sound effects added.")
        except Exception as e:
            print(f"Skipping sound effects: {e}")

    if len(layers) > 1:
        final_clip = final_clip.set_audio(CompositeAudioClip(layers))
    return final_clip

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


def create_video(client, storyboard_project, output_file, audio_dir, voice_name):
    config = load_config()
    clips = []
    scene_durations = []
    for scene in storyboard_project['storyboards']:
        # Generate audio for the subtitle
        audio_file = scene['audio']
        generate_audio(client, scene['subtitles'], audio_file, voice_name)

        # Create audio clip
        audio_clip = AudioFileClip(audio_file)
        scene_durations.append(audio_clip.duration)

        # Create image clip with duration matching the audio
        image_clip = ImageClip(scene['image']).set_duration(audio_clip.duration)

        # Combine image, text, and audio
        video_clip = image_clip.set_audio(audio_clip)

        # Apply transition effect
        transition_type = scene.get('transition_type')

        if transition_type == 'zoom-in':
            clips.append(zoom(video_clip))
        elif transition_type == 'zoom-out':
            clips.append(zoom(video_clip, mode='out'))
        else:
            clips.append(video_clip)

    final_clip = concatenate_videoclips(clips)

    # Mix in optional background music and transition sound effects.
    final_clip = _apply_audio_mix(final_clip, scene_durations, config)

    final_clip.write_videofile(output_file, fps=24)

    add_subtitles(output_file, output_file.replace('.mp4', '_subtitle.mp4'))
