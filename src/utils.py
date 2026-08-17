import os
import re
import json
from datetime import datetime
import datetime
from typing import List, Dict
from PIL import Image


STORY_TYPES = [
    "Scary",
    "Mystery",
    "Bedtime",
    "Interesting History",
    "Urban Legends",
    "Motivational",
    "Fun Facts",
    "Long Form Jokes",
    "Life Pro Tips",
    "Philosophy",
    "Love",
]

STORY_TYPE_HASHTAGS = {
    "Scary": "#scary",
    "Mystery": "#mystery",
    "Bedtime": "#bedtime",
    "Interesting History": "#history",
    "Urban Legends": "#urbanlegends",
    "Motivational": "#motivation",
    "Fun Facts": "#funfacts",
    "Long Form Jokes": "#joke",
    "Life Pro Tips": "#lifeprotips",
    "Philosophy": "#philosophy",
    "Love": "#love",
}

def create_resource_dir(script_dir, story_type, title):
    # Remove leading and trailing quotation marks and spaces
    clean_title = title.strip().strip('"')

    # Remove special characters and replace spaces with underscores
    clean_title = re.sub(r'[^\w\s-]', '', clean_title)
    clean_title = re.sub(r'[-\s]+', '_', clean_title)

    # Create data directory if it doesn't exist
    data_dir = os.path.join(os.path.dirname(script_dir), "data")
    os.makedirs(data_dir, exist_ok=True)

    # Create a directory for the story type
    story_type_dir = os.path.join(data_dir, story_type)
    os.makedirs(story_type_dir, exist_ok=True)

    # Create a directory for this story
    story_dir = os.path.join(story_type_dir, clean_title)
    os.makedirs(story_dir, exist_ok=True)

    return story_dir

def call_openai_api(client, messages, max_retries=3):
    config = load_config()
    # Add a system message requesting JSON output
    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=config['openai']['model'],
                temperature=config['openai']['temperature'],
                messages=messages
            )
            return response.choices[0].message.content
        except Exception as e:
            print(f"An error occurred: {e}")
            if attempt < max_retries - 1:
                print(f"Retrying... (Attempt {attempt + 2} of {max_retries})")
            else:
                print("Max retries reached. Unable to get a valid response.")
    return None


def create_empty_storyboard(title):
    return {
        "project_info": {
            "title": title,
            "user": "AI Generated",
            "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %I:%M:%S %p")
        },
        "storyboards": []
    }

def pick_story_type():
    print("Choose a story type:")
    for i, story_type in enumerate(STORY_TYPES, 1):
        print(f"{i}. {story_type}")

    while True:
        try:
            choice = int(input("Enter the number of your choice: "))
            if 1 <= choice <= len(STORY_TYPES):
                return STORY_TYPES[choice - 1]
            else:
                print("Invalid choice. Please try again.")
        except ValueError:
            print("Invalid input. Please enter a number.")

def pick_image_style():
    styles = ["photorealistic", "cinematic", "anime", "comic-book", "pixar-art"]
    print("Choose an image style:")
    for i, style in enumerate(styles, 1):
        print(f"{i}. {style}")

    while True:
        try:
            choice = int(input("Enter the number of your choice: "))
            if 1 <= choice <= len(styles):
                return styles[choice - 1]
            else:
                print("Invalid choice. Please try again.")
        except ValueError:
            print("Invalid input. Please enter a number.")

# ---------------------------------------------------------------------------
# Long-form helpers
# ---------------------------------------------------------------------------

def split_paragraphs(text: str) -> List[str]:
    """Divide el texto en párrafos (separados por líneas en blanco).

    Si un párrafo supera max_chars_per_paragraph se subdivide por frases
    para no saturar el modelo de audio.
    """
    config = load_config()
    max_chars = config['long_form']['max_chars_per_paragraph']

    raw = re.split(r'\n\s*\n', text)
    paragraphs = []
    for block in raw:
        block = block.strip()
        if not block:
            continue
        if len(block) <= max_chars:
            paragraphs.append(block)
        else:
            # Subdividir por frases (punto, exclamación, interrogación + espacio)
            sentences = re.split(r'(?<=[.!?])\s+', block)
            chunk = ""
            for sentence in sentences:
                if len(chunk) + len(sentence) + 1 <= max_chars:
                    chunk = (chunk + " " + sentence).strip() if chunk else sentence
                else:
                    if chunk:
                        paragraphs.append(chunk)
                    chunk = sentence
            if chunk:
                paragraphs.append(chunk)
    return paragraphs


def build_long_storyboard(paragraphs: List[str], title: str) -> Dict:
    """Construye un storyboard_project compatible con el pipeline existente
    a partir de una lista de párrafos (modo guión largo).
    """
    project = create_empty_storyboard(title)
    project["characters"] = []  # Requerido por generate_and_download_images

    for i, paragraph in enumerate(paragraphs):
        project["storyboards"].append({
            "scene_number": i + 1,
            "description": paragraph,   # Prompt de imagen
            "subtitles": paragraph,      # Texto narrado → audio + SRT
            "image": None,
            "audio": None,
            "transition_type": "zoom-in" if i % 2 == 0 else "zoom-out",
        })
    return project


def build_srt_from_storyboard(project: Dict, srt_path: str) -> str:
    """Genera un archivo SRT a partir del texto del guión y la duración real
    del audio de cada escena (scene['_audio_duration']).

    Cada escena se parte en líneas de ≤ subtitle_max_words_per_line palabras.
    La duración se reparte entre líneas de forma proporcional al nº de caracteres.
    """
    config = load_config()
    max_words = config['long_form']['subtitle_max_words_per_line']

    entries: List[Dict] = []
    current_time = 0.0

    for scene in project['storyboards']:
        duration = scene.get('_audio_duration', 0.0)
        text = scene.get('subtitles', '').strip()
        if not text or duration <= 0:
            current_time += duration
            continue

        # Dividir en líneas de ≤ max_words palabras
        words = text.split()
        lines = []
        line_buf = []
        for word in words:
            line_buf.append(word)
            if len(line_buf) >= max_words:
                lines.append(' '.join(line_buf))
                line_buf = []
        if line_buf:
            lines.append(' '.join(line_buf))

        if not lines:
            current_time += duration
            continue

        # Repartir duración proporcionalmente al nº de caracteres de cada línea
        char_counts = [len(l) for l in lines]
        total_chars = sum(char_counts) or 1
        for line, chars in zip(lines, char_counts):
            line_duration = duration * (chars / total_chars)
            entries.append({
                'start_time': current_time,
                'end_time': current_time + line_duration,
                'text': line,
            })
            current_time += line_duration

    save_timestamped_subtitles(entries, srt_path)
    return srt_path


# ---------------------------------------------------------------------------
# Legacy subtitle helpers (conservados para el modo corto)
# ---------------------------------------------------------------------------

def convert_to_timestamped_subtitles(chinese_storyboard_project: Dict, scene_duration: int = 10) -> List[Dict]:
    timestamped_subtitles = []
    current_time = datetime.timedelta()

    for scene in chinese_storyboard_project['storyboards']:
        subtitles = scene['subtitles'].split('\n')
        time_per_subtitle = scene_duration / len(subtitles)

        for subtitle in subtitles:
            start_time = current_time
            end_time = current_time + datetime.timedelta(seconds=time_per_subtitle)

            timestamped_subtitles.append({
                'start_time': start_time.total_seconds(),
                'end_time': end_time.total_seconds(),
                'text': subtitle.strip()
            })

            current_time = end_time

    return timestamped_subtitles

def format_timedelta(seconds: float) -> str:
    td = datetime.timedelta(seconds=seconds)
    hours, remainder = divmod(td.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    milliseconds = td.microseconds // 1000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"

def save_timestamped_subtitles(timestamped_subtitles: List[Dict], output_file: str) -> None:
    with open(output_file, "w", encoding="utf-8") as f:
        for i, subtitle in enumerate(timestamped_subtitles, 1):
            f.write(f"{i}\n")
            f.write(f"{format_timedelta(subtitle['start_time'])} --> {format_timedelta(subtitle['end_time'])}\n")
            f.write(f"{subtitle['text']}\n\n")

def load_config(config_file='config.json'):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(os.path.dirname(script_dir), config_file)
    with open(config_path, 'r') as f:
        return json.load(f)

def create_blank_image(filename, width=720, height=1280):
    blank_image = Image.new('RGB', (width, height), color='black')
    blank_image.save(filename)
    print(f"Created blank image: {filename}")

def pick_voice_name():
    # alloy, echo, fable, onyx, nova, and shimmer
    voices = [
        "alloy",
        "echo",
        "fable",
        "onyx",
        "nova",
        "shimmer"
    ]
    print("Choose a voice:")
    for i, voice in enumerate(voices, 1):
        print(f"{i}. {voice}")

    while True:
        try:
            choice = int(input("Enter the number of your choice: "))
            if 1 <= choice <= len(voices):
                return voices[choice - 1]
            else:
                print("Invalid choice. Please try again.")
        except ValueError:
            print("Invalid input. Please enter a number.")
