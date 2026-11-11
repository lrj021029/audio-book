"""Complete data generation runner with streaming inserts and small batches.

Usage: python gen_complete.py
"""
import os, sys, time

os.environ["TERM"] = "dumb"

import rich.console
rich.console.Console = type("FC", (), {
    "print": staticmethod(lambda *a, **kw: print(a[0] if a else "")),
    "__init__": lambda *a, **kw: None,
})
import rich.progress
class FP:
    def __init__(self, *a, **kw): pass
    def __enter__(self): return self
    def __exit__(self, *a): return None
    def add_task(self, *a, **kw): return 0
    def update(self, *a, **kw): pass
    def advance(self, *a, **kw): pass
    def start_task(self, *a, **kw): pass
    def stop_task(self, *a, **kw): pass
    def remove_task(self, *a, **kw): pass
rich.progress.Progress = FP
import contextlib
import generate.progress as gp
gp.Console = rich.console.Console
gp.Progress = rich.progress.Progress
gp.ProgressColumn = object
gp.SpinnerColumn = None
gp.TextColumn = None
gp._console = None
gp._progress = None
@contextlib.contextmanager
def ppc(): yield
gp.progress_context = ppc

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from generate.config import GENERATION_PROFILES, GENERATION_DEFAULTS, LAYERS
GENERATION_DEFAULTS.clear()
GENERATION_DEFAULTS.update(GENERATION_PROFILES["smoke"])
GENERATION_DEFAULTS["batch_size"] = 300  # Smaller batches for remote DB

from generate.db import init_db, close_db, db
from generate.insert_support import insert_dict_rows, insert_dict_rows_stream

def step(name, func):
    print(f"\n--- {name} ---", flush=True)
    t0 = time.time()
    result = func()
    print(f"  => {name}: done in {time.time()-t0:.1f}s", flush=True)
    return result

def main():
    init_db()
    try:
        # ═══ Layer 2 remaining: audio_track, track_audio_file, etc ═══
        from generate.layers.layer2 import Layer2Generator
        from generate.layers.common import parse_datetime, to_int
        from generate.layers.seed_importer import SeedImporter
        from generate.layers.base import BaseGenerator

        g = Layer2Generator()
        seed = SeedImporter()

        # audio_track (streaming, 30k+ rows)
        albums = db.fetch_all("SELECT id, album_code, created_at, published_at FROM audio_album")
        album_by_code = {str(r["album_code"]): r for r in albums}
        source_album_codes = g.album_code_by_source()

        def track_rows():
            count = 0
            for source in seed.load_csv("2_content/audio_track.csv"):
                album_code = source_album_codes.get(
                    (str(source["source_album_type"]), str(source["source_album_id"]))
                )
                album = album_by_code.get(album_code or "")
                if not album:
                    continue
                duration = to_int(source.get("duration_seconds"))
                if duration <= 0:
                    duration = g.random.randint(420, 1800)
                published_at = parse_datetime(source.get("last_update"), g.now)
                published_at = min(max(published_at, album["created_at"]), g.now)
                created_at = g.random_datetime(album["created_at"], published_at)
                free_flag = 1 if source.get("pay_type") == "free" else 0
                yield {
                    "album_id": album["id"],
                    "track_no": to_int(source["track_no"], 1),
                    "track_title": source["track_title"],
                    "track_type": "normal",
                    "duration_seconds": duration,
                    "free_flag": free_flag,
                    "trial_seconds": duration if free_flag else min(300, duration),
                    "track_status": "published",
                    "play_count": to_int(source.get("play_count")),
                    "published_at": published_at,
                    "created_at": created_at,
                    "updated_at": g.random_datetime(created_at, g.now),
                }
                count += 1
                if count % 5000 == 0:
                    print(f"  ...generated {count} track rows", flush=True)

        step("audio_track", lambda: insert_dict_rows_stream("audio_track", track_rows(), total_rows=30969, batch_size=300))
        step("update_album_stats", g.update_album_track_stats)
        step("track_audio_file", g.generate_track_audio_files)
        step("content_upload_task", g.generate_upload_tasks)
        step("content_audit_record", g.generate_audit_records)
        step("album_update_record", g.generate_album_update_records)
        step("album_price_rule", g.generate_price_rules)

        # ═══ Layer 3 ═══
        from generate.layers.layer3 import Layer3Generator
        step("layer3", Layer3Generator().run)

        # ═══ Layer 4 ═══
        from generate.layers.layer4 import Layer4Generator
        step("layer4", Layer4Generator().run)

        # ═══ Layer 5 ═══
        from generate.layers.layer5 import Layer5Generator
        step("layer5", Layer5Generator().run)

        # ═══ Layer 6 ═══
        from generate.layers.layer6 import Layer6Generator
        step("layer6", Layer6Generator().run)

        # ═══ Acceptance ═══
        from generate.layers.validations import validate_acceptance
        print("\n=== Acceptance ===", flush=True)
        for check in validate_acceptance():
            print(f"  [OK] {check}", flush=True)

        print("\n*** ALL DATA GENERATED ***", flush=True)
    finally:
        close_db()

if __name__ == "__main__":
    main()
