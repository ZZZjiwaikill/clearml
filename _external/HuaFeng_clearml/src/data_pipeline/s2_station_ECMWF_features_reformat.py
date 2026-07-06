import os
import argparse
from datetime import datetime
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from tqdm import tqdm
from multiprocessing import Pool

PROJECT_ROOT = Path(__file__).resolve().parents[2]

"""
将区域 ECMWF 格点预报（npy）转换为站点级特征（csv）。

核心思路：
1) 每个预报起报时刻（forecast_date）对应一个 npy 文件，里面按时间步存储格点场。
2) 对每个场站经纬度：
   - 基础特征（如 10m U/V 风）对最近 2x2 格点做双线性插值，得到整点值序列；
   - 同时取插值网格周围 4x4 的格点原始值，作为“周围格点特征”；
   - 将整点值序列线性插值到 15min 分辨率，输出 408 行（0~102h）。

由于输入的场站均为山东场站，属于"华东华中地区"，本脚本默认读取：
  /mnt/md0/Power_Forecast_Data/EC_regional/华东华中区域/forecast_wind_npy_0.1
  /mnt/md0/Power_Forecast_Data/EC_regional/华东华中区域/forecast_temperature_npy_0.1

站点信息来自：
  <项目根目录>/data/stations.csv
功率数据来自：
  <项目根目录>/data/s1_clean_data/power_ky

并将每个站点输出到：
  <项目根目录>/data/s2_forecast_csv/wind/<站点>.csv
  <项目根目录>/data/s2_forecast_csv/temperature/<站点>.csv
"""


def bilinear_literpolation(lat1, lat2, lon1, lon2, lon, lat, data):
    """
    双线性插值：根据 2x2 格点值插值出 (lat, lon) 点的值。

    data 的布局为：
      [[q11, q12],
       [q21, q22]]
    其中第一维对应纬向（lat1/lat2），第二维对应经向（lon1/lon2）。
    """
    x_x1 = (lon - lon1) / (lon2 - lon1)
    x2_x = (lon2 - lon) / (lon2 - lon1)

    y_y2 = (lat - lat1) / (lat2 - lat1)
    y3_y = (lat2 - lat) / (lat2 - lat1)

    result = x2_x * y3_y * data[1][0] + x_x1 * y3_y * data[1][1] + \
             x_x1 * y_y2 * data[0][1] + x2_x * y_y2 * data[0][0]

    return float(result)


def linear_interpolation(data):
    """
    将整点/逐小时序列插值为 15min 序列。

    TIME_LIST 的单位是“小时”，间隔在 90h 之后变为 3h，因此这里用
    points = (dt_hour) * 4 统一生成 15min 点数。
    """
    features = [0.0 for _ in range(102 * 4)]
    index = 0

    for i in range(len(TIME_LIST) - 1):
        points = (TIME_LIST[i + 1] - TIME_LIST[i]) * 4
        data_start = data[i]
        data_step = (data[i + 1] - data[i]) / points

        for j in range(points):
            features[index] = data_start + data_step * j
            index += 1

    return features


def linear_interpolation_radiation(data):
    """
    辐照度类特征的插值。

    ECMWF 辐照度在每个时刻通常存的是“累计量”，因此先估算整点“瞬时辐照度”
    再做线性插值到 15min。
    """
    features = [0.0 for _ in range(102 * 4)]
    index = 0

    # 辐照度特征每个时刻的记录为累计值，所以需要构造一个新的data，内容为整点瞬时辐照度，
    data_instanct = []
    for i in range(len(TIME_LIST)):
        if i == 0:
            data_instanct.append(0.0)
        # 最后一个时间点的处理不准确，但一般不会用到
        elif i == len(TIME_LIST) - 1:
            data_instanct.append((data[i] - data[i - 1]) / (TIME_LIST[i] - TIME_LIST[i - 1]) / 3600)
        else:
            t1 = (TIME_LIST[i] - TIME_LIST[i - 1])
            t2 = (TIME_LIST[i + 1] - TIME_LIST[i])
            c1 = t2 / (t1 + t2)
            c2 = t1 / (t1 + t2)
            average_v_before = (data[i] - data[i - 1]) / t1 / 3600
            average_v_after = (data[i + 1] - data[i]) / t2 / 3600
            data_instanct.append((average_v_before * c1 + average_v_after * c2))

    for i in range(len(TIME_LIST) - 1):
        points = (TIME_LIST[i + 1] - TIME_LIST[i]) * 4
        data_start = data_instanct[i]
        data_step = (data_instanct[i + 1] - data_instanct[i]) / points

        for j in range(points):
            features[index] = data_start + data_step * j
            index += 1

    return features


def _find_surrounding_grid(lat_list, lon_list, lat, lon):
    """
    在 ECMWF 格点网格中定位站点所在的 2x2 包围格点，以及对应的索引。

    返回：
      index_x, index_y, lat1, lat2, lon1, lon2
    其中 (index_x, index_y) 表示左上角格点索引（配合原脚本的访问方式）。
    """
    index_x = None
    index_y = None
    lat1 = lat2 = lon1 = lon2 = None

    for i in range(len(lat_list) - 1):
        if lat > lat_list[i + 1]:
            lat2 = lat_list[i]
            lat1 = lat_list[i + 1]
            index_x = i
            break

    for j in range(len(lon_list) - 1):
        if lon < lon_list[j + 1]:
            lon1 = lon_list[j]
            lon2 = lon_list[j + 1]
            index_y = j
            break

    if index_x is None or index_y is None:
        raise ValueError(f"station ({lat}, {lon}) out of grid range")

    return index_x, index_y, lat1, lat2, lon1, lon2


def _extract_feature_dict_one_data(npy_data, lat, lon, feature_list, origin_name_dict):
    """
    从一个 npy_data（一个 data_type）中提取指定特征，返回 {feature_name: 15min 序列}。
    """
    lat_list, lon_list = npy_data["latitude"][:, 0], npy_data["longitude"][0, :]
    index_x, index_y, lat1, lat2, lon1, lon2 = _find_surrounding_grid(lat_list, lon_list, lat, lon)

    feature_dict = {}
    for feature_name in feature_list:
        values = []

        if feature_name in origin_name_dict:
            for grb in npy_data[origin_name_dict[feature_name]]:
                now_feature = [
                    [grb[index_x, index_y], grb[index_x, index_y + 1]],
                    [grb[index_x + 1, index_y], grb[index_x + 1, index_y + 1]],
                ]
                values.append(bilinear_literpolation(lat1, lat2, lon1, lon2, lon, lat, now_feature))
        else:
            i = int(feature_name.split("_")[-2])
            j = int(feature_name.split("_")[-1])
            start_x = index_x - 1
            start_y = index_y - 1
            ori_name = feature_name[:-4]
            for grb in npy_data[origin_name_dict[ori_name]]:
                values.append(grb[start_x + i, start_y + j])

        if "radiation" in feature_name:
            feature_dict[feature_name] = linear_interpolation_radiation(values)
        else:
            feature_dict[feature_name] = linear_interpolation(values)

    return feature_dict


def _write_one_forecast_block(fd, start_time, feature_dict, feature_order):
    """
    将一个 forecast_date 的特征块写入 csv。

    每个 forecast_date 输出 408 行，date_time 以 15min 递增。
    """
    grb_time = start_time
    n_rows = len(feature_dict[feature_order[0]])
    for i in range(n_rows):
        row = [f"{start_time}", f"{grb_time}"]
        for feat in feature_order:
            row.append(str(feature_dict[feat][i]))
        fd.write(",".join(row) + "\n")
        grb_time = grb_time + FIFTEEN_MINUTE


def run_one_station(
    wind_dir,
    temperature_dir,
    wind_target_dir,
    temperature_target_dir,
    name,
    wind_feature_order,
    temperature_feature_order,
    feature_name_origin,
    first_day,
    final_day,
):
    """
    处理单个站点：
    - 遍历 wind npy 的目录结构（year/month/file）
    - 同步读取对应的 temperature npy（同名文件）
    - 分别写出 wind 特征 csv 与 temperature 特征 csv
    """
    print(f"running station {name}")
    os.makedirs(wind_target_dir, exist_ok=True)
    os.makedirs(temperature_target_dir, exist_ok=True)
    wind_out_path = os.path.join(wind_target_dir, f"{name}.csv")
    temperature_out_path = os.path.join(temperature_target_dir, f"{name}.csv")

    lat, lon = location_dict[name]

    with (
        open(wind_out_path, "w") as wind_fd,
        open(temperature_out_path, "w") as temperature_fd,
    ):
        wind_header = ["forecast_date", "date_time"] + list(wind_feature_order)
        temperature_header = ["forecast_date", "date_time"] + list(temperature_feature_order)
        wind_fd.write(",".join(wind_header) + "\n")
        temperature_fd.write(",".join(temperature_header) + "\n")

        year_list = sorted(os.listdir(wind_dir))
        for year in tqdm(year_list, position=1, leave=False):
            year_path = os.path.join(wind_dir, year)
            if not os.path.isdir(year_path):
                continue
            month_list = sorted(os.listdir(year_path))

            for month in tqdm(month_list, position=2, leave=False):
                month_path = os.path.join(year_path, month)
                if not os.path.isdir(month_path):
                    continue
                file_list = sorted(os.listdir(month_path))

                for file_name in tqdm(file_list, position=3, leave=False):
                    today = file_name[:10]
                    today_dt = datetime.strptime(today, "%Y-%m-%d")
                    first_dt = datetime.strptime(first_day[name], "%Y-%m-%d")
                    final_dt = datetime.strptime(final_day[name], "%Y-%m-%d")
                    if today_dt < first_dt or today_dt > final_dt:
                        continue

                    wind_path = os.path.join(wind_dir, year, month, file_name)
                    temp_path = os.path.join(temperature_dir, year, month, file_name)
                    if not os.path.exists(wind_path) or not os.path.exists(temp_path):
                        continue

                    wind_data = np.load(wind_path, allow_pickle=True).item()
                    temp_data = np.load(temp_path, allow_pickle=True).item()
                    start_time = datetime.strptime(file_name.split(".")[0], "%Y-%m-%d %H:%M:%S")

                    wind_feature_dict = _extract_feature_dict_one_data(
                        wind_data, lat, lon, WIND_FEATURE_LIST, feature_name_origin
                    )
                    temp_feature_dict = _extract_feature_dict_one_data(
                        temp_data, lat, lon, TEMPERATURE_FEATURE_LIST, feature_name_origin
                    )
                    _write_one_forecast_block(wind_fd, start_time, wind_feature_dict, wind_feature_order)
                    _write_one_forecast_block(
                        temperature_fd, start_time, temp_feature_dict, temperature_feature_order
                    )
                    wind_fd.flush()
                    temperature_fd.flush()


EIGHT_HOUR = timedelta(hours=8)
FIFTEEN_MINUTE = timedelta(minutes=15)
TIME_LIST = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9,
             10, 11, 12, 13, 14, 15, 16, 17, 18, 19,
             20, 21, 22, 23, 24, 25, 26, 27, 28, 29,
             30, 31, 32, 33, 34, 35, 36, 37, 38, 39,
             40, 41, 42, 43, 44, 45, 46, 47, 48, 49,
             50, 51, 52, 53, 54, 55, 56, 57, 58, 59,
             60, 61, 62, 63, 64, 65, 66, 67, 68, 69,
             70, 71, 72, 73, 74, 75, 76, 77, 78, 79,
             80, 81, 82, 83, 84, 85, 86, 87, 88, 89,
             90, 93, 96, 99, 102]

WIND_BASE_FEATURES = [
    "10_metre_U_wind",
    "10_metre_V_wind",
    "200_metre_U_wind",
    "200_metre_V_wind",
    "100_metre_U_wind",
    "100_metre_V_wind",
]
TEMPERATURE_BASE_FEATURES = ["2_metre_temperature"]

FEATURE_NAME_ORIGIN = {
    "10_metre_U_wind": "10 metre U wind component",
    "10_metre_V_wind": "10 metre V wind component",
    "200_metre_U_wind": "200 metre U wind component",
    "200_metre_V_wind": "200 metre V wind component",
    "100_metre_U_wind": "100 metre U wind component",
    "100_metre_V_wind": "100 metre V wind component",
    "2_metre_temperature": "2 metre temperature",
}


def _augment_grid_features(base_features, grid_size):
    """
    将基础特征扩展为：基础值 + 周围 grid_size x grid_size 的格点原始值。

    命名约定沿用原脚本：{feat}_{i}_{j}，其中 i/j 均从 0 开始。
    """
    augmented = list(base_features)
    for i in range(grid_size):
        for j in range(grid_size):
            for feat in base_features:
                augmented.append(f"{feat}_{i}_{j}")
    return augmented


parser = argparse.ArgumentParser()
parser.add_argument("--region", type=str, default="华东华中区域")
parser.add_argument("--station", type=str, default="all")
parser.add_argument("--n-workers", type=int, default=16)
parser.add_argument("--input-region-root", type=str, default="/mnt/md0/Power_Forecast_Data/EC_regional")
parser.add_argument("--stations-file", type=str, default=str(PROJECT_ROOT / "data" / "stations.csv"))
parser.add_argument("--power-dir", type=str, default=str(PROJECT_ROOT / "data" / "s1_clean_data" / "power_ky"))
parser.add_argument(
    "--output-wind-dir", type=str, default=str(PROJECT_ROOT / "data" / "s2_forecast_csv" / "wind")
)
parser.add_argument(
    "--output-temperature-dir", type=str, default=str(PROJECT_ROOT / "data" / "s2_forecast_csv" / "temperature")
)
args = parser.parse_known_args()[0]

stations_file = Path(args.stations_file)
if not stations_file.exists():
    raise FileNotFoundError(f"stations file not found: {stations_file}")

df_stations = pd.read_csv(stations_file)
required_cols = {"station_id", "longitude", "latitude"}
if not required_cols.issubset(set(df_stations.columns)):
    raise ValueError(f"stations.csv missing required columns: {sorted(required_cols)}")

location_dict = {}
for _, row in df_stations.iterrows():
    name = str(row["station_id"])
    location_dict[name] = (float(row["latitude"]), float(row["longitude"]))

grid_size = 4
WIND_FEATURE_LIST = _augment_grid_features(WIND_BASE_FEATURES, grid_size)
TEMPERATURE_FEATURE_LIST = _augment_grid_features(TEMPERATURE_BASE_FEATURES, grid_size)

power_dir = Path(args.power_dir)
ensure_stations = []
first_day = {}
final_day = {}
for name in sorted(list(location_dict.keys())):
    if args.station != "all" and name != args.station:
        continue
    power_file = power_dir / f"{name}.csv"
    if not power_file.exists():
        print(f"[skip] power csv missing for station: {name}")
        continue

    df_power = pd.read_csv(power_file).sort_values("date_time").reset_index(drop=True)
    num_rows = len(df_power)
    first_date_time = pd.to_datetime(df_power.loc[0, "date_time"]).date() - timedelta(days=2)
    final_date_time = pd.to_datetime(df_power.loc[num_rows - 1, "date_time"]).date() - timedelta(days=2)
    first_day[name] = str(first_date_time)
    final_day[name] = str(final_date_time)
    ensure_stations.append(name)

wind_dir = os.path.join(args.input_region_root, args.region, "forecast_wind_npy_0.1")
temperature_dir = os.path.join(args.input_region_root, args.region, "forecast_temperature_npy_0.1")
wind_target_dir = args.output_wind_dir
temperature_target_dir = args.output_temperature_dir

p = Pool(args.n_workers)
for name in ensure_stations:
    p.apply_async(
        run_one_station,
        args=(
            wind_dir,
            temperature_dir,
            wind_target_dir,
            temperature_target_dir,
            name,
            WIND_FEATURE_LIST,
            TEMPERATURE_FEATURE_LIST,
            FEATURE_NAME_ORIGIN,
            first_day,
            final_day,
        ),
    )
p.close()
p.join()
