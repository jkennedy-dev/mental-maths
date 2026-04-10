from pathlib import Path

DATA_FILE = Path.home() / ".mental-maths.json"
VOICE_MODEL_DIR = Path.home() / ".local" / "share" / "mental-maths" / "vosk-model"
OPERATIONS = ["Addition", "Subtraction", "Multiplication", "Division"]
TIME_OPTIONS = [
    ("30 seconds", 30),
    ("1 minute", 60),
    ("2 minutes", 120),
    ("5 minutes", 300),
    ("10 minutes", 600),
]


class QuitGame(Exception):
    """Raised from any screen to exit the program."""
