"""Project locations, resolved independently of the working directory."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'raw'
RESULTS = ROOT / 'results'
LEGACY = RESULTS / 'legacy'
STOPS = RESULTS / 'stops'
