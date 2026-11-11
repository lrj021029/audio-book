"""Fine-grained generation runner - each sub-step is a separate process call.

Usage:
    python gen_fine.py <step_name>

Steps:
    layer1_seeds, layer1_users, layer1_narrators
    layer2_clear, layer2_creators, layer2_albums, layer2_rels, layer2_tags
    layer2_tracks, layer2_trackfiles, layer2_uploads, layer2_audits
    layer2_updates, layer2_prices, layer2_stats
    layer3, layer4, layer5, layer6
    acceptance
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
def ppc():
    yield
gp.progress_context = ppc

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from generate.config import GENERATION_PROFILES, GENERATION_DEFAULTS, LAYERS
GENERATION_DEFAULTS.clear()
GENERATION_DEFAULTS.update(GENERATION_PROFILES["smoke"])

from generate.db import init_db, close_db, db

def run(name, func):
    print(f"\n=== {name} ===", flush=True)
    t0 = time.time()
    try:
        result = func()
        print(f"  DONE: {name} ({time.time()-t0:.1f}s) result={result}", flush=True)
    except Exception as e:
        print(f"  ERROR in {name}: {e}", flush=True)
        raise

def main():
    step = sys.argv[1] if len(sys.argv) > 1 else "help"
    init_db()
    try:
        if step == "help":
            print("Available steps listed in script docstring")
            return

        # ── Layer 1 ──
        if step == "layer1_seeds":
            from generate.layers.seed_importer import SeedImporter
            run("layer1_seeds", lambda: SeedImporter().import_layer1_seeds())

        elif step == "layer1_users":
            from generate.layers.layer1 import Layer1Generator
            g = Layer1Generator()
            run("layer1_users", g.generate_users)

        elif step == "layer1_narrators":
            from generate.layers.layer1 import Layer1Generator
            g = Layer1Generator()
            run("layer1_narrators", g.import_narrators)

        # ── Layer 2 ──
        elif step == "layer2_clear":
            from generate.layers.base import BaseGenerator
            g = BaseGenerator()
            g.layer = 2
            run("layer2_clear", g.clear_layer_tables)

        elif step == "layer2_creators":
            from generate.layers.layer2 import Layer2Generator
            g = Layer2Generator()
            run("creator_profile", g.generate_creator_profiles)
            run("creator_apply_record", g.generate_creator_apply_records)

        elif step == "layer2_albums":
            from generate.layers.layer2 import Layer2Generator
            g = Layer2Generator()
            run("audio_album", g.import_albums)
            run("album_org_rel", g.generate_album_organization_rels)
            run("album_author_rel", g.generate_album_author_rels)

        elif step == "layer2_rels":
            from generate.layers.layer2 import Layer2Generator
            g = Layer2Generator()
            run("album_narrator_rel", g.generate_album_narrator_rels)
            run("album_tag_rel", g.generate_album_tag_rels)

        elif step == "layer2_tracks":
            from generate.layers.layer2 import Layer2Generator
            g = Layer2Generator()
            run("audio_track", g.import_tracks)
            run("update_album_stats", g.update_album_track_stats)
            run("track_audio_file", g.generate_track_audio_files)

        elif step == "layer2_uploads":
            from generate.layers.layer2 import Layer2Generator
            g = Layer2Generator()
            run("content_upload_task", g.generate_upload_tasks)
            run("content_audit_record", g.generate_audit_records)

        elif step == "layer2_updates":
            from generate.layers.layer2 import Layer2Generator
            g = Layer2Generator()
            run("album_update_record", g.generate_album_update_records)
            run("album_price_rule", g.generate_price_rules)

        # ── Layer 3-6 ──
        elif step == "layer3":
            from generate.layers.layer3 import Layer3Generator
            g = Layer3Generator()
            run("layer3", g.run)

        elif step == "layer4":
            from generate.layers.layer4 import Layer4Generator
            g = Layer4Generator()
            run("layer4", g.run)

        elif step == "layer5":
            from generate.layers.layer5 import Layer5Generator
            g = Layer5Generator()
            run("layer5", g.run)

        elif step == "layer6":
            from generate.layers.layer6 import Layer6Generator
            g = Layer6Generator()
            run("layer6", g.run)

        elif step == "acceptance":
            from generate.layers.validations import validate_acceptance
            for check in validate_acceptance():
                print(f"  [OK] acceptance: {check}")

        else:
            print(f"Unknown step: {step}")
    finally:
        close_db()

if __name__ == "__main__":
    main()
