"""
合并风场数据（功率 + 实测风速 + ECMWF 预报特征）。

输入（每个站点一个 csv）：
- 功率数据：/mnt/md0/zhouyunqi/HuaFeng/data/s1_clean_data/power_ky/{站点}.csv
- 风速数据：/mnt/md0/zhouyunqi/HuaFeng/data/s1_clean_data/wind_speed/{站点}.csv
- ECMWF 风速预报特征：/mnt/md0/zhouyunqi/HuaFeng/data/s2_forecast_csv/wind/{站点}.csv
- ECMWF 温度预报特征：/mnt/md0/zhouyunqi/HuaFeng/data/s2_forecast_csv/temperature/{站点}.csv

处理逻辑保持不变：
- ECMWF 文件按 block_size=408 切块，每块只取 [16+96 : 16+96+96] 的 96 行（对应某一天的指定时间段）
- 将风速/温度特征横向拼接后，与功率、实测风速按 date_time 左连接

输出：
- /mnt/md0/zhouyunqi/HuaFeng/data/s3_dataset_pre/{站点}.csv
"""

import os
import argparse
from datetime import timedelta, datetime
from pathlib import Path
from multiprocessing import Pool

import pandas as pd

FIFTEEN_MINUTE = timedelta(minutes=15)
ONE_DAY = timedelta(days=1)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)


def run_one_station(station_name):
    file = f"{station_name}.csv"
    save_path = os.path.join(args.output_dir, file)
    power_path = os.path.join(args.power_dir, file)
    wind_path = os.path.join(args.wind_dir, file)
    EC_path1 = os.path.join(args.ec_wind_dir, file)
    EC_path2 = os.path.join(args.ec_temperature_dir, file)

    # 输入不齐则跳过（不产生输出）
    if (
        not os.path.exists(power_path)
        or not os.path.exists(wind_path)
        or not os.path.exists(EC_path1)
        or not os.path.exists(EC_path2)
    ):
        print(f"[skip] missing input for station file: {file}")
        return

    # 读取功率和实测风速数据
    df_power = pd.read_csv(power_path)[['date_time', 'power']]
    df_wind = pd.read_csv(wind_path)

    # 读取 ECMWF 预报数据（风速 + 温度），并做与原脚本一致的裁剪
    df_EC1 = pd.read_csv(EC_path1)
    df_EC2 = pd.read_csv(EC_path2)
    df_EC2.drop(columns=['forecast_date', 'date_time'], inplace=True)
    block_size = 408
    assert df_EC1.shape[0] == df_EC2.shape[0]
    assert df_EC1.shape[0] % block_size == 0
    assert df_EC2.shape[0] % block_size == 0

    # ECMWF 文件由多个 block 组成；每个 block 取固定 96 行作为当天样本
    df_oneday = []
    for i in range(df_EC1.shape[0] // block_size):
        block1 = df_EC1[i * block_size:(i + 1) * block_size]
        block2 = df_EC2[i * block_size:(i + 1) * block_size]
        block = pd.concat([block1, block2], axis=1)
        df_oneday.append(block[16 + 96:16 + 96 + 96])
    df_feature = pd.concat(df_oneday, axis=0).reset_index(drop=True)

    # 按 date_time 合并：ECMWF 特征 LEFT JOIN 功率、实测风速（合并后可能出现 NaN）
    df = pd.merge(df_feature, df_power, on='date_time', how='left')
    df = pd.merge(df, df_wind, on='date_time', how='left')
    df.reset_index(drop=True, inplace=True)
    df.to_csv(save_path, index=False)


parser = argparse.ArgumentParser()
parser.add_argument("--station", type=str, default="all")
parser.add_argument("--n-workers", type=int, default=16)
parser.add_argument("--stations-file", type=str, default="/mnt/md0/zhouyunqi/HuaFeng/data/stations.csv")
parser.add_argument("--power-dir", type=str, default="/mnt/md0/zhouyunqi/HuaFeng/data/s1_clean_data/power_ky")
parser.add_argument("--wind-dir", type=str, default="/mnt/md0/zhouyunqi/HuaFeng/data/s1_clean_data/wind_speed")
parser.add_argument("--ec-wind-dir", type=str, default="/mnt/md0/zhouyunqi/HuaFeng/data/s2_forecast_csv/wind")
parser.add_argument(
    "--ec-temperature-dir", type=str, default="/mnt/md0/zhouyunqi/HuaFeng/data/s2_forecast_csv/temperature"
)
parser.add_argument("--output-dir", type=str, default="/mnt/md0/zhouyunqi/HuaFeng/data/s3_dataset_pre")
args = parser.parse_known_args()[0]

ensure_dir(args.output_dir)

stations_file = Path(args.stations_file)
if not stations_file.exists():
    raise FileNotFoundError(f"stations file not found: {stations_file}")
df_stations = pd.read_csv(stations_file)
if "station_id" not in df_stations.columns:
    raise ValueError("stations file missing column: station_id")
station_list = [str(x) for x in df_stations["station_id"].tolist()]

p = Pool(args.n_workers)
for station in station_list:
    if args.station != "all" and station != args.station:
        continue
    p.apply_async(run_one_station, args=(station,))
p.close()
p.join()
