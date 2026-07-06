"""
风电 XGBoost 训练脚本（CDQ 数据集）。

功能概述
- 输入：按“场站-单文件”的方式读取数据集目录下的 <station>.pkl；读取场站配置 stations.csv 获取站点列表与装机/额定功率（用于评价指标归一化）。
- 处理：对每个场站、每个 forecast_index（0~15）训练一个 XGBoost 回归模型；特征构建与样本切片逻辑保持原实现。
- 输出：模型与预测结果分别写入 outputs/model 与 outputs/results 两个目录。
"""

import argparse
import os
import pickle as pkl
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb

warnings.filterwarnings('ignore')


def ensure_dir(path: str | Path) -> None:
    """
    创建目录（若已存在则忽略）。

    说明：用于统一处理输出目录的创建，避免因目录不存在导致写文件失败。
    """
    Path(path).mkdir(parents=True, exist_ok=True)


def CR_relative(pred: np.ndarray, label: np.ndarray, Ymax: float = 100.0) -> float:
    """
    相对考核指标（CRR）。

    - 分母使用 max(label, 0.2*Ymax) 做保护，避免低功率时误差比值过大。
    - 返回值通常在 (-inf, 1]，越接近 1 越好。
    """
    tmp = label.copy()
    tmp[label < 0.2 * Ymax] = 0.2 * Ymax
    tmp = ((pred - label) / tmp) ** 2
    tmp = tmp[~np.isnan(tmp)]
    cr = 1 - np.sqrt(np.mean(tmp))
    return float(cr)


def CR_absolute(pred: np.ndarray, label: np.ndarray, Ymax: float = 100.0) -> float:
    """
    绝对考核指标（CRA）。

    - 使用 Ymax（通常为场站容量）进行归一化。
    - 返回值通常在 (-inf, 1]，越接近 1 越好。
    """
    tmp = ((pred - label) / Ymax) ** 2
    tmp = tmp[~np.isnan(tmp)]
    cr = 1 - np.sqrt(np.mean(tmp))
    return float(cr)


def load_station_powers(stations_file: str | Path) -> dict[str, float]:
    """
    从 stations.csv 读取场站容量（ymax）。

    - 必需列：station_id
    - 容量列：优先使用 ymax；否则依次尝试 capacity_mw / capacity / y_max
    """
    df = pd.read_csv(stations_file)
    if "station_id" not in df.columns:
        raise ValueError(f"stations_file missing required column: station_id, got={list(df.columns)}")

    cap_col = None
    for c in ["ymax", "capacity_mw", "capacity", "y_max"]:
        if c in df.columns:
            cap_col = c
            break
    if cap_col is None:
        raise ValueError(
            f"stations_file missing capacity column. Expected one of: ymax/capacity_mw/capacity/y_max, got={list(df.columns)}"
        )

    station_powers: dict[str, float] = {}
    for _, row in df.iterrows():
        name = str(row["station_id"])
        cap = row[cap_col]
        if pd.isna(cap):
            continue
        station_powers[name] = float(cap)
    return station_powers


parser = argparse.ArgumentParser()
parser.add_argument("--gpu_id", type=str, default="7")
parser.add_argument("--station", type=str, default="all")
parser.add_argument("--forecast_index", type=str, default="all")
parser.add_argument("--data_dir", type=str, default="/mnt/md0/zhouyunqi/HuaFeng/data/s4_dataset_CDQ")
parser.add_argument("--stations_file", type=str, default="/mnt/md0/zhouyunqi/HuaFeng/data/stations.csv")
parser.add_argument("--output_root", type=str, default="/mnt/md0/zhouyunqi/HuaFeng/outputs")
args = parser.parse_known_args()[0]

data_dir = Path(args.data_dir)
stations_file = Path(args.stations_file)
output_root = Path(args.output_root)

save_root1 = output_root / "model"
save_root2 = output_root / "results"
ensure_dir(save_root1)
ensure_dir(save_root2)

summary_rows: list[dict[str, object]] = []
summary_path = save_root2 / "summary.csv"


sample_size = 32
ec_start_index, ec_end_index = 0, 32  # ECMWF 特征共 32 个时刻（对应 sample_size=32）
s_start_index, s_end_index = 0, 16  # 场站历史特征取前 16 个时刻

valid_month = []
test_month = ["2026-04"]
train_before_month = "2026-04"
skip_after_month = "2026-04"

station_powers = load_station_powers(stations_file)

print(
    "running on dataset:",
    str(data_dir),
    "stations_file:",
    str(stations_file),
    "output_root:",
    str(output_root),
    "ec_index:",
    (ec_start_index, ec_end_index),
    "station_index:",
    (s_start_index, s_end_index),
)

# 逐场站训练（每个场站会训练 16 个 forecast_index 模型）
for station in sorted(list(station_powers.keys())):
    if args.station != "all" and station != args.station:
        continue
    pkl_path = data_dir / f"{station}.pkl"
    if not pkl_path.exists():
        continue
    ymax = station_powers[station]
    with open(pkl_path, "rb") as f:
        df = pkl.load(f)
    assert df.shape[0] % sample_size == 0

    forecast_indices = range(16) if args.forecast_index == "all" else [int(args.forecast_index)]
    for forecast_index in forecast_indices:
        # if forecast_index != 15:
        #     continue
        # 取 ECMWF 特征矩阵（仅保留 wind 相关字段，并过滤掉非目标网格/索引）
        feature_cols = [x for x in df.columns if x.endswith('wind') or x[-9:-3] == '_wind_']
        feature_cols = [x for x in feature_cols if x[-3:] in ['ind', '1_1', '1_2', '2_1', '2_2']]
        df_EC = df[feature_cols]

        # 额外构造风速模长特征：sqrt(U^2 + V^2) 以及其二次/三次项
        feature_add = {}
        for U_wind in sorted([x for x in list(df_EC.columns) if 'U' in x]):
            V_wind = U_wind.split('_')
            if V_wind[-1] == 'wind':
                wind_name = V_wind[0] + '_center'
            else:
                wind_name = V_wind[0] + '_' + V_wind[-2] + '_' + V_wind[-1]
            V_wind[2] = 'V'
            V_wind = '_'.join(V_wind)

            pred_wind = np.sqrt(df_EC[U_wind].to_numpy() ** 2 + df_EC[V_wind].to_numpy() ** 2)
            feature_add[wind_name] = pred_wind
            feature_add[wind_name + '**2'] = pred_wind ** 2
            feature_add[wind_name + '**3'] = pred_wind ** 3

        df_EC.reset_index(inplace=True, drop=True)
        df_EC = pd.concat([df_EC, pd.DataFrame(feature_add)], axis=1)
        feature_cols.extend(list(feature_add.keys()))

        sample_list_EC, sample_list_station = [], []
        sample_list_target, part_list, sample_list_pred_time = [], [], []

        # 样本切片：
        # - 每 32 行作为一个样本（包含 0~31 时刻）
        # - 目标点在第 16 + forecast_index 时刻
        for i in range(df.shape[0] // sample_size):
            sample = df[i * sample_size:(i + 1) * sample_size]
            sample_EC = df_EC[i * sample_size:(i + 1) * sample_size]
            sample.reset_index(drop=True, inplace=True)
            sample_EC.reset_index(drop=True, inplace=True)

            target_dt = sample.loc[16 + forecast_index, "date_time"]
            target_month = str(target_dt)[:len("2024-11")]

            if target_month < train_before_month:
                # 训练集：仅使用 2026-04 之前（不含 2026-04）的样本
                # 目标点要求 mask==1（可用）
                if sample.loc[16 + forecast_index, "mask"] == 0:
                    continue
                part_list.append(0)
            elif target_month in test_month:
                # 测试集：仅使用 2026-04 的样本
                # 目标点要求 label 非空
                if pd.isna(sample.loc[16 + forecast_index, "power"]):
                    continue
                part_list.append(2)
            else:
                # 丢弃：2026-05 及之后（或其他不在 train/test 规则内的月份）不参与训练也不参与测试
                continue

            sample_list_EC.append(sample_EC.values[ec_start_index:ec_end_index].reshape(1, -1))
            sample_list_station.append(
                sample[["power", "wind_speed"]][s_start_index: s_end_index].values.reshape(1, -1))
            sample_list_target.append(sample.loc[16 + forecast_index, "power"])
            sample_list_pred_time.append(target_dt)

        if not sample_list_EC or not sample_list_station:
            print(f"[skip] empty samples for station={station}, forecast_index={forecast_index}")
            continue
        EC_feature = np.concatenate(sample_list_EC, axis=0)
        station_feature = np.concatenate(sample_list_station, axis=0)

        X = np.concatenate([EC_feature, station_feature], axis=1)
        Y = np.array(sample_list_target).reshape(-1, 1)
        part = np.array(part_list).reshape(-1)
        pred_time = np.array(sample_list_pred_time).reshape(-1, 1)

        # 划分训练集/测试集
        X_train = X[part == 0]
        Y_train = Y[part == 0]
        # train_pred_time = pred_time[part == 0]
        # X_valid = X[part == 1]
        # Y_valid = Y[part == 1]
        # valid_pred_time = pred_time[part == 1]
        X_test = X[part == 2]
        Y_test = Y[part == 2]
        test_pred_time = pred_time[part == 2]
        # print(X_train.shape, X_test.shape)

        # XGBoost 的输入矩阵（稀疏/稠密都可），这里使用 numpy 拼接后的稠密特征
        data_train = xgb.DMatrix(X_train, label=Y_train)

        # 训练参数（与原脚本保持一致）
        params = {
            "device": "cpu" if args.gpu_id.lower() == "cpu" else f"cuda:{args.gpu_id}",
            'booster': 'gbtree',
            'objective': 'reg:absoluteerror',
            # 'objective': 'reg:squarederror',
            # 'objective': 'reg:pseudohubererror',
            # 'huber_slope': 1.5,  # 搭配pseudohubererror
            'nthread': 40,
            'max_depth': 5,  # 树的最大深度
            'learning_rate': 0.02,  # 学习率
            'subsample': 0.5,  # 训练数据的子采样比例
            'colsample_bytree': 0.5,  # 列采样比例
            'gamma': 0.2,  # 控制树复杂度的参数
            'min_child_weight': 1.5,  # 节点分裂所需最小样本权重和
            'lambda': 10,  # L2正则化项
            'alpha': 10  # L1正则化项
        }

        # 训练单步长模型
        model = xgb.train(params, data_train, num_boost_round=1000)
        save_dir = Path(save_root1) / f"{station}" / "CDQ_xgb_ky"
        ensure_dir(save_dir)
        pkl.dump(model, open(save_dir / f"model_{forecast_index}.dat", "wb"))

        # 验证集
        # data_valid = xgb.DMatrix(X_valid)
        # Y_pred = model.predict(data_valid)
        # Y_pred = np.clip(Y_pred, 0, None)

        # 测试集
        data_test = xgb.DMatrix(X_test)
        Y_pred = model.predict(data_test)
        Y_pred = np.clip(Y_pred, 0, None)
        Y_pred, Y_test, test_pred_time = Y_pred.reshape(-1), Y_test.reshape(-1), test_pred_time.reshape(-1)

        # 保存预测序列：date_time / pred / label
        data = pd.DataFrame({'date_time': test_pred_time, 'pred': Y_pred, 'label': Y_test})
        data.dropna(inplace=True)

        Y_pred = data['pred'].values.reshape(-1)
        Y_test = data['label'].values.reshape(-1)

        cra_model = round(CR_absolute(Y_pred, Y_test, ymax), 4)
        crr_model = round(CR_relative(Y_pred, Y_test, ymax), 4)

        # print(f'{station}  cra_model:{cra_model} crr_model:{crr_model} {X_train.shape[0]} {X_test.shape[0]}')
        print(station, forecast_index, cra_model, crr_model)
        summary_rows.append(
            {
                "station": station,
                "forecast_index": int(forecast_index),
                "cra": float(cra_model),
                "crr": float(crr_model),
            }
        )

        results_dir = Path(save_root2) / f"xgboost_{station}"
        ensure_dir(results_dir)
        data.to_csv(results_dir / f"{station}_{forecast_index}.csv", index=False)

if summary_rows:
    pd.DataFrame(summary_rows).sort_values(["station", "forecast_index"]).to_csv(summary_path, index=False)
