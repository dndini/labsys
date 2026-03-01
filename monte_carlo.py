import pandas as pd


def lcg(a, c, m, z0, n):
    """
    Linear Congruential Generator (LCG)
    menghasilkan n angka acak dalam range 0..m-1
    """
    random_numbers = []
    z = z0
    for _ in range(n):
        z = (a * z + c) % m
        random_numbers.append(int(z))
    return random_numbers


def run_monte_carlo_simulation(df_freq, n_periods, params):
    """
    Simulasi Monte Carlo menggunakan LCG.

    df_freq: dataframe dengan kolom:
      - jumlah_pakai
      - frekuensi
    n_periods: jumlah iterasi/periode prediksi
    params: dict LCG {a, c, m, z0}

    Output:
      - df_prob: df_freq + probabilitas, kumulatif, interval
      - df_sim: hasil simulasi per periode
      - stats: statistik ringkas
    """
    # Validasi Input
    if df_freq is None or df_freq.empty:
        raise ValueError("df_freq kosong, tidak bisa simulasi.")

    df_freq = df_freq.copy()
    df_freq["jumlah_pakai"] = pd.to_numeric(df_freq["jumlah_pakai"])
    df_freq["frekuensi"] = pd.to_numeric(df_freq["frekuensi"])

    total_freq = df_freq["frekuensi"].sum()
    if total_freq <= 0:
        raise ValueError("Total frekuensi tidak valid (0).")

    # 1) Hitung Probabilitas
    df_freq["probabilitas"] = df_freq["frekuensi"] / total_freq
    df_freq["prob_kumulatif"] = df_freq["probabilitas"].cumsum()

    # 2) Buat Interval Angka Acak (0..m-1)
    m = int(params["m"])
    if m <= 1:
        raise ValueError("Parameter m (modulus) harus > 1.")

    # Mapping probabilitas ke range integer 0 sampai m
    upper_bounds = (df_freq["prob_kumulatif"] * m).astype(int).tolist()

    intervals_str = []
    int_bawah_list = []
    int_atas_list = []

    lower = 0
    for i, ub in enumerate(upper_bounds):
        ub = max(ub, lower)

        if i == len(upper_bounds) - 1:
            ub = m

        int_bawah_list.append(lower)
        int_atas_list.append(ub)

        if ub > lower:
            intervals_str.append(f"{lower} - {ub - 1}")
        else:
            intervals_str.append(f"{lower} - {lower}")

        lower = ub

    if lower < m:
        int_atas_list[-1] = m
        intervals_str[-1] = f"{int_bawah_list[-1]} - {m - 1}"

    df_freq["interval_bawah"] = int_bawah_list
    df_freq["interval_atas"] = int_atas_list
    df_freq["rentang_interval"] = intervals_str

    # 3) Generate Random Numbers dengan LCG
    random_vals = lcg(params["a"], params["c"], m, params["z0"], n_periods)

    # 4) Jalankan Simulasi
    simulated_data = []
    for i, r_val in enumerate(random_vals):
        prediksi = None
        for _, row in df_freq.iterrows():
            if row["interval_bawah"] <= r_val < row["interval_atas"]:
                prediksi = row["jumlah_pakai"]
                break

        if prediksi is None:
            prediksi = df_freq.iloc[-1]["jumlah_pakai"]

        simulated_data.append({
            "Periode": i + 1,
            "Angka Acak (Z)": r_val,
            "Prediksi Kebutuhan": float(prediksi)
        })

    df_sim = pd.DataFrame(simulated_data)

    # 5) Hitung Statistik Akhir
    stats = {
        "avg": float(df_sim["Prediksi Kebutuhan"].mean()),
        "max": float(df_sim["Prediksi Kebutuhan"].max()),
        "min": float(df_sim["Prediksi Kebutuhan"].min()),
        "total_predicted": float(df_sim["Prediksi Kebutuhan"].sum())
    }

    return df_freq, df_sim, stats


def run_monte_carlo_monthly(df_freq, params, n_months=12):
    """
    Simulasi Monte Carlo untuk prediksi bulanan dengan breakdown 4 minggu per bulan.

    df_freq: dataframe dengan kolom jumlah_pakai, frekuensi
    params: dict LCG {a, c, m, z0}
    n_months: jumlah bulan yang diprediksi (default 12)

    Output:
      - df_prob: tabel probabilitas
      - df_monthly: DataFrame dengan kolom Bulan, Minggu ke-1..4
      - stats: statistik ringkas keseluruhan
    """
    if df_freq is None or df_freq.empty:
        raise ValueError("df_freq kosong, tidak bisa simulasi.")

    # Total periode = n_months * 4 minggu
    total_periods = n_months * 4

    df_prob, df_sim_raw, _ = run_monte_carlo_simulation(df_freq, total_periods, params)

    # Reshape ke format bulanan (4 minggu per bulan)
    nama_bulan = [
        "Januari", "Februari", "Maret", "April", "Mei", "Juni",
        "Juli", "Agustus", "September", "Oktober", "November", "Desember"
    ]

    monthly_data = []
    idx = 0
    for i in range(n_months):
        row = {"Bulan": nama_bulan[i % 12]}
        for w in range(1, 5):
            if idx < len(df_sim_raw):
                row[f"Minggu ke-{w}"] = int(df_sim_raw.iloc[idx]["Prediksi Kebutuhan"])
            else:
                row[f"Minggu ke-{w}"] = 0
            idx += 1
        monthly_data.append(row)

    df_monthly = pd.DataFrame(monthly_data)

    # Hitung total per bulan
    week_cols = [f"Minggu ke-{w}" for w in range(1, 5)]
    df_monthly["Total"] = df_monthly[week_cols].sum(axis=1)

    # Total Pemakaian (baris terakhir)
    total_row = {"Bulan": "Total Pemakaian"}
    for col in week_cols:
        total_row[col] = int(df_monthly[col].sum())
    total_row["Total"] = int(df_monthly["Total"].sum())
    df_monthly = pd.concat([df_monthly, pd.DataFrame([total_row])], ignore_index=True)

    # Statistik keseluruhan
    all_values = df_sim_raw["Prediksi Kebutuhan"]
    stats = {
        "avg_per_periode": float(all_values.mean()),
        "max": float(all_values.max()),
        "min": float(all_values.min()),
        "total_predicted": float(all_values.sum()),
        "total_bulan": n_months
    }

    return df_prob, df_monthly, stats