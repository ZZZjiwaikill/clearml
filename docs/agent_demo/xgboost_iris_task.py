import argparse
from pathlib import Path

import xgboost as xgb
from clearml import Task
from sklearn.datasets import load_iris
from sklearn.metrics import accuracy_score
from sklearn.model_selection import train_test_split


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a script-based ClearML XGBoost task for clone/agent testing."
    )
    parser.add_argument(
        "--project-name",
        default="Getting Started-zyq",
        help="ClearML project name.",
    )
    parser.add_argument(
        "--task-name",
        default="XGBoost Training Script",
        help="ClearML task name.",
    )
    parser.add_argument(
        "--model-path",
        default="best_model.json",
        help="Where to save the trained XGBoost model.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    task = Task.init(
        project_name=args.project_name,
        task_name=args.task_name,
        output_uri=True,
        reuse_last_task_id=False,
    )

    X, y = load_iris(return_X_y=True)
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=100
    )

    dtrain = xgb.DMatrix(X_train, label=y_train)
    dtest = xgb.DMatrix(X_test, label=y_test)

    params = {
        "max_depth": 2,
        "eta": 1,
        "objective": "reg:squarederror",
        "nthread": 4,
        "eval_metric": "rmse",
    }
    task.connect(params)

    booster = xgb.train(
        params,
        dtrain,
        num_boost_round=100,
        evals=[(dtrain, "train"), (dtest, "test")],
        verbose_eval=0,
    )

    predictions = booster.predict(dtest)
    rounded_predictions = predictions.round().clip(0, 2)
    accuracy = accuracy_score(y_test, rounded_predictions)

    logger = task.get_logger()
    logger.report_scalar(
        title="metrics",
        series="test_accuracy",
        iteration=0,
        value=float(accuracy),
    )

    model_path = Path(args.model_path)
    model_path.parent.mkdir(parents=True, exist_ok=True)
    booster.save_model(model_path.as_posix())
    task.close()


if __name__ == "__main__":
    main()
