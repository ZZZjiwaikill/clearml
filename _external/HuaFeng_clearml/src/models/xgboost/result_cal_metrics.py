import argparse
import os
from datetime import datetime
import warnings
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')

# 结果根目录（XGBoost 输出目录：每个站点一个子目录 xgboost_{station}）
DATA_ROOT = '/mnt/md0/zhouyunqi/HuaFeng/outputs/results'

# 评估输出根目录（所有产出按分类写入该目录下）
EVAL_ROOT = '/mnt/md0/zhouyunqi/HuaFeng/outputs/eval'

# 竞品路径（先确定路径，当前版本不参与对比/计算）
COMPETITOR_PATHS = {
    '日照五莲': '/mnt/md0/Power_Forecast_Data/source_data/华风/日照五莲/日照_超短期竞品预测.csv',
    '威海新区': '/mnt/md0/Power_Forecast_Data/source_data/华风/威海新区/新区_超短期竞品预测.csv',
}

STATIONS = ['日照五莲', '威海新区']

# 风电考核允许偏差（非受限时刻）：ΔP = max(0.25 * P_M, 1MW)
# 注：若后续拿到“受限标记”，可将受限时刻比例改为 0.28
WIND_ALLOW_RATIO = 0.25


def _infer_dt_hours(date_time: pd.Series, default_hours: float = 0.25) -> float:
    if date_time.empty:
        return default_hours
    dt = date_time.sort_values().diff().dropna()
    if dt.empty:
        return default_hours
    dt_hours = dt.median().total_seconds() / 3600.0
    if not np.isfinite(dt_hours) or dt_hours <= 0:
        return default_hours
    return float(dt_hours)


def calc_ultra_short_accuracy_penalty(
    df: pd.DataFrame,
    allow_ratio: float,
    min_allow_mw: float = 1.0,
    dt_hours: Optional[float] = None,
) -> Tuple[pd.DataFrame, Dict]:
    """
    超短期预测准确率考核（见 docs/考核标准.md）：

    考核电量 = Σ ( max(|P_M - P_P| - |ΔP|, 0) * dt * α )

    其中：
    - P_M：实际功率/可用功率（本项目中使用 label 列）
    - P_P：预测功率（本项目中使用 pred 列）
    - ΔP：允许偏差（风电：max(allow_ratio * P_M, 1MW)）
    - α：考核系数（按 |P_M - P_P| / P_M 的区间分段：0.1 / 0.3 / 0.7）
    """
    df = df.copy()
    df['date_time'] = pd.to_datetime(df['date_time'])
    df.sort_values('date_time', inplace=True)

    if dt_hours is None:
        dt_hours = _infer_dt_hours(df['date_time'])

    df['P_M'] = df['label'].astype(float)
    df['P_P'] = df['pred'].astype(float)
    df['abs_err'] = (df['P_M'] - df['P_P']).abs()
    df['allow_dev'] = np.maximum(df['P_M'] * allow_ratio, min_allow_mw)
    df['excess_err'] = np.maximum(df['abs_err'] - df['allow_dev'], 0.0)

    denom = np.maximum(df['P_M'].abs(), 1e-6)
    df['err_ratio'] = df['abs_err'] / denom
    df['alpha'] = np.select(
        [
            df['err_ratio'] < 0.5,
            df['err_ratio'] < 1.0,
        ],
        [
            0.1,
            0.3,
        ],
        default=0.7,
    )
    df.loc[df['excess_err'] <= 0, 'alpha'] = 0.0

    df['dt_hours'] = float(dt_hours)
    df['penalty_mwh'] = df['excess_err'] * df['dt_hours'] * df['alpha']

    df['month'] = df['date_time'].dt.to_period('M').astype(str)
    monthly_energy_mwh = df.groupby('month')['P_M'].apply(lambda x: float((x * dt_hours).sum()))
    monthly_penalty_mwh = df.groupby('month')['penalty_mwh'].sum()

    monthly_df = pd.DataFrame(
        {
            'month': monthly_energy_mwh.index,
            'energy_mwh': monthly_energy_mwh.values,
            'accuracy_penalty_mwh_raw': monthly_penalty_mwh.reindex(monthly_energy_mwh.index, fill_value=0.0).values,
        }
    )
    monthly_df['accuracy_penalty_mwh_cap_8pct'] = np.minimum(
        monthly_df['accuracy_penalty_mwh_raw'], monthly_df['energy_mwh'] * 0.08
    )

    report = {
        'dt_hours': float(dt_hours),
        'total_accuracy_penalty_mwh_raw': float(df['penalty_mwh'].sum()),
    }
    return df, {'monthly': monthly_df, 'report': report}


def calc_ultra_short_report_penalty(
    df: pd.DataFrame,
    dt_hours: float,
    points_per_day: int = 96,
) -> pd.DataFrame:
    """
    超短期预测上报率考核（按 docs/考核标准.md 文本描述实现）：
    - 上报率按日统计，按月考核
    - 每降低 1 个百分点，扣罚当月上网电量的 0.1%
    - 月度累计考核电量不超过当月上网电量的 1%
    """
    df = df.copy()
    df['date_time'] = pd.to_datetime(df['date_time'])
    df['date'] = df['date_time'].dt.date
    df['month'] = df['date_time'].dt.to_period('M').astype(str)

    daily_cnt = df.groupby(['month', 'date']).size().rename('reported_points').reset_index()
    daily_cnt['expected_points'] = points_per_day
    daily_cnt['report_rate'] = daily_cnt['reported_points'] / daily_cnt['expected_points']
    daily_cnt['missing_pct'] = (1.0 - daily_cnt['report_rate']).clip(lower=0.0) * 100.0

    monthly_energy_mwh = df.groupby('month')['label'].apply(lambda x: float((x.astype(float) * dt_hours).sum()))
    monthly_missing_pct = daily_cnt.groupby('month')['missing_pct'].mean()
    monthly = pd.DataFrame({'month': monthly_energy_mwh.index})
    monthly['energy_mwh'] = monthly_energy_mwh.values
    monthly['missing_pct'] = monthly_missing_pct.reindex(monthly['month'], fill_value=0.0).values
    monthly['report_penalty_mwh_raw'] = monthly['energy_mwh'] * (monthly['missing_pct'] * 0.001)
    monthly['report_penalty_mwh_cap_1pct'] = np.minimum(monthly['report_penalty_mwh_raw'], monthly['energy_mwh'] * 0.01)
    return monthly

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-root', type=str, default=DATA_ROOT)
    parser.add_argument('--eval-root', type=str, default=EVAL_ROOT)
    parser.add_argument('--forecast-index', type=int, default=1)
    parser.add_argument('--stations', nargs='*', default=STATIONS)
    return parser


def main():
    args = build_parser().parse_args()

    accuracy_dir = os.path.join(args.eval_root, 'ultra_short_accuracy')
    os.makedirs(accuracy_dir, exist_ok=True)

    print(
        f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] start eval: data_root={args.data_root}, eval_root={args.eval_root}, forecast_index={args.forecast_index}, stations={args.stations}",
        flush=True,
    )

    summary_rows = []
    total = len(args.stations)
    for i, station in enumerate(args.stations, start=1):
        station_dir = os.path.join(args.data_root, f'xgboost_{station}')
        data_path = os.path.join(station_dir, f'{station}_{args.forecast_index}.csv')

        print(f"[{i}/{total}] reading: {data_path}", flush=True)
        if not os.path.exists(data_path):
            raise FileNotFoundError(f"missing result file: {data_path}")

        df = pd.read_csv(data_path)
        if list(df.columns)[:3] != ['date_time', 'pred', 'label'] and df.shape[1] >= 3:
            df = df.iloc[:, :3]
            df.columns = ['date_time', 'pred', 'label']

        detail_df, out = calc_ultra_short_accuracy_penalty(df, allow_ratio=WIND_ALLOW_RATIO)
        monthly_accuracy_df = out['monthly']
        dt_hours = out['report']['dt_hours']

        monthly_report_df = calc_ultra_short_report_penalty(df, dt_hours=dt_hours)
        monthly_df = pd.merge(monthly_accuracy_df, monthly_report_df, on=['month', 'energy_mwh'], how='outer')

        detail_path = os.path.join(accuracy_dir, f'{station}_detail.csv')
        monthly_path = os.path.join(accuracy_dir, f'{station}_monthly.csv')
        detail_df.to_csv(detail_path, index=False)
        monthly_df.to_csv(monthly_path, index=False)
        print(f"[{i}/{total}] wrote: {detail_path}", flush=True)
        print(f"[{i}/{total}] wrote: {monthly_path}", flush=True)

        summary_rows.append(
            {
                'station': station,
                'result_path': data_path,
                'competitor_path': COMPETITOR_PATHS.get(station, ''),
                'dt_hours': dt_hours,
                'total_accuracy_penalty_mwh_raw': float(detail_df['penalty_mwh'].sum()),
                'total_accuracy_penalty_mwh_cap_8pct': float(monthly_df['accuracy_penalty_mwh_cap_8pct'].sum()),
                'total_report_penalty_mwh_raw': float(monthly_df['report_penalty_mwh_raw'].fillna(0.0).sum()),
                'total_report_penalty_mwh_cap_1pct': float(monthly_df['report_penalty_mwh_cap_1pct'].fillna(0.0).sum()),
            }
        )

        print(
            f"[{i}/{total}] done station={station} accuracy_penalty_mwh_raw={summary_rows[-1]['total_accuracy_penalty_mwh_raw']} report_penalty_mwh_raw={summary_rows[-1]['total_report_penalty_mwh_raw']}",
            flush=True,
        )

    summary_df = pd.DataFrame(summary_rows)
    summary_path = os.path.join(accuracy_dir, 'summary_all.csv')
    summary_df.to_csv(summary_path, index=False)
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] all done: {summary_path}", flush=True)


if __name__ == '__main__':
    main()
