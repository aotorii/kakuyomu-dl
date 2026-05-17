from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

OUT_DIR = ROOT / "out"
OUT_DIR.mkdir(exist_ok=True)