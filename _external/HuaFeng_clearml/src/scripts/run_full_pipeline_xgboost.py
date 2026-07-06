import argparse
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from time import perf_counter


def _find_project_root(start: Path) -> Path:
    start = start.resolve()
    for p in [start, *start.parents]:
        if (p / "src" / "data_pipeline").is_dir() and (p / "src" / "models" / "xgboost").is_dir():
            return p
    return start.parents[1]


PROJECT_ROOT = _find_project_root(Path(__file__))


@dataclass(frozen=True)
class GpuInfo:
    index: int
    memory_total_mb: int
    memory_free_mb: int


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _log(msg: str) -> None:
    print(f"[{_now()}] {msg}", flush=True)


def _run_cmd(argv: list[str], cwd: Path) -> None:
    _log("run: " + " ".join([str(x) for x in argv]))
    t0 = perf_counter()
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    subprocess.run(argv, cwd=str(cwd), check=True, env=env)
    _log(f"done: exit=0, elapsed_sec={perf_counter() - t0:.2f}")


def _parse_nvidia_smi_csv(text: str) -> list[GpuInfo]:
    gpus: list[GpuInfo] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 3:
            continue
        try:
            idx = int(parts[0])
            total = int(parts[1])
            free = int(parts[2])
        except ValueError:
            continue
        gpus.append(GpuInfo(index=idx, memory_total_mb=total, memory_free_mb=free))
    return gpus


def _query_gpus() -> list[GpuInfo]:
    try:
        out = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=index,memory.total,memory.free",
                "--format=csv,noheader,nounits",
            ],
            stderr=subprocess.STDOUT,
            text=True,
        )
    except Exception:
        return []
    return _parse_nvidia_smi_csv(out)


def _visible_gpu_mapping() -> list[int] | None:
    raw = os.environ.get("CUDA_VISIBLE_DEVICES")
    if raw is None:
        return None
    raw = raw.strip()
    if not raw or raw == "-1":
        return None
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if not parts:
        return None
    physical: list[int] = []
    for p in parts:
        if not p.isdigit():
            return None
        physical.append(int(p))
    return physical


def pick_best_gpu_id(min_free_mb: int = 1024) -> str:
    gpus = _query_gpus()
    if not gpus:
        return "cpu"

    visible_physical = _visible_gpu_mapping()
    if visible_physical is not None:
        visible_set = set(visible_physical)
        gpus = [g for g in gpus if g.index in visible_set]
        if not gpus:
            return "cpu"

    eligible = [g for g in gpus if g.memory_free_mb >= min_free_mb] or gpus
    best = max(eligible, key=lambda g: (g.memory_free_mb, g.memory_total_mb))

    if visible_physical is None:
        return str(best.index)
    return str(visible_physical.index(best.index))


def run_pipeline(args: argparse.Namespace) -> None:
    py = sys.executable
    cwd = PROJECT_ROOT
    pyu = [py, "-u"]
    _log(f"project_root: {cwd}")
    _log(f"station: {args.station}, region: {args.region}, n_workers: {args.n_workers}")
    _log(f"output_root: {args.output_root}")

    if not args.skip_s1:
        _log("Step1: station_data_reformat")
        _run_cmd([*pyu, str(cwd / "src/data_pipeline/s1_station_data_reformat.py")], cwd=cwd)

    if not args.skip_s2:
        _log("Step2: station_ECMWF_features_reformat")
        cmd = [
            *pyu,
            str(cwd / "src/data_pipeline/s2_station_ECMWF_features_reformat.py"),
            "--n-workers",
            str(args.n_workers),
        ]
        if args.station != "all":
            cmd += ["--station", args.station]
        if args.region is not None:
            cmd += ["--region", args.region]
        _run_cmd(cmd, cwd=cwd)

    if not args.skip_s3:
        _log("Step3: merge_power_and_ECMWF_features_wind")
        cmd = [
            *pyu,
            str(cwd / "src/data_pipeline/s3_merge_power_and_ECMWF_features_wind.py"),
            "--n-workers",
            str(args.n_workers),
        ]
        if args.station != "all":
            cmd += ["--station", args.station]
        _run_cmd(cmd, cwd=cwd)

    if not args.skip_s4:
        _log("Step4: dataset_split")
        cmd = [
            *pyu,
            str(cwd / "src/data_pipeline/s4_dataset_split.py"),
            "--seq-len",
            str(args.seq_len),
            "--gap-len",
            str(args.gap_len),
            "--pred-len",
            str(args.pred_len),
        ]
        if args.save_split:
            cmd.append("--save-split")
            if args.test_months:
                cmd += ["--test-months", *args.test_months]
        _run_cmd(cmd, cwd=cwd)

    if not args.skip_s5:
        _log("Step5: train_xgboost_wind")
        gpu_id = args.gpu
        if gpu_id == "auto":
            selected = pick_best_gpu_id(min_free_mb=args.min_free_mb)
            gpu_id = selected
            if gpu_id.lower() != "cpu":
                gpus = _query_gpus()
                visible_physical = _visible_gpu_mapping()
                if visible_physical is None:
                    chosen = next((g for g in gpus if str(g.index) == str(gpu_id)), None)
                    if chosen is not None:
                        _log(
                            f"gpu=auto -> gpu_id={gpu_id}, free_mb={chosen.memory_free_mb}, total_mb={chosen.memory_total_mb}"
                        )
                else:
                    physical = visible_physical[int(gpu_id)] if str(gpu_id).isdigit() else None
                    if physical is not None:
                        chosen = next((g for g in gpus if g.index == physical), None)
                        if chosen is not None:
                            _log(
                                f"gpu=auto -> CUDA_VISIBLE_DEVICES={visible_physical}, gpu_id={gpu_id} (physical={physical}), free_mb={chosen.memory_free_mb}, total_mb={chosen.memory_total_mb}"
                            )
            else:
                _log("gpu=auto -> cpu (no available gpu or nvidia-smi not found)")
        cmd = [
            *pyu,
            str(cwd / "src/models/xgboost/train_xgboost_wind.py"),
            "--gpu_id",
            str(gpu_id),
            "--output_root",
            str(args.output_root),
        ]
        if args.station != "all":
            cmd += ["--station", args.station]
        if args.forecast_index != "all":
            cmd += ["--forecast_index", str(args.forecast_index)]
        _run_cmd(cmd, cwd=cwd)

    if not args.skip_s6:
        _log("Step6: result_cal_metrics")
        cmd = [
            *pyu,
            str(cwd / "src/models/xgboost/result_cal_metrics.py"),
            "--data-root",
            str(Path(args.output_root) / "results"),
            "--eval-root",
            str(Path(args.output_root) / "eval"),
        ]
        if args.station != "all":
            cmd += ["--stations", args.station]
        if args.forecast_index != "all":
            cmd += ["--forecast-index", str(args.forecast_index)]
        _run_cmd(cmd, cwd=cwd)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    p.add_argument("--station", type=str, default="all")
    p.add_argument("--region", type=str, default=None)
    p.add_argument("--n-workers", type=int, default=16)

    p.add_argument("--seq-len", type=int, default=16)
    p.add_argument("--gap-len", type=int, default=1)
    p.add_argument("--pred-len", type=int, default=16)
    p.add_argument("--save-split", action="store_true")
    p.add_argument("--test-months", nargs="*", default=None)

    p.add_argument("--forecast-index", type=str, default="all")
    p.add_argument("--output-root", type=str, default="/mnt/md0/zhouyunqi/HuaFeng/outputs")

    p.add_argument("--gpu", type=str, default="auto")
    p.add_argument("--min-free-mb", type=int, default=1024)

    p.add_argument("--skip-s1", action="store_true")
    p.add_argument("--skip-s2", action="store_true")
    p.add_argument("--skip-s3", action="store_true")
    p.add_argument("--skip-s4", action="store_true")
    p.add_argument("--skip-s5", action="store_true")
    p.add_argument("--skip-s6", action="store_true")
    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    run_pipeline(args)


if __name__ == "__main__":
    main()
