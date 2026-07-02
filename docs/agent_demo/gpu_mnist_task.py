import os

from clearml import Task


def main() -> None:
    queue_name = os.environ.get("CLEARML_QUEUE", "gpu")
    max_steps = int(os.environ.get("MAX_STEPS", "200"))

    task = Task.init(
        project_name="Agent Demos",
        task_name="gpu_mnist_task",
        output_uri=True,
        reuse_last_task_id=False,
    )
    task.execute_remotely(queue_name=queue_name, exit_process=True)

    import torch
    import torch.nn as nn
    import torch.optim as optim
    from torch.utils.data import DataLoader
    from torch.utils.tensorboard import SummaryWriter
    from torchvision.datasets import MNIST
    from torchvision.transforms import ToTensor

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is not available on this machine")

    device = torch.device("cuda:0")

    writer = SummaryWriter()

    train_data = MNIST("data", train=True, download=True, transform=ToTensor())
    train_loader = DataLoader(
        train_data,
        batch_size=64,
        shuffle=True,
        num_workers=2,
        pin_memory=True,
    )

    model = nn.Sequential(
        nn.Linear(784, 128),
        nn.ReLU(),
        nn.Linear(128, 10),
    ).to(device)

    criterion = nn.CrossEntropyLoss()
    optimizer = optim.SGD(model.parameters(), lr=0.01)

    step = 0
    model.train()
    for inputs, labels in train_loader:
        inputs = inputs.view(-1, 784).to(device, non_blocking=True)
        labels = labels.to(device, non_blocking=True)

        optimizer.zero_grad(set_to_none=True)
        outputs = model(inputs)
        loss = criterion(outputs, labels)
        loss.backward()
        optimizer.step()

        loss_value = float(loss.item())
        writer.add_scalar("train/loss", loss_value, step)
        if step % 20 == 0:
            print(f"step={step} loss={loss_value:.6f}")

        step += 1
        if step >= max_steps:
            break

    writer.close()
    task.close()


if __name__ == "__main__":
    main()

