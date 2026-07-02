#!/usr/bin/env python3
"""
All-in-one ClearML Dataset demo.

This script is intentionally small and self-contained:
- It creates tiny local demo files on the fly
- It builds a base dataset version
- It creates a child dataset version from the base dataset
- It demonstrates local files, external files, sync, removal, metadata, upload, finalize, publish
- It demonstrates how a downstream task consumes the dataset with get_local_copy()
- It also demonstrates get_mutable_local_copy() for workflows that need a writable folder

Typical usage:

    python clearml_dataset_full_demo.py

Optional usage:

    python clearml_dataset_full_demo.py --project demo_project --name-prefix toy_dataset
    python clearml_dataset_full_demo.py --output-uri s3://my-bucket/datasets --publish

Before running:
- Make sure ClearML is configured in your environment
- For example, run `clearml-init` once and verify you can create Tasks
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable

try:
    import pandas as pd
except ImportError:  # pragma: no cover - optional dependency in some environments
    pd = None

from clearml import Dataset, Task


def write_csv(path: Path, rows: Iterable[Dict[str, object]]) -> None:
    """Write a tiny CSV file used by the demo."""
    rows = list(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        raise ValueError(f"CSV rows can not be empty: {path}")
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: Dict[str, object]) -> None:
    """Write a small JSON file used by the demo."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def reset_dir(path: Path) -> None:
    """Remove an old demo directory so the current run always starts clean."""
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def build_demo_files(workspace: Path) -> Dict[str, Path]:
    """
    Create very small, human-readable toy data.

    The files are deliberately simple so the ClearML Dataset behavior stays easy to inspect:
    - tabular/train.csv: base version training rows
    - meta/labels.json: label mapping / metadata-like side file
    - docs/notes.txt: file that will later be removed in the child dataset
    - sync_source/tabular/*.csv: local folder used to demonstrate sync_folder()
    - external_store/reference.csv: local file exposed as file:// to simulate external storage
    """
    reset_dir(workspace)

    base_source = workspace / "base_source"
    sync_source = workspace / "sync_source"
    external_store = workspace / "external_store"
    mutable_target = workspace / "mutable_local_copy"

    # Base local data: this is the first dataset version.
    write_csv(
        base_source / "tabular" / "train.csv",
        [
            {"sample_id": 1, "feature": 0.10, "label": "low"},
            {"sample_id": 2, "feature": 0.45, "label": "mid"},
            {"sample_id": 3, "feature": 0.90, "label": "high"},
        ],
    )
    write_json(
        base_source / "meta" / "labels.json",
        {
            "low": 0,
            "mid": 1,
            "high": 2,
            "description": "Tiny label mapping for the ClearML Dataset demo",
        },
    )
    (base_source / "docs").mkdir(parents=True, exist_ok=True)
    (base_source / "docs" / "notes.txt").write_text(
        "This file exists in v1 and will be removed in the child dataset version.\n",
        encoding="utf-8",
    )

    # Sync source: this folder represents the local truth for tabular data in the child version.
    # sync_folder() will compare this folder to the dataset subtree and register additions / modifications.
    write_csv(
        sync_source / "train.csv",
        [
            {"sample_id": 1, "feature": 0.11, "label": "low"},   # slightly corrected value
            {"sample_id": 2, "feature": 0.44, "label": "mid"},   # slightly corrected value
            {"sample_id": 3, "feature": 0.92, "label": "high"},  # slightly corrected value
        ],
    )
    write_csv(
        sync_source / "valid.csv",
        [
            {"sample_id": 101, "feature": 0.20, "label": "low"},
            {"sample_id": 102, "feature": 0.60, "label": "mid"},
        ],
    )

    # External file: we use a local file:// URI so the example stays simple and still demonstrates add_external_files().
    write_csv(
        external_store / "reference.csv",
        [
            {"bucket": "A", "threshold": 0.30},
            {"bucket": "B", "threshold": 0.70},
        ],
    )

    return {
        "workspace": workspace,
        "base_source": base_source,
        "sync_source": sync_source,
        "external_store": external_store,
        "mutable_target": mutable_target,
    }


def maybe_set_metadata(dataset: Dataset, version_name: str, source_kind: str) -> None:
    """
    Attach a tiny piece of metadata to the dataset.

    If pandas is available, we store a tiny DataFrame so it can also appear nicely in the UI.
    Otherwise we fall back to a plain dictionary, which is still useful programmatically.
    """
    if pd is not None:
        metadata = pd.DataFrame(
            [
                {"field": "version_name", "value": version_name},
                {"field": "source_kind", "value": source_kind},
                {"field": "demo_size", "value": "tiny"},
            ]
        )
        dataset.set_metadata(metadata, metadata_name="demo_profile", ui_visible=True)
    else:
        dataset.set_metadata(
            {
                "version_name": version_name,
                "source_kind": source_kind,
                "demo_size": "tiny",
            },
            metadata_name="demo_profile",
            ui_visible=False,
        )


def create_base_dataset(
    project: str,
    dataset_name: str,
    output_uri: str | None,
    paths: Dict[str, Path],
    publish: bool,
) -> Dataset:
    """
    Create version 1 of the demo dataset from local files only.

    This covers the most common "producer" workflow:
    create -> add_files -> upload -> finalize -> publish(optional)
    """
    print("\n[STEP 1] Create base dataset from local files")
    base_dataset = Dataset.create(
        dataset_project=project,
        dataset_name=dataset_name,
        output_uri=output_uri,
        description="Base version of the tiny ClearML Dataset demo",
    )

    # Put each local folder under an explicit dataset path so the final dataset layout is easy to inspect.
    base_dataset.add_files(paths["base_source"] / "tabular", dataset_path="tabular")
    base_dataset.add_files(paths["base_source"] / "meta", dataset_path="meta")
    base_dataset.add_files(paths["base_source"] / "docs", dataset_path="docs")
    maybe_set_metadata(base_dataset, version_name="v1_base", source_kind="local_files")

    # upload() is the step that moves local file entries to remote storage managed by ClearML.
    base_dataset.upload(output_url=output_uri) if output_uri else base_dataset.upload()
    base_dataset.finalize()

    if publish:
        base_dataset.publish()

    print(f"  Base dataset id      : {base_dataset.id}")
    print(f"  Base dataset files   : {len(base_dataset.list_files())}")
    return base_dataset


def create_child_dataset(
    project: str,
    dataset_name: str,
    output_uri: str | None,
    parent: Dataset,
    paths: Dict[str, Path],
    publish: bool,
) -> Dataset:
    """
    Create version 2 as a child dataset.

    This step demonstrates the "incremental maintenance" workflow:
    - inherit from a parent dataset
    - sync a local folder into one subtree
    - add an external file via file:// URI
    - remove an obsolete file
    - upload and finalize the new version
    """
    print("\n[STEP 2] Create child dataset with sync, external files, and file removal")
    child_dataset = Dataset.create(
        dataset_project=project,
        dataset_name=dataset_name,
        parent_datasets=[parent.id],
        output_uri=output_uri,
        description="Child version of the tiny ClearML Dataset demo",
    )

    # sync_folder() is useful when a local directory is your current source of truth.
    # We sync it into dataset path "tabular", so train.csv is updated and valid.csv is added.
    child_dataset.sync_folder(paths["sync_source"], dataset_path="tabular", verbose=False)

    # add_external_files() usually points to cloud/object storage.
    # Here we use a local file:// URI so the example is still runnable on one machine.
    child_dataset.add_external_files(
        source_url=(paths["external_store"] / "reference.csv").as_uri(),
        dataset_path="external",
    )

    # remove_files() demonstrates how to remove obsolete content in the new dataset version.
    child_dataset.remove_files("docs/notes.txt")
    maybe_set_metadata(child_dataset, version_name="v2_child", source_kind="local_plus_external")

    child_dataset.upload(output_url=output_uri) if output_uri else child_dataset.upload()
    child_dataset.finalize()

    if publish:
        child_dataset.publish()

    print(f"  Child dataset id     : {child_dataset.id}")
    print(f"  Child dataset files  : {len(child_dataset.list_files())}")
    return child_dataset


def consume_dataset(project: str, dataset_name: str, dataset_id: str, workspace: Path) -> None:
    """
    Simulate a downstream training/inference task that consumes the dataset.

    This shows the "consumer" side:
    - Task.init() creates a normal experiment / job task
    - Dataset.get(..., alias=..., overridable=True) records which dataset is used
    - get_local_copy() gives a read-only merged dataset path
    - get_mutable_local_copy() creates a writable copy for extra processing
    """
    print("\n[STEP 3] Consume the latest dataset in a downstream task")
    task = Task.init(
        project_name=project,
        task_name=f"{dataset_name}_consumer_demo",
        task_type=Task.TaskTypes.data_processing,
    )

    # alias + overridable is a practical pattern for training jobs:
    # the task records which dataset was used, and remote runs can override it more cleanly.
    dataset = Dataset.get(
        dataset_id=dataset_id,
        alias="demo_dataset",
        overridable=True,
    )

    latest_by_name = Dataset.get(
        dataset_project=project,
        dataset_name=dataset_name,
        only_completed=False,
        alias="latest_demo_dataset",
        overridable=True,
    )

    local_copy = Path(dataset.get_local_copy())
    print(f"  Dataset fetched by id      : {dataset.id}")
    print(f"  Latest dataset fetched     : {latest_by_name.id}")
    print(f"  Read-only local copy path  : {local_copy}")

    files = dataset.list_files()
    print("  Files in dataset:")
    for relative_path in files:
        print(f"    - {relative_path}")

    # A writable copy is useful for preprocessing / feature generation / temp edits.
    mutable_target = workspace / "mutable_local_copy"
    if mutable_target.exists():
        shutil.rmtree(mutable_target)
    writable_copy = dataset.get_mutable_local_copy(target_folder=mutable_target, overwrite=True)
    print(f"  Writable local copy path   : {writable_copy}")

    # verify_dataset_hash() is optional, but it is a good example of a validation helper.
    hash_ok = dataset.verify_dataset_hash()
    print(f"  Dataset hash verification  : {hash_ok}")

    # Report a tiny summary so the consumer task has something visible in the UI.
    task.get_logger().report_text(
        "Consumed ClearML Dataset demo successfully.\n"
        f"dataset_id={dataset.id}\n"
        f"local_copy={local_copy}\n"
        f"writable_copy={writable_copy}",
        print_console=False,
    )
    task.close()


def parse_args() -> argparse.Namespace:
    """Parse CLI options so the example can be reused in different environments."""
    parser = argparse.ArgumentParser(description="Runnable all-in-one ClearML Dataset demo")
    parser.add_argument(
        "--project",
        default="clearml_dataset_demo",
        help="ClearML project name used to store the demo datasets and the consumer task",
    )
    parser.add_argument(
        "--name-prefix",
        default="toy_dataset",
        help="Dataset base name prefix; a timestamp suffix is added automatically",
    )
    parser.add_argument(
        "--workspace",
        default="./demo_artifacts/clearml_dataset_demo",
        help="Local folder used to generate the toy files and the writable dataset copy",
    )
    parser.add_argument(
        "--output-uri",
        default=None,
        help="Optional dataset upload destination, for example s3://bucket/demo or /mnt/share/demo",
    )
    parser.add_argument(
        "--publish",
        action="store_true",
        help="Publish the generated dataset versions after finalize()",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dataset_name = f"{args.name_prefix}_{timestamp}"
    workspace = Path(args.workspace).expanduser().resolve()

    print("ClearML Dataset full demo")
    print(f"  project      : {args.project}")
    print(f"  dataset_name : {dataset_name}")
    print(f"  workspace    : {workspace}")
    if args.output_uri:
        print(f"  output_uri   : {args.output_uri}")

    paths = build_demo_files(workspace)
    base_dataset = create_base_dataset(
        project=args.project,
        dataset_name=dataset_name,
        output_uri=args.output_uri,
        paths=paths,
        publish=args.publish,
    )
    child_dataset = create_child_dataset(
        project=args.project,
        dataset_name=dataset_name,
        output_uri=args.output_uri,
        parent=base_dataset,
        paths=paths,
        publish=args.publish,
    )
    consume_dataset(
        project=args.project,
        dataset_name=dataset_name,
        dataset_id=child_dataset.id,
        workspace=workspace,
    )

    print("\nDone.")
    print("What this demo covered:")
    print("  - Dataset.create()")
    print("  - add_files()")
    print("  - add_external_files()")
    print("  - sync_folder()")
    print("  - remove_files()")
    print("  - set_metadata()")
    print("  - upload()")
    print("  - finalize()")
    if args.publish:
        print("  - publish()")
    print("  - Dataset.get()")
    print("  - list_files()")
    print("  - get_local_copy()")
    print("  - get_mutable_local_copy()")
    print("  - verify_dataset_hash()")


if __name__ == "__main__":
    main()
