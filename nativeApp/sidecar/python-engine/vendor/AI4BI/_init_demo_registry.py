"""
One-shot script to bootstrap data/semiconductor_demo/registry/ from
the existing data/semiconductor_demo/blocks/*.json files.

Run from the AI4BI project root:
    python _init_demo_registry.py
"""

import json
import sys
from pathlib import Path

# Ensure ai4bi is importable
sys.path.insert(0, str(Path(__file__).parent))

from ai4bi.blocks.contracts import DataBlockContract
from ai4bi.blocks.registry import FilesystemBlockRegistry

BLOCKS_DIR = Path(__file__).parent / "data" / "semiconductor_demo" / "blocks"
REGISTRY_ROOT = Path(__file__).parent / "data" / "semiconductor_demo" / "registry"

VERSION = "1.0.0"
CERTIFIED_BY = "AUTO_CERTIFY"


def main() -> None:
    registry = FilesystemBlockRegistry(REGISTRY_ROOT)

    block_files = sorted(BLOCKS_DIR.glob("*.json"))
    if not block_files:
        print("No block JSON files found in", BLOCKS_DIR)
        sys.exit(1)

    for block_file in block_files:
        raw = json.loads(block_file.read_text(encoding="utf-8"))
        contract = DataBlockContract.model_validate(raw)

        # Copy to registry/<block_id>/1.0.0.json
        vr = registry.register(contract, VERSION)
        pointer = registry.certify(contract.block_id, VERSION, CERTIFIED_BY)

        print(
            f"  registered + certified  {contract.block_id}  "
            f"v{VERSION}  certified_latest={pointer.certified_latest}"
        )

    print(f"\nRegistry initialized at: {REGISTRY_ROOT}")
    print(f"Blocks processed: {len(block_files)}")


if __name__ == "__main__":
    main()
