"""Step-by-step data generation script to avoid timeout issues.

Each step is a separate function that can be called independently.
Usage:
    python gen_steps.py step1   # Run step 1 only
    python gen_steps.py all     # Run all steps sequentially
"""
import os
import sys
import time

# Disable rich progress
os.environ["TERM"] = "dumb"

import rich.console
rich.console.Console = type("FakeConsole", (), {
    "print": staticmethod(lambda *a, **kw: print(a[0] if a else "")),
    "__init__": lambda *a, **kw: None,
})

import rich.progress
class FakeProgress:
    def __init__(self, *a, **kw): pass
    def __enter__(self): return self
    def __exit__(self, *a): return None
    def add_task(self, *a, **kw): return 0
    def update(self, *a, **kw): pass
    def advance(self, *a, **kw): pass
    def start_task(self, *a, **kw): pass
    def stop_task(self, *a, **kw): pass
    def remove_task(self, *a, **kw): pass
rich.progress.Progress = FakeProgress

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
def patched_progress_context():
    yield
gp.progress_context = patched_progress_context

# Load env and config
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from generate.config import GENERATION_PROFILES, GENERATION_DEFAULTS, LAYERS
GENERATION_DEFAULTS.clear()
GENERATION_DEFAULTS.update(GENERATION_PROFILES["smoke"])

from generate.db import db, init_db, close_db

STEPS = []

def step(name):
    def decorator(func):
        STEPS.append((name, func))
        return func
    return decorator

@step("layer1_seeds")
def step_layer1_seeds():
    """Import Layer 1 seed data (categories, tags, channels, etc.)"""
    from generate.layers.seed_importer import SeedImporter
    importer = SeedImporter()
    counts = importer.import_layer1_seeds()
    print(f"  Seeds imported: {counts}")
    return counts

@step("layer1_stamp")
def step_layer1_stamp():
    """Stamp seed tables with timestamps"""
    from generate.layers.layer1 import Layer1Generator
    gen = Layer1Generator()
    gen.stamp_seed_tables()
    print("  Seed tables stamped with timestamps")

@step("layer1_users")
def step_layer1_users():
    """Generate user accounts"""
    from generate.layers.layer1 import Layer1Generator
    gen = Layer1Generator()
    count = gen.generate_users()
    print(f"  user_account: {count} rows")
    return count

@step("layer1_narrators")
def step_layer1_narrators():
    """Import narrators from CSV"""
    from generate.layers.layer1 import Layer1Generator
    gen = Layer1Generator()
    count = gen.import_narrators()
    print(f"  content_narrator: {count} rows")
    return count

@step("layer1_validate")
def step_layer1_validate():
    """Validate Layer 1"""
    from generate.layers.validations import validate_layer1
    for check in validate_layer1():
        print(f"  [OK] {check}")

@step("layer2")
def step_layer2():
    """Run Layer 2: content supply and assets"""
    from generate.layers.layer2 import Layer2Generator
    gen = Layer2Generator()
    gen.header()
    gen.clear_layer_tables()
    counts = {table: 0 for table in LAYERS[2]["tables"]}
    steps2 = [
        ("creator_profile", "generate_creator_profiles"),
        ("creator_apply_record", "generate_creator_apply_records"),
        ("audio_album", "import_albums"),
        ("album_organization_rel", "generate_album_organization_rels"),
        ("album_author_rel", "generate_album_author_rels"),
        ("album_narrator_rel", "generate_album_narrator_rels"),
        ("album_tag_rel", "generate_album_tag_rels"),
        ("audio_track", "import_tracks"),
        ("track_audio_file", "generate_track_audio_files"),
        ("content_upload_task", "generate_upload_tasks"),
        ("content_audit_record", "generate_audit_records"),
        ("album_update_record", "generate_album_update_records"),
        ("album_price_rule", "generate_price_rules"),
    ]
    for table_name, method_name in steps2:
        method = getattr(gen, method_name)
        count = method()
        counts[table_name] = count
        print(f"  [OK] {table_name}: {count} rows", flush=True)
    gen.update_album_track_stats()
    print("  Layer 2 complete")

@step("layer3")
def step_layer3():
    """Run Layer 3: user membership and preferences"""
    from generate.layers.layer3 import Layer3Generator
    Layer3Generator().run()
    print("  Layer 3 complete")

@step("layer4")
def step_layer4():
    """Run Layer 4: trade and wallet"""
    from generate.layers.layer4 import Layer4Generator
    Layer4Generator().run()
    print("  Layer 4 complete")

@step("layer5")
def step_layer5():
    """Run Layer 5: playback and interaction"""
    from generate.layers.layer5 import Layer5Generator
    Layer5Generator().run()
    print("  Layer 5 complete")

@step("layer6")
def step_layer6():
    """Run Layer 6: operations and search"""
    from generate.layers.layer6 import Layer6Generator
    Layer6Generator().run()
    print("  Layer 6 complete")

@step("acceptance")
def step_acceptance():
    """Run acceptance validation"""
    from generate.layers.validations import validate_acceptance
    for check in validate_acceptance():
        print(f"  [OK] acceptance: {check}")

def run_step(step_name: str):
    for name, func in STEPS:
        if name == step_name:
            print(f"\n=== Running step: {name} ===", flush=True)
            start = time.time()
            func()
            elapsed = time.time() - start
            print(f"=== Step {name} done ({elapsed:.1f}s) ===\n", flush=True)
            return True
    print(f"Unknown step: {step_name}")
    print(f"Available steps: {[name for name, _ in STEPS]}")
    return False

def run_all():
    for name, func in STEPS:
        print(f"\n=== Running step: {name} ===", flush=True)
        start = time.time()
        func()
        elapsed = time.time() - start
        print(f"=== Step {name} done ({elapsed:.1f}s) ===\n", flush=True)

def main():
    if len(sys.argv) < 2:
        print(f"Usage: python {sys.argv[0]} <step_name|all>")
        print(f"Available steps: {[name for name, _ in STEPS]}")
        return

    init_db()
    try:
        if sys.argv[1] == "all":
            run_all()
        else:
            for step_name in sys.argv[1:]:
                run_step(step_name)
    finally:
        close_db()

if __name__ == "__main__":
    main()
