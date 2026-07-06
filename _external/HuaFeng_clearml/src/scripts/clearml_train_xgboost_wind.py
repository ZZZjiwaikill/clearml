import argparse
import os
import subprocess
import sys
from pathlib import Path

from clearml import Task


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _parse_known_args(argv: list[str]) -> tuple[argparse.Namespace, list[str]]:
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--clearml-project", type=str, default="HuaFeng")
    p.add_argument("--clearml-task-name", type=str, default="train_xgboost_wind")
    p.add_argument("--clearml-queue", type=str, default=os.environ.get("CLEARML_QUEUE", "cpu"))
    p.add_argument("--clearml-output-uri", type=str, default=os.environ.get("CLEARML_OUTPUT_URI", ""))
    return p.parse_known_args(argv)


def _default_output_root(root: Path) -> str:
    return str(root / "outputs")


def main() -> None:
    known, rest = _parse_known_args(sys.argv[1:])
    root = _project_root()

    task_kwargs: dict = {
        "project_name": known.clearml_project,
        "task_name": known.clearml_task_name,
        "reuse_last_task_id": False,
    }
    if known.clearml_output_uri:
        task_kwargs["output_uri"] = known.clearml_output_uri
    else:
        task_kwargs["output_uri"] = True

    task = Task.init(**task_kwargs)
    task.connect(
        {
            "clearml_project": known.clearml_project,
            "clearml_task_name": known.clearml_task_name,
            "clearml_queue": known.clearml_queue,
            "argv": rest,
        }
    )
    task.execute_remotely(queue_name=known.clearml_queue, exit_process=True)

    script = root / "src" / "models" / "xgboost" / "train_xgboost_wind.py"
    argv = [sys.executable, "-u", str(script), *rest]
    if "--output_root" not in rest and "--output-root" not in rest:
        argv += ["--output_root", _default_output_root(root)]

    subprocess.run(argv, cwd=str(root), check=True)

    output_root = Path(_default_output_root(root))
    for key in ("--output_root", "--output-root"):
        if key in rest:
            idx = rest.index(key)
            if idx + 1 < len(rest):
                output_root = Path(rest[idx + 1]).expanduser().resolve()
            break

    if output_root.is_dir():
        task.upload_artifact(name="outputs", artifact_object=str(output_root))

    task.close()


if __name__ == "__main__":
    main()

