import os
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

warnings.filterwarnings('ignore')
OUTPUT_BASE_DIR = "/mnt/md0/zhouyunqi/HuaFeng/data/s1_clean_data"
POWER_DIR = os.path.join(OUTPUT_BASE_DIR, "power_ky")
WIND_DIR = os.path.join(OUTPUT_BASE_DIR, "wind_speed")
os.makedirs(POWER_DIR, exist_ok=True)
os.makedirs(WIND_DIR, exist_ok=True)


def read_huafeng_wind_station_csv(file_path: str) -> pd.DataFrame:
    """
    读取华风场站原始CSV，并整理出统一字段:
    - date_time: 时间戳（datetime64[ns]）
    - power: 功率（float）
    - wind_speed: 平均风速（float）

    清洗规则（按用户要求）:
    1) 只保留整分数据，精确到秒：秒必须为 0（如 00:00:00 可保留，00:03:30 需剔除）
    2) 同一时刻有多条记录时，保留第一条（keep='first'）
    3) 功率 clip 到 >= 0；风速 > 30 置 NaN（沿用原脚本风电站点逻辑）

    15min 重采样规则:
    - 目标时间序列为整 15 分钟（00/15/30/45），且秒为 0
    - 不做插值：仅将原始数据对齐到 15min 网格，缺失时间点保持为 NaN
    """
    df = pd.read_csv(file_path)
    df = df.rename(
        columns={
            "timestamp": "date_time",
            "平均风速": "wind_speed",
            "可用功率": "power",
        }
    )

    df["date_time"] = pd.to_datetime(df["date_time"])

    df = df[df["date_time"].dt.second == 0]
    df = df[["date_time", "power", "wind_speed"]]

    df["power"] = pd.to_numeric(df["power"], errors="coerce").clip(lower=0) / 1000.0
    df["wind_speed"] = pd.to_numeric(df["wind_speed"], errors="coerce")

    df.drop_duplicates(inplace=True, subset=["date_time"], keep="first")

    df.loc[df["wind_speed"] > 30, "wind_speed"] = np.nan
    df = df.sort_values(by="date_time")

    df = df.set_index("date_time")
    start = df.index.min().floor("15T")
    end = df.index.max().ceil("15T")
    target_index = pd.date_range(start=start, end=end, freq="15T")

    df = df.reindex(target_index)
    df.index.name = "date_time"

    df = df.reset_index()
    return df


def station_name_from_file(file_path: str) -> str:
    """
    从文件名中推导场站名。
    例如: 日照五莲风电场.csv -> 日照五莲
    """
    name = Path(file_path).stem
    return name.replace("风电场", "")


def main() -> None:
    """
    从指定两份原始CSV读取数据，输出两类清洗结果:
    - power_ky/站点.csv: date_time, power
    - wind_speed/站点.csv: date_time, wind_speed

    输出路径固定为: /mnt/md0/zhouyunqi/HuaFeng/data/s1_clean_data
    """
    input_files = [
        "/mnt/md0/Power_Forecast_Data/source_data/华风/日照五莲/日照五莲风电场.csv",
        "/mnt/md0/Power_Forecast_Data/source_data/华风/威海新区/威海新区风电场.csv",
    ]

    for file_path in input_files:
        station = station_name_from_file(file_path)
        print(f"processing {station}...")

        df_all = read_huafeng_wind_station_csv(file_path)

        df_power = df_all[["date_time", "power"]]
        df_power.to_csv(os.path.join(POWER_DIR, f"{station}.csv"), index=False)

        df_wind = df_all[["date_time", "wind_speed"]]
        df_wind.to_csv(os.path.join(WIND_DIR, f"{station}.csv"), index=False)

        print(f"{station} done! rows={len(df_all)}")


if __name__ == "__main__":
    main()
