import argparse
from pathlib import Path

import xgboost as xgb
from clearml import OutputModel, Task
from sklearn.datasets import load_iris
from sklearn.metrics import accuracy_score
from sklearn.model_selection import train_test_split
"""
这个代码脚本是一个“普通脚本型 ClearML Task”
- 只有 Task.init() ， 没有 task.execute_remotely() ，见 xgboost_iris_task.py:L36-L41
- 所以你 直接运行这个 .py 时，任务会在你当前这台机器本地执行；你后台启动的 1 个 CPU agent 和 2 个 GPU agent 不会接手这个任务
- 只有当你在 ClearML 平台上把这个任务 Clone 之后再 Enqueue 到某个队列，agent 才会真正参与执行
"""

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
    parser.add_argument(
        "--model-name",
        default="xgboost_iris_model",
        help="ClearML model entity name shown in the Models UI.",
    )
    parser.add_argument(
        "--publish-model",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Publish the registered ClearML model after upload.",
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
    params = task.connect(params)

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

    output_model = OutputModel(task=task, name=args.model_name, framework="XGBoost")
    output_model.update_design(config_dict=params)
    output_model.set_metadata("task_id", task.id, v_type="str")
    output_model.set_metadata("dataset", "sklearn.datasets.load_iris", v_type="str")
    output_model.set_metadata("model_path", model_path.as_posix(), v_type="str")
    output_model.set_metadata("test_accuracy", str(float(accuracy)), v_type="float")
    output_model.update_weights(weights_filename=model_path.as_posix())
    output_model.report_single_value(name="test_accuracy", value=float(accuracy))
    output_model.tags = ["xgboost", "iris", "ready-for-serving"]
    if args.publish_model:
        output_model.publish()

    task.upload_artifact(
        name="serving_manifest",
        artifact_object={
            "task_id": task.id,
            "model_id": output_model.id,
            "model_name": args.model_name,
            "model_path": model_path.as_posix(),
            "published": bool(args.publish_model),
            "test_accuracy": float(accuracy),
        },
    )
    print(f"Registered ClearML model id: {output_model.id}")
    print(
        "Model registered under Models. To appear in Models Endpoints, deploy this model "
        "with ClearML Serving / clearml-serving using the model_id above."
    )
    task.close()


if __name__ == "__main__":
    main()
