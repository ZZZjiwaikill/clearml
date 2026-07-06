"""
将 s3 阶段输出的站点级时序 CSV 滑窗切分为监督学习样本，并保存为 PKL。

输入：
- /mnt/md0/zhouyunqi/HuaFeng/data/s3_dataset_pre/{站点}.csv

输出：
- /mnt/md0/zhouyunqi/HuaFeng/data/s4_dataset_CDQ/{站点}.pkl

样本构造（与原脚本逻辑一致）：
- 设历史窗口长度 seq_len、预测窗口长度 pred_len，并允许在两者之间插入 gap_len 个时间步的间隔。
- 每个滑窗样本原始长度为 seq_len + gap_len + pred_len；
  其中 gap_len 部分会被丢弃（squeeze_gap），最终样本长度为 seq_len + pred_len。

说明：
- 该脚本本身不做训练/测试集拆分；下游（例如 xgboost 训练脚本）通常依据样本内的 date_time 来划分月份。
- 如需直接在此处导出 train/test 两份文件，可以开启 --save-split（测试集月份默认 2026-04/2026-05）。
"""

import argparse
import os
import pickle as pkl

import pandas as pd
from tqdm import tqdm


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


parser = argparse.ArgumentParser()
parser.add_argument(
    "--input-dir",
    type=str,
    default="/mnt/md0/zhouyunqi/HuaFeng/data/s3_dataset_pre",
    help="s3 输出目录（每站一个 CSV）",
)
parser.add_argument(
    "--output-dir",
    type=str,
    default="/mnt/md0/zhouyunqi/HuaFeng/data/s4_dataset_CDQ",
    help="s4 输出目录（每站一个 PKL）",
)
parser.add_argument("--seq-len", type=int, default=16, help="历史窗口长度")
parser.add_argument(
    "--gap-len",
    type=int,
    default=1,
    help="历史窗口与预测窗口之间的间隔步数（15min/步；gap_len=1 表示 30min 间隔）",
)
parser.add_argument("--pred-len", type=int, default=16, help="预测窗口长度")
parser.add_argument(
    "--save-split",
    action="store_true",
    help="额外导出 train/test 两份数据（按 date_time 的月份划分）",
)
parser.add_argument(
    "--test-months",
    nargs="+",
    default=["2026-04", "2026-05"],
    help="测试集月份列表，例如：2026-04 2026-05",
)
args = parser.parse_known_args()[0]

read_dir = args.input_dir
save_dir = args.output_dir
ensure_dir(save_dir)

file_list = sorted([x for x in os.listdir(read_dir) if x.lower().endswith(".csv")])
seq_len = args.seq_len
gap_len = args.gap_len
pred_len = args.pred_len


def squeeze_gap(sample, seq_len, gap_len, pred_len):
    """
    将一个滑窗样本中的 gap 部分去掉。

    sample: 长度为 seq_len + gap_len + pred_len 的 DataFrame
    返回: 长度为 seq_len + pred_len 的 DataFrame
    """
    sample_seq = sample[:seq_len]
    sample_pred = sample[seq_len + gap_len:]
    new_sample = pd.concat([sample_seq, sample_pred], axis=0)
    assert new_sample.shape[0] == seq_len + pred_len
    return new_sample


def run_one_station(file):
    print(f"[station] {file}")

    # 单站输入与输出路径
    file_read_path = os.path.join(read_dir, file)
    station_name = os.path.splitext(file)[0]
    file_save_path = os.path.join(save_dir, f"{station_name}.pkl")

    df = pd.read_csv(file_read_path)

    # mask 逻辑：
    # - 如果原数据已有 mask（例如由限电分类生成），仍需将 power 为 NaN 的位置 mask 掉
    # - 如果原数据没有 mask，则以 power 非空作为 mask
    if 'mask' in df.columns:
        df['mask'] = pd.notna(df['power']).astype(int) * df['mask']
    else:
        df['mask'] = pd.notna(df['power']).astype(int)

    sample_list = []
    train_sample_list = []
    test_sample_list = []
    sample_len = seq_len + gap_len + pred_len

    # 滑窗构造样本：
    # - 每个样本先取 (seq_len + gap_len + pred_len) 行
    # - 再通过 squeeze_gap 去掉 gap 部分，得到 (seq_len + pred_len) 行
    for i in range(df.shape[0] - sample_len + 1):
        sample = df.iloc[i:i + sample_len].copy()
        sample.reset_index(drop=True, inplace=True)
        new_sample = squeeze_gap(sample, seq_len, gap_len, pred_len)
        sample_list.append(new_sample)

        if args.save_split and "date_time" in sample.columns:
            pred_start_dt = str(sample.loc[seq_len + gap_len, "date_time"])
            if pred_start_dt[:len("2026-04")] in set(args.test_months):
                test_sample_list.append(new_sample)
            else:
                train_sample_list.append(new_sample)

    if not sample_list:
        print(f"[skip] empty samples: {file}")
        return

    df_all = pd.concat(sample_list, axis=0, ignore_index=True)
    with open(file_save_path, 'wb') as f:
        pkl.dump(df_all, f)

    if args.save_split:
        split_dir = os.path.join(save_dir, "split")
        ensure_dir(split_dir)

        if not train_sample_list:
            df_train = df_all.iloc[0:0].copy()
        else:
            df_train = pd.concat(train_sample_list, axis=0, ignore_index=True)

        if not test_sample_list:
            df_test = df_all.iloc[0:0].copy()
        else:
            df_test = pd.concat(test_sample_list, axis=0, ignore_index=True)

        with open(os.path.join(split_dir, f"{station_name}_train.pkl"), "wb") as f:
            pkl.dump(df_train, f)
        with open(os.path.join(split_dir, f"{station_name}_test.pkl"), "wb") as f:
            pkl.dump(df_test, f)



for file in tqdm(file_list, position=0, leave=False):
    run_one_station(file)
