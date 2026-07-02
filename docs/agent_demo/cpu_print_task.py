import os
import time

from clearml import Task


def main() -> None:
    queue_name = os.environ.get("CLEARML_QUEUE", "cpu")

    task = Task.init(
        project_name="Agent Demos",
        task_name="cpu_print_task",
        output_uri=True,
        reuse_last_task_id=False,
    )
    task.execute_remotely(queue_name=queue_name, exit_process=True)

    print("hello from clearml agent demo (cpu)")
    logger = task.get_logger()
    for i in range(5):
        logger.report_scalar(title="demo", series="i", iteration=i, value=i)
        time.sleep(1)

    task.close()


if __name__ == "__main__":
    main()

