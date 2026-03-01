import streamlit as st
import pandas as pd
import hashlib
import plotly.express as px
import plotly.graph_objects as go
from datetime import date, datetime, timedelta
import time
import secrets
import calendar

from sqlalchemy import text

# --- Import Modul Lokal ---
from models import (
    SessionLocal, engine,
    User, Proyek, Bahan, Alat,
    Pemakaian, DetailPemakaianBahan, DetailPemakaianAlat,
    reset_database
)
from monte_carlo import run_monte_carlo_simulation, run_monte_carlo_monthly

# --- Konfigurasi Halaman ---
st.set_page_config(
    page_title="Sinergi Geoenvi Lab System",
    layout="wide",
    page_icon="🔬",
    initial_sidebar_state="expanded"
)

# --- Styling CSS ---
st.markdown("""
<style>
    .header-style {
        font-size: 24px; font-weight: 700; color: #0f52ba;
        border-bottom: 2px solid #eee; padding-bottom: 10px; margin-bottom: 20px;
    }
    .metric-box {
        background-color: #f8f9fa; border: 1px solid #ddd; padding: 15px;
        border-radius: 8px; text-align: center;
    }
    .metric-title { font-size: 14px; color: #666; }
    .metric-value { font-size: 24px; font-weight: bold; color: #333; }
    .hint { color: #666; font-size: 13px; }
    .weekly-table th {
        background-color: #0f52ba; color: white; text-align: center; padding: 8px;
    }
    .weekly-table td {
        text-align: center; padding: 6px; border: 1px solid #ddd;
    }
    .weekly-table tr:nth-child(even) { background-color: #f2f6fc; }
    .weekly-table tr:last-child { font-weight: bold; background-color: #e8eef7; }
</style>
""", unsafe_allow_html=True)

# --- Helper Functions ---
def get_session():
    return SessionLocal()

def hash_pass(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def hash_text(text_in: str) -> str:
    return hashlib.sha256(text_in.encode()).hexdigest()


def get_week_of_month(dt):
    """Menentukan minggu ke berapa dalam bulan (1-4). Minggu ke-5 digabung ke minggu ke-4."""
    day = dt.day
    if day <= 7:
        return 1
    elif day <= 14:
        return 2
    elif day <= 21:
        return 3
    else:
        return 4


def build_weekly_usage_table(db, item_type="bahan", category_filter=None, item_id=None, year=None):
    """
    Membangun tabel pemakaian mingguan format: Bulan x Minggu ke-1..4
    Sesuai format dokumen: Tabel Data Jumlah Pemakaian per Tahun.

    Parameters:
      - db: database session
      - item_type: 'bahan' atau 'alat'
      - category_filter: filter kategori (Solvent/Padatan/Consumable)
      - item_id: filter item tertentu (opsional, untuk detail per item)
      - year: tahun filter (default tahun berjalan)
    """
    if year is None:
        year = date.today().year

    if item_type == "bahan":
        sql = f"""
            SELECT p.tgl_pemakaian, b.nama_bahan AS item, b.kategori,
                   SUM(d.jumlah_pakai) AS jumlah
            FROM detail_pemakaian_bahan d
            JOIN pemakaian p ON d.id_pemakaian = p.id
            JOIN bahan b ON d.id_bahan = b.id
            WHERE strftime('%Y', p.tgl_pemakaian) = '{year}'
        """
        if category_filter:
            sql += f" AND b.kategori = '{category_filter}'"
        if item_id:
            sql += f" AND b.id = {item_id}"
        sql += " GROUP BY p.tgl_pemakaian, b.nama_bahan, b.kategori"
    else:
        sql = f"""
            SELECT p.tgl_pemakaian, a.nama_alat AS item, a.kategori,
                   SUM(d.jumlah_pakai) AS jumlah
            FROM detail_pemakaian_alat d
            JOIN pemakaian p ON d.id_pemakaian = p.id
            JOIN alat a ON d.id_alat = a.id
            WHERE strftime('%Y', p.tgl_pemakaian) = '{year}'
        """
        if category_filter:
            sql += f" AND a.kategori = '{category_filter}'"
        if item_id:
            sql += f" AND a.id = {item_id}"
        sql += " GROUP BY p.tgl_pemakaian, a.nama_alat, a.kategori"

    df_raw = pd.read_sql(text(sql), db.bind)

    if df_raw.empty:
        return pd.DataFrame()

    # Parse tanggal & hitung minggu ke-berapa
    df_raw["tgl_pemakaian"] = pd.to_datetime(df_raw["tgl_pemakaian"])
    df_raw["bulan"] = df_raw["tgl_pemakaian"].dt.month
    df_raw["minggu"] = df_raw["tgl_pemakaian"].apply(get_week_of_month)

    # Pivot: Bulan x Minggu
    pivot = df_raw.groupby(["bulan", "minggu"])["jumlah"].sum().reset_index()
    pivot_table = pivot.pivot_table(index="bulan", columns="minggu", values="jumlah", fill_value=0)

    # Pastikan semua minggu 1-4 ada
    for w in range(1, 5):
        if w not in pivot_table.columns:
            pivot_table[w] = 0
    pivot_table = pivot_table[[1, 2, 3, 4]]

    # Rename kolom
    pivot_table.columns = ["Minggu ke-1", "Minggu ke-2", "Minggu ke-3", "Minggu ke-4"]

    # Map bulan ke nama
    nama_bulan = {
        1: "Januari", 2: "Februari", 3: "Maret", 4: "April",
        5: "Mei", 6: "Juni", 7: "Juli", 8: "Agustus",
        9: "September", 10: "Oktober", 11: "November", 12: "Desember"
    }
    pivot_table.index = pivot_table.index.map(nama_bulan)
    pivot_table.index.name = "Bulan"

    # Tambah kolom Total per bulan
    pivot_table["Total"] = pivot_table.sum(axis=1)

    # Tambah baris Total Pemakaian
    total_row = pivot_table.sum(axis=0)
    total_row.name = "Total Pemakaian"
    pivot_table = pd.concat([pivot_table, total_row.to_frame().T])

    # Cast ke integer
    pivot_table = pivot_table.astype(int)

    return pivot_table


def get_usage_summary(db, item_type: str, category_filter: str = None):
    """
    Menghitung total pemakaian bahan atau alat.
    Menambahkan category_filter untuk perhitungan rata-rata per jenis.
    """
    if item_type == "bahan":
        query = """
            SELECT b.id AS id, b.nama_bahan AS nama, b.kategori,
                   COALESCE(SUM(d.jumlah_pakai), 0) AS total_pakai
            FROM bahan b
            LEFT JOIN detail_pemakaian_bahan d ON d.id_bahan = b.id
        """
        if category_filter:
            query += f" WHERE b.kategori = '{category_filter}'"
        query += " GROUP BY b.id, b.nama_bahan"
    else:
        query = """
            SELECT a.id AS id, a.nama_alat AS nama, a.kategori,
                   COALESCE(SUM(d.jumlah_pakai), 0) AS total_pakai
            FROM alat a
            LEFT JOIN detail_pemakaian_alat d ON d.id_alat = a.id
        """
        if category_filter:
            query += f" WHERE a.kategori = '{category_filter}'"
        query += " GROUP BY a.id, a.nama_alat"

    df = pd.read_sql(text(query), db.bind)

    df_hist = df[df["total_pakai"] > 0].copy()
    avg_total = float(df_hist["total_pakai"].mean()) if not df_hist.empty else 0.0

    df["sering_digunakan"] = df["total_pakai"] >= avg_total if avg_total > 0 else False
    return df, avg_total


# --- Autentikasi Session State ---
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.user_role = None
    st.session_state.user_id = None
    st.session_state.username = None

def login_page():
    c1, c2, c3 = st.columns([1, 1.2, 1])
    with c2:
        st.markdown("<br><br>", unsafe_allow_html=True)
        st.markdown(
            "<h2 style='text-align: center; color: #0f52ba;'>🔬 Sinergi Geoenvi Lab System</h2>",
            unsafe_allow_html=True
        )
        st.markdown(
            "<p style='text-align: center; color: #666;'>Sistem Manajemen Laboratorium Terpadu</p>",
            unsafe_allow_html=True
        )

        with st.form("login_form"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")

            if st.form_submit_button("Masuk Sistem", type="primary", use_container_width=True):
                db = get_session()
                user = db.query(User).filter(User.username == username).first()
                db.close()

                if user and user.password == hash_pass(password):
                    st.session_state.logged_in = True
                    st.session_state.user_role = user.role
                    st.session_state.user_id = user.id
                    st.session_state.username = user.nama
                    st.success("Login Berhasil!")
                    st.rerun()
                else:
                    st.error("Username atau Password salah.")

        # --- Forgot Password ---
        with st.expander("🔑 Lupa Password? Reset dengan Kode"):
            st.caption("Minta reset code ke Manager. Kode berlaku 24 jam, sekali pakai.")

            with st.form("reset_password_form"):
                u = st.text_input("Username yang lupa password", key="fp_user")
                reset_code = st.text_input("Reset Code dari Manager", key="fp_code")
                new_pw = st.text_input("Password Baru", type="password", key="fp_newpw")
                new_pw2 = st.text_input("Ulangi Password Baru", type="password", key="fp_newpw2")

                if st.form_submit_button("Reset Password", type="primary", use_container_width=True):
                    if not u or not reset_code or not new_pw:
                        st.error("Lengkapi username, reset code, dan password baru.")
                    elif new_pw != new_pw2:
                        st.error("Password baru tidak sama.")
                    else:
                        db = get_session()
                        user = db.query(User).filter(User.username == u).first()

                        if not user or not user.reset_code_hash or not user.reset_code_expiry:
                            st.error("Reset code tidak ditemukan. Minta Manager buatkan kode baru.")
                        else:
                            now = datetime.now()
                            if user.reset_code_expiry < now:
                                st.error("Reset code sudah kedaluwarsa. Minta Manager buat kode baru.")
                            elif user.reset_code_hash != hash_text(reset_code.strip()):
                                st.error("Reset code salah.")
                            else:
                                user.password = hash_pass(new_pw)
                                user.reset_code_hash = None
                                user.reset_code_expiry = None
                                db.commit()
                                st.success("Password berhasil direset. Silakan login dengan password baru.")
                        db.close()


def logout():
    st.session_state.logged_in = False
    st.session_state.user_role = None
    st.session_state.user_id = None
    st.session_state.username = None
    st.rerun()


# =====================================================================
# HALAMAN 1: DASHBOARD (Hanya untuk Manager)
# =====================================================================
def dashboard_page():
    
    st.markdown("<div class='header-style'>📊 Dashboard Pemakaian Laboratorium</div>", unsafe_allow_html=True)
    db = get_session()

    # --- KPI Cards ---
    total_bahan = db.query(Bahan).count()
    total_alat = db.query(Alat).count()
    total_proyek = db.query(Proyek).count()
    total_transaksi = db.query(Pemakaian).count()

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(
            f"""<div class="metric-box"><div class="metric-title">Total Bahan Kimia</div>
            <div class="metric-value">{total_bahan}</div></div>""",
            unsafe_allow_html=True
        )
    with col2:
        st.markdown(
            f"""<div class="metric-box"><div class="metric-title">Total Alat Consumable</div>
            <div class="metric-value">{total_alat}</div></div>""",
            unsafe_allow_html=True
        )
    with col3:
        st.markdown(
            f"""<div class="metric-box"><div class="metric-title">Proyek Aktif</div>
            <div class="metric-value">{total_proyek}</div></div>""",
            unsafe_allow_html=True
        )
    with col4:
        st.markdown(
            f"""<div class="metric-box"><div class="metric-title">Total Transaksi</div>
            <div class="metric-value">{total_transaksi}</div></div>""",
            unsafe_allow_html=True
        )

    st.markdown("---")

    # --- Filter Tahun & Kategori ---
    col_filter1, col_filter2 = st.columns(2)
    with col_filter1:
        current_year = date.today().year
        year_options = list(range(current_year, current_year - 5, -1))
        selected_year = st.selectbox("Pilih Tahun:", year_options, index=0, key="dash_year")
    with col_filter2:
        view_mode = st.selectbox(
            "Tampilkan Kategori:",
            ["Semua Bahan Kimia", "Solvent", "Padatan", "Alat Consumable"],
            key="dash_category"
        )

    # Tentukan parameter query
    if view_mode == "Solvent":
        itype, ifilter = "bahan", "Solvent"
    elif view_mode == "Padatan":
        itype, ifilter = "bahan", "Padatan"
    elif view_mode == "Alat Consumable":
        itype, ifilter = "alat", "Consumable"
    else:
        itype, ifilter = "bahan", None  # Semua bahan

    # --- Tabel Pemakaian Mingguan ---
    st.subheader(f"📋 Data Pemakaian Per Minggu — Tahun {selected_year}")

    df_weekly = build_weekly_usage_table(db, item_type=itype, category_filter=ifilter, year=selected_year)

    if not df_weekly.empty:
        st.dataframe(df_weekly, use_container_width=True)

        # --- Grafik Pemakaian Mingguan ---
        st.subheader("📈 Grafik Pemakaian Per Periode Mingguan")

        # Hilangkan baris Total untuk grafik
        df_chart = df_weekly[df_weekly.index != "Total Pemakaian"].copy()
        week_cols = ["Minggu ke-1", "Minggu ke-2", "Minggu ke-3", "Minggu ke-4"]

        fig = go.Figure()
        colors = ["#0f52ba", "#4a90d9", "#7fb3e8", "#b5d4f1"]
        for i, col in enumerate(week_cols):
            fig.add_trace(go.Bar(
                name=col,
                x=df_chart.index.tolist(),
                y=df_chart[col].tolist(),
                marker_color=colors[i]
            ))

        fig.update_layout(
            barmode='group',
            title=f"Pemakaian {view_mode} Per Minggu — Tahun {selected_year}",
            xaxis_title="Bulan",
            yaxis_title="Jumlah Pemakaian",
            legend_title="Periode",
            height=450
        )
        st.plotly_chart(fig, use_container_width=True)

        # Grafik Tren Total Bulanan
        st.subheader("📉 Tren Total Pemakaian Bulanan")
        df_trend = df_chart[["Total"]].copy()
        fig_trend = px.line(
            x=df_trend.index.tolist(),
            y=df_trend["Total"].tolist(),
            markers=True,
            labels={"x": "Bulan", "y": "Total Pemakaian"},
            title=f"Tren Pemakaian Bulanan — {view_mode} ({selected_year})"
        )
        fig_trend.update_traces(line_color="#0f52ba", line_width=3)
        st.plotly_chart(fig_trend, use_container_width=True)

    else:
        st.info(f"Belum ada data pemakaian untuk kategori '{view_mode}' di tahun {selected_year}.")

    db.close()


# =====================================================================
# HALAMAN 2: MASTER DATA
# =====================================================================
def master_data_page():
    role = st.session_state.user_role
    st.markdown("<div class='header-style'>Pengelolaan Data Master</div>", unsafe_allow_html=True)

    if role == 'manager':
        st.info("ℹ️ Mode Manager: View Only (tidak bisa tambah/edit).")

    tab1, tab2, tab3 = st.tabs(["📦 Data Bahan", "🧰 Data Alat", "🏗️ Data Proyek"])
    db = get_session()

    # --- TAB BAHAN ---
    with tab1:
        df_bahan = pd.read_sql(db.query(Bahan).statement, db.bind)
        st.dataframe(df_bahan, use_container_width=True, hide_index=True)

        if role == 'purchasing':
            st.markdown("### Aksi")
            action = st.radio(
                "Pilih Menu:",
                ["Tambah Baru", "Restock (Tambah Stok)", "Edit / Hapus Data"],
                horizontal=True, key="act_b"
            )

            if action == "Tambah Baru":
                with st.form("add_bahan", clear_on_submit=True):
                    c1, c2 = st.columns(2)
                    nb = c1.text_input("Nama Bahan")
                    kat = c2.selectbox("Kategori", ["Solvent", "Padatan"])
                    sat = c1.selectbox("Satuan", ["ml", "gram"])
                    sa = c2.number_input("Stok Awal", min_value=0, step=1)
                    sm = c1.number_input("Stok Minimum", min_value=0, step=1)
                    ket = c2.text_input("Keterangan")

                    if st.form_submit_button("Simpan Data"):
                        if nb:
                            db.add(Bahan(
                                nama_bahan=nb, kategori=kat, satuan=sat,
                                stok_awal=sa, stok_minimum=sm, keterangan=ket
                            ))
                            db.commit()
                            st.success(f"Bahan '{nb}' tersimpan!")
                            st.rerun()
                        else:
                            st.error("Nama bahan wajib diisi.")

            elif action == "Restock (Tambah Stok)":
                opts = {
                    b.id: f"{b.nama_bahan} (Stok: {b.stok_awal} {b.satuan})"
                    for b in db.query(Bahan).all()
                }
                if not opts:
                    st.warning("Belum ada data bahan.")
                else:
                    bid = st.selectbox(
                        "Pilih Bahan untuk Restock:",
                        list(opts.keys()), format_func=lambda x: opts[x]
                    )
                    if bid:
                        add_qty = st.number_input("Jumlah Masuk", min_value=1, step=1)
                        if st.button("Update Stok", type="primary"):
                            item = db.query(Bahan).filter(Bahan.id == bid).first()
                            item.stok_awal += add_qty
                            db.commit()
                            st.success("Stok berhasil ditambahkan!")
                            st.rerun()

            elif action == "Edit / Hapus Data":
                opts = {b.id: f"{b.nama_bahan}" for b in db.query(Bahan).all()}
                if not opts:
                    st.warning("Belum ada data bahan.")
                else:
                    bid = st.selectbox(
                        "Pilih Bahan Edit:",
                        list(opts.keys()), format_func=lambda x: opts[x]
                    )
                    if bid:
                        item = db.query(Bahan).filter(Bahan.id == bid).first()
                        with st.form("edit_bahan"):
                            enama = st.text_input("Nama", value=item.nama_bahan)
                            ekat = st.selectbox(
                                "Kategori", ["Solvent", "Padatan"],
                                index=["Solvent", "Padatan"].index(item.kategori)
                                if item.kategori in ["Solvent", "Padatan"] else 0
                            )
                            esat = st.selectbox(
                                "Satuan", ["ml", "gram"],
                                index=["ml", "gram"].index(item.satuan)
                                if item.satuan in ["ml", "gram"] else 0
                            )
                            estok = st.number_input("Stok Saat Ini", value=int(item.stok_awal), min_value=0, step=1)
                            emin = st.number_input("Stok Min", value=int(item.stok_minimum), min_value=0, step=1)
                            eket = st.text_input("Ket", value=item.keterangan or "")

                            c_edit, c_del = st.columns(2)
                            if c_edit.form_submit_button("Simpan Perubahan"):
                                item.nama_bahan = enama
                                item.kategori = ekat
                                item.satuan = esat
                                item.stok_awal = estok
                                item.stok_minimum = emin
                                item.keterangan = eket
                                db.commit()
                                st.success("Data diperbarui.")
                                st.rerun()

                            if c_del.form_submit_button("🗑️ Hapus Data", type="primary"):
                                db.delete(item)
                                db.commit()
                                st.warning("Data dihapus.")
                                st.rerun()

    # --- TAB ALAT ---
    with tab2:
        df_alat = pd.read_sql(db.query(Alat).statement, db.bind)
        st.dataframe(df_alat, use_container_width=True, hide_index=True)

        if role == 'purchasing':
            st.markdown("### Aksi")
            action_a = st.radio(
                "Pilih Menu:", ["Tambah Baru", "Restock", "Edit / Hapus"],
                horizontal=True, key="act_a"
            )

            if action_a == "Tambah Baru":
                with st.form("add_alat", clear_on_submit=True):
                    na = st.text_input("Nama Alat")
                    kat = st.selectbox("Kategori", ["Consumable"])
                    sat = st.selectbox("Satuan", ["pcs", "set", "unit"])
                    sa = st.number_input("Stok Awal", min_value=0, step=1)
                    sm = st.number_input("Stok Minimum", min_value=0, step=1)
                    ket = st.text_input("Keterangan")
                    if st.form_submit_button("Simpan Data"):
                        if na:
                            db.add(Alat(
                                nama_alat=na, kategori=kat, satuan=sat,
                                stok_awal=sa, stok_minimum=sm, keterangan=ket
                            ))
                            db.commit()
                            st.success("Alat tersimpan!")
                            st.rerun()
                        else:
                            st.error("Nama alat wajib diisi.")

            elif action_a == "Restock":
                opts = {
                    a.id: f"{a.nama_alat} (Stok: {a.stok_awal})"
                    for a in db.query(Alat).all()
                }
                if not opts:
                    st.warning("Belum ada data.")
                else:
                    aid = st.selectbox(
                        "Pilih Alat:", list(opts.keys()),
                        format_func=lambda x: opts[x]
                    )
                    if aid:
                        add_qty = st.number_input("Jumlah Masuk", min_value=1, step=1, key="ra")
                        if st.button("Update Stok Alat", type="primary"):
                            item = db.query(Alat).filter(Alat.id == aid).first()
                            item.stok_awal += add_qty
                            db.commit()
                            st.success("Stok update!")
                            st.rerun()

            elif action_a == "Edit / Hapus":
                opts = {a.id: f"{a.nama_alat}" for a in db.query(Alat).all()}
                if not opts:
                    st.warning("Belum ada data.")
                else:
                    aid = st.selectbox(
                        "Pilih Alat Edit:", list(opts.keys()),
                        format_func=lambda x: opts[x]
                    )
                    if aid:
                        item = db.query(Alat).filter(Alat.id == aid).first()
                        with st.form("edit_alat"):
                            enama = st.text_input("Nama", value=item.nama_alat)
                            esat = st.selectbox(
                                "Satuan", ["pcs", "set", "unit"],
                                index=["pcs", "set", "unit"].index(item.satuan)
                                if item.satuan in ["pcs", "set", "unit"] else 0
                            )
                            estok = st.number_input("Stok", value=int(item.stok_awal), step=1)
                            emin = st.number_input("Min", value=int(item.stok_minimum), step=1)
                            if st.form_submit_button("Simpan"):
                                item.nama_alat = enama
                                item.satuan = esat
                                item.stok_awal = estok
                                item.stok_minimum = emin
                                db.commit()
                                st.success("Update berhasil.")
                                st.rerun()
                            if st.form_submit_button("Hapus", type="primary"):
                                db.delete(item)
                                db.commit()
                                st.rerun()

    # --- TAB PROYEK ---
    with tab3:
        if role == 'purchasing':
            with st.expander("➕ Buat Proyek Baru"):
                with st.form("add_proyek", clear_on_submit=True):
                    np_name = st.text_input("Nama Proyek")
                    c1, c2 = st.columns(2)
                    tm = c1.date_input("Tgl Mulai")
                    ts = c2.date_input("Tgl Selesai")
                    desk = st.text_area("Deskripsi")
                    if st.form_submit_button("Simpan Proyek"):
                        db.add(Proyek(nama_proyek=np_name, tgl_mulai=tm, tgl_selesai=ts, deskripsi=desk))
                        db.commit()
                        st.success("Proyek dibuat!")
                        st.rerun()

        df_proyek = pd.read_sql(db.query(Proyek).statement, db.bind)
        st.dataframe(df_proyek, use_container_width=True, hide_index=True)

    db.close()


# =====================================================================
# HALAMAN 3: TRANSAKSI / INPUT LOGISTIK (Purchasing)
# =====================================================================
def transaction_page():
    st.markdown("<div class='header-style'>Input Pemakaian</div>", unsafe_allow_html=True)
    db = get_session()

    # 1. Header Transaksi
    with st.container(border=True):
        col_a, col_b = st.columns(2)
        with col_a:
            today = date.today()
            proyek_list = db.query(Proyek).filter(Proyek.tgl_selesai >= today).all()
            p_opts = {p.id: p.nama_proyek for p in proyek_list}
            if not p_opts:
                st.warning("Tidak ada proyek aktif (cek tanggal selesai).")
            sel_proyek = st.selectbox(
                "Pilih Proyek Aktif:", options=list(p_opts.keys()),
                format_func=lambda x: p_opts[x], index=None
            )
        with col_b:
            tgl = st.date_input("Tanggal Pemakaian", value=date.today())

        ket = st.text_input("Catatan Tambahan")

    # 2. Input Bahan & Alat
    tab_solvent, tab_padatan, tab_alat = st.tabs(
        ["💧 Bahan: Solvent", "🧱 Bahan: Padatan", "🧰 Alat (Consumable)"]
    )

    def create_input_editor(query_filter, key_suffix):
        df = pd.read_sql(
            db.query(Bahan.id, Bahan.nama_bahan, Bahan.stok_awal, Bahan.satuan)
              .filter(Bahan.stok_awal > 0).filter(query_filter).statement,
            db.bind
        )
        if not df.empty:
            df['Pilih'] = False
            df['Jumlah_Pakai'] = 0
            return st.data_editor(
                df,
                column_config={
                    "Pilih": st.column_config.CheckboxColumn(default=False),
                    "Jumlah_Pakai": st.column_config.NumberColumn(min_value=0, step=1),
                    "id": None
                },
                disabled=["id", "nama_bahan", "stok_awal", "satuan"],
                hide_index=True,
                use_container_width=True,
                key=f"edit_{key_suffix}"
            )
        else:
            st.info("Tidak ada stok tersedia untuk kategori ini.")
            return pd.DataFrame()

    with tab_solvent:
        edited_solvent = create_input_editor(Bahan.kategori == 'Solvent', 'solvent')

    with tab_padatan:
        edited_padatan = create_input_editor(Bahan.kategori == 'Padatan', 'padatan')

    with tab_alat:
        df_a = pd.read_sql(
            db.query(Alat.id, Alat.nama_alat, Alat.stok_awal, Alat.satuan)
              .filter(Alat.stok_awal > 0).statement,
            db.bind
        )
        if not df_a.empty:
            df_a['Pilih'] = False
            df_a['Jumlah_Pakai'] = 0
            edited_alat = st.data_editor(
                df_a,
                column_config={
                    "Pilih": st.column_config.CheckboxColumn(default=False),
                    "Jumlah_Pakai": st.column_config.NumberColumn(min_value=0, step=1)
                },
                disabled=["id", "nama_alat", "stok_awal", "satuan"],
                hide_index=True, use_container_width=True, key="edit_alat_trx"
            )
        else:
            st.info("Stok alat kosong.")
            edited_alat = pd.DataFrame()

    # 3. Submit
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("💾 Simpan Transaksi", type="primary", use_container_width=True):
        if not sel_proyek:
            st.error("Wajib memilih proyek!")
        else:
            try:
                trx = Pemakaian(
                    id_proyek=sel_proyek, tgl_pemakaian=tgl,
                    user_id=st.session_state.user_id, keterangan=ket
                )
                db.add(trx)
                db.flush()

                item_count = 0

                def save_items(df_input, Model, DetailModel, id_field):
                    count = 0
                    if not df_input.empty:
                        for _, row in df_input[df_input['Pilih'] == True].iterrows():
                            if row['Jumlah_Pakai'] > 0:
                                if row['Jumlah_Pakai'] > row['stok_awal']:
                                    raise ValueError(f"Stok '{row.iloc[1]}' tidak cukup!")

                                detail = DetailModel(
                                    id_pemakaian=trx.id,
                                    jumlah_pakai=row['Jumlah_Pakai']
                                )
                                setattr(detail, id_field, row['id'])
                                db.add(detail)

                                item_obj = db.query(Model).filter(
                                    getattr(Model, 'id') == row['id']
                                ).first()
                                item_obj.stok_awal -= row['Jumlah_Pakai']
                                count += 1
                    return count

                item_count += save_items(edited_solvent, Bahan, DetailPemakaianBahan, 'id_bahan')
                item_count += save_items(edited_padatan, Bahan, DetailPemakaianBahan, 'id_bahan')
                item_count += save_items(edited_alat, Alat, DetailPemakaianAlat, 'id_alat')

                if item_count > 0:
                    db.commit()
                    st.success(f"Transaksi Berhasil! {item_count} item dicatat.")
                    time.sleep(1)
                    st.rerun()
                else:
                    st.warning("Belum ada item dipilih.")
                    db.rollback()

            except Exception as e:
                db.rollback()
                st.error(f"Gagal: {e}")
    db.close()


# =====================================================================
# HALAMAN 4: PREDIKSI (Manager)
# =====================================================================
def prediction_page():
    
    st.markdown(
        "<div class='header-style'>📈 Simulasi Prediksi Pemakaian</div>",
        unsafe_allow_html=True
    )
    db = get_session()

    # Pilihan kategori
    c1, c2 = st.columns(2)
    with c1:
        cat_type = st.selectbox(
            "Pilih Kategori:",
            ["Bahan: Solvent", "Bahan: Padatan", "Alat: Consumable"]
        )

    # Mapping
    if "Solvent" in cat_type:
        itype, ifilter = "bahan", "Solvent"
    elif "Padatan" in cat_type:
        itype, ifilter = "bahan", "Padatan"
    else:
        itype, ifilter = "alat", "Consumable"

    # Hitung rata-rata per kategori
    df_sum, avg_total = get_usage_summary(db, itype, ifilter)

    with c2:
        st.info(f"Rata-rata total pemakaian (kategori ini): **{avg_total:.2f}**")

    # Filter item sering digunakan
    df_freq_items = df_sum[
        (df_sum["total_pakai"] > 0) & (df_sum["sering_digunakan"] == True)
    ].copy()

    if df_freq_items.empty:
        st.warning("Belum ada item yang digunakan pada kategori ini.")
        db.close()
        return

    # Pilihan item
    opts = dict(zip(df_freq_items["id"], df_freq_items["nama"]))
    selected_item = st.selectbox(
        "Pilih Item :",
        options=list(opts.keys()), format_func=lambda x: opts[x]
    )

    # Parameter LCG
    params = {'a': 67, 'c': 17, 'm': 99, 'z0': 10}

    # Prediksi 4 periode per bulan x 12 bulan
    st.markdown("---")
    st.caption("Simulasi menggunakan metode Monte Carlo dengan LCG untuk memprediksi kebutuhan 4 periode (minggu) per bulan selama 12 bulan ke depan.")

    if st.button("🚀 Jalankan Simulasi Prediksi", type="primary"):
        # Ambil data history
        table_detail = "detail_pemakaian_bahan" if itype == "bahan" else "detail_pemakaian_alat"
        col_id = "id_bahan" if itype == "bahan" else "id_alat"

        q = f"""
            SELECT d.jumlah_pakai
            FROM {table_detail} d
            JOIN pemakaian p ON d.id_pemakaian = p.id
            WHERE d.{col_id} = {selected_item}
        """
        df_raw = pd.read_sql(text(q), db.bind)

        if df_raw.empty:
            st.error("Tidak ada history transaksi untuk item ini.")
            db.close()
            return

        df_freq = df_raw['jumlah_pakai'].value_counts().reset_index()
        df_freq.columns = ['jumlah_pakai', 'frekuensi']

        # Jalankan Monte Carlo bulanan (4 minggu × 12 bulan = 48 periode)
        df_prob, df_monthly, stats = run_monte_carlo_monthly(df_freq, params, n_months=12)

        # --- Hasil & Rekomendasi ---
        st.markdown("---")
        st.subheader("📊 Hasil Prediksi")

        # Info item
        Model = Bahan if itype == "bahan" else Alat
        curr = db.query(Model).filter(Model.id == selected_item).first()
        item_name = curr.nama_bahan if itype == "bahan" else curr.nama_alat
        stok_now = curr.stok_awal
        satuan = curr.satuan

        # Tampilkan tabel format Bulan × Minggu ke-1..4
        st.markdown(f"**Tabel Prediksi Kebutuhan {item_name}**")
        st.dataframe(df_monthly, use_container_width=True, hide_index=True)

        # Statistik & Status Stok
        st.markdown("---")
        st.subheader("📋 Analisis & Rekomendasi")

        col_res1, col_res2 = st.columns(2)
        with col_res1:
            # periode
            st.metric("Estimasi Total Kebutuhan (12 Bulan)", f"{stats['total_predicted']:.0f} {satuan}")
            st.metric("Rata-rata per Periode (Minggu)", f"{stats['avg_per_periode']:.2f} {satuan}")

        with col_res2:
            # Safety stock = rata-rata × 4 periode (1 bulan buffer)
            buffer = stats['avg_per_periode'] * 4

            st.markdown("**Status Stok:**")
            st.write(f"- Stok Saat Ini: **{stok_now} {satuan}**")
            st.write(f"- Safety Stock (Saran 1 Bulan): **{buffer:.0f} {satuan}**")

            if stok_now > buffer:
                st.success("✅ Stok Aman untuk periode berikutnya.")
            else:
                st.error("⚠️ Stok Kritis! Disarankan segera melakukan restock.")

        # Grafik Prediksi Bulanan
        st.markdown("---")
        st.subheader(f"📈 Grafik Proyeksi Kebutuhan {item_name}")

        df_chart = df_monthly[df_monthly["Bulan"] != "Total Pemakaian"].copy()
        week_cols = ["Minggu ke-1", "Minggu ke-2", "Minggu ke-3", "Minggu ke-4"]

        fig = go.Figure()
        colors = ["#0f52ba", "#4a90d9", "#7fb3e8", "#b5d4f1"]
        for i, col in enumerate(week_cols):
            fig.add_trace(go.Bar(
                name=col,
                x=df_chart["Bulan"].tolist(),
                y=df_chart[col].tolist(),
                marker_color=colors[i]
            ))

        fig.update_layout(
            barmode='group',
            title=f"Proyeksi Kebutuhan {item_name} — 4 Periode per Bulan",
            xaxis_title="Bulan",
            yaxis_title="Prediksi Kebutuhan ({})".format(satuan),
            legend_title="Periode",
            height=450
        )
        st.plotly_chart(fig, use_container_width=True)

        # Tabel Probabilitas (detail teknis)
        with st.expander("🔍 Detail Teknis: Tabel Probabilitas & Parameter LCG"):
            st.write(f"Parameter LCG: a={params['a']}, c={params['c']}, m={params['m']}, z₀={params['z0']}")
            st.dataframe(df_prob, use_container_width=True, hide_index=True)

    db.close()


# =====================================================================
# HALAMAN 5: LAPORAN (Manager)
# =====================================================================
def report_page():
    """
    Laporan menampilkan breakdown mingguan
    (Minggu ke-1 s/d Minggu ke-4 per bulan)
    """
    st.markdown("<div class='header-style'>📑 Laporan Pemakaian </div>", unsafe_allow_html=True)
    db = get_session()

    c1, c2 = st.columns(2)
    start_d = c1.date_input("Dari Tanggal", value=date(2024, 1, 1))
    end_d = c2.date_input("Sampai Tanggal", value=date.today())

    tab_b, tab_a, tab_all, tab_weekly = st.tabs([
        "📦 Laporan Bahan", "🧰 Laporan Alat",
        "📚 Gabungan", "📅 Rekapitulasi Mingguan"
    ])

    # --- Tab Bahan ---
    with tab_b:
        st.subheader("Rekapitulasi Pemakaian Bahan")
        if st.button("Tampilkan Data Bahan"):
            sql = f"""
                SELECT p.tgl_pemakaian, pr.nama_proyek, u.nama as user,
                       b.nama_bahan as item, b.kategori, d.jumlah_pakai, p.keterangan
                FROM pemakaian p
                JOIN detail_pemakaian_bahan d ON p.id = d.id_pemakaian
                JOIN bahan b ON d.id_bahan = b.id
                JOIN proyek pr ON p.id_proyek = pr.id
                JOIN users u ON p.user_id = u.id
                WHERE p.tgl_pemakaian BETWEEN '{start_d}' AND '{end_d}'
                ORDER BY p.tgl_pemakaian DESC
            """
            df = pd.read_sql(text(sql), db.bind)
            st.dataframe(df, use_container_width=True, hide_index=True)

            csv = df.to_csv(index=False).encode('utf-8')
            st.download_button("Unduh CSV (Bahan)", csv, "laporan_bahan.csv", "text/csv")

    # --- Tab Alat ---
    with tab_a:
        st.subheader("Rekapitulasi Pemakaian Alat")
        if st.button("Tampilkan Data Alat"):
            sql = f"""
                SELECT p.tgl_pemakaian, pr.nama_proyek, u.nama as user,
                       a.nama_alat as item, a.kategori, d.jumlah_pakai, p.keterangan
                FROM pemakaian p
                JOIN detail_pemakaian_alat d ON p.id = d.id_pemakaian
                JOIN alat a ON d.id_alat = a.id
                JOIN proyek pr ON p.id_proyek = pr.id
                JOIN users u ON p.user_id = u.id
                WHERE p.tgl_pemakaian BETWEEN '{start_d}' AND '{end_d}'
                ORDER BY p.tgl_pemakaian DESC
            """
            df = pd.read_sql(text(sql), db.bind)
            st.dataframe(df, use_container_width=True, hide_index=True)

            csv = df.to_csv(index=False).encode('utf-8')
            st.download_button("Unduh CSV (Alat)", csv, "laporan_alat.csv", "text/csv")

    # --- Tab Gabungan ---
    with tab_all:
        st.subheader("Rekapitulasi Gabungan (Bahan + Alat)")
        if st.button("Tampilkan Data Gabungan"):
            sql = f"""
                SELECT p.tgl_pemakaian, pr.nama_proyek, u.nama as user,
                       'Bahan' as jenis, b.nama_bahan as item, b.kategori,
                       d.jumlah_pakai, p.keterangan
                FROM pemakaian p
                JOIN detail_pemakaian_bahan d ON p.id = d.id_pemakaian
                JOIN bahan b ON d.id_bahan = b.id
                JOIN proyek pr ON p.id_proyek = pr.id
                JOIN users u ON p.user_id = u.id
                WHERE p.tgl_pemakaian BETWEEN '{start_d}' AND '{end_d}'

                UNION ALL

                SELECT p.tgl_pemakaian, pr.nama_proyek, u.nama as user,
                       'Alat' as jenis, a.nama_alat as item, a.kategori,
                       d2.jumlah_pakai, p.keterangan
                FROM pemakaian p
                JOIN detail_pemakaian_alat d2 ON p.id = d2.id_pemakaian
                JOIN alat a ON d2.id_alat = a.id
                JOIN proyek pr ON p.id_proyek = pr.id
                JOIN users u ON p.user_id = u.id
                WHERE p.tgl_pemakaian BETWEEN '{start_d}' AND '{end_d}'

                ORDER BY tgl_pemakaian DESC
            """
            df = pd.read_sql(text(sql), db.bind)
            st.dataframe(df, use_container_width=True, hide_index=True)

            csv = df.to_csv(index=False).encode('utf-8')
            st.download_button("Unduh CSV (Gabungan)", csv, "laporan_gabungan.csv", "text/csv")

    # --- Tab Rekapitulasi Mingguan ---
    with tab_weekly:
        st.subheader("📅 Rekapitulasi Pemakaian Per Minggu")
        st.caption("Menampilkan data pemakaian dalam format Bulan × Minggu ke-1 s/d Minggu ke-4")

        col_yr, col_cat = st.columns(2)
        with col_yr:
            current_year = date.today().year
            year_opts = list(range(current_year, current_year - 5, -1))
            rpt_year = st.selectbox("Tahun:", year_opts, index=0, key="rpt_year")
        with col_cat:
            rpt_cat = st.selectbox(
                "Kategori:",
                ["Bahan: Solvent", "Bahan: Padatan", "Alat: Consumable", "Semua Bahan"],
                key="rpt_cat"
            )

        # Mapping
        if "Solvent" in rpt_cat:
            r_itype, r_ifilter = "bahan", "Solvent"
        elif "Padatan" in rpt_cat:
            r_itype, r_ifilter = "bahan", "Padatan"
        elif "Consumable" in rpt_cat:
            r_itype, r_ifilter = "alat", "Consumable"
        else:
            r_itype, r_ifilter = "bahan", None

        # Pilihan item spesifik (opsional)
        if r_itype == "bahan":
            items_q = db.query(Bahan)
            if r_ifilter:
                items_q = items_q.filter(Bahan.kategori == r_ifilter)
            items_list = items_q.all()
            item_opts = {0: "-- Semua Item --"}
            item_opts.update({b.id: b.nama_bahan for b in items_list})
        else:
            items_q = db.query(Alat)
            if r_ifilter:
                items_q = items_q.filter(Alat.kategori == r_ifilter)
            items_list = items_q.all()
            item_opts = {0: "-- Semua Item --"}
            item_opts.update({a.id: a.nama_alat for a in items_list})

        sel_item_rpt = st.selectbox(
            "Filter Item (opsional):",
            list(item_opts.keys()),
            format_func=lambda x: item_opts[x],
            key="rpt_item"
        )

        if st.button("📊 Tampilkan Rekapitulasi Mingguan", type="primary"):
            item_id_filter = sel_item_rpt if sel_item_rpt != 0 else None

            df_weekly_rpt = build_weekly_usage_table(
                db, item_type=r_itype, category_filter=r_ifilter,
                item_id=item_id_filter, year=rpt_year
            )

            if not df_weekly_rpt.empty:
                st.dataframe(df_weekly_rpt, use_container_width=True)

                # Grafik
                df_chart = df_weekly_rpt[df_weekly_rpt.index != "Total Pemakaian"].copy()
                week_cols = ["Minggu ke-1", "Minggu ke-2", "Minggu ke-3", "Minggu ke-4"]

                fig = go.Figure()
                colors = ["#0f52ba", "#4a90d9", "#7fb3e8", "#b5d4f1"]
                for i, col in enumerate(week_cols):
                    fig.add_trace(go.Bar(
                        name=col,
                        x=df_chart.index.tolist(),
                        y=df_chart[col].tolist(),
                        marker_color=colors[i]
                    ))

                fig.update_layout(
                    barmode='group',
                    title=f"Rekapitulasi Pemakaian Mingguan — {rpt_cat} ({rpt_year})",
                    xaxis_title="Bulan",
                    yaxis_title="Jumlah Pemakaian",
                    legend_title="Periode",
                    height=450
                )
                st.plotly_chart(fig, use_container_width=True)

                # Download
                csv = df_weekly_rpt.to_csv().encode('utf-8')
                st.download_button(
                    "📥 Unduh CSV (Rekapitulasi Mingguan)",
                    csv, f"rekap_mingguan_{rpt_year}.csv", "text/csv"
                )
            else:
                st.info("Tidak ada data pemakaian untuk filter yang dipilih.")

    db.close()


# =====================================================================
# HALAMAN 6: MANAJEMEN USER (Manager only)
# =====================================================================
def user_management_page():
    st.markdown(
        "<div class='header-style'>👥 Manajemen User (Reset Password)</div>",
        unsafe_allow_html=True
    )

    if st.session_state.user_role != "manager":
        st.error("Akses ditolak.")
        return

    db = get_session()

    users = db.query(User).order_by(User.username.asc()).all()
    if not users:
        st.info("Belum ada user.")
        db.close()
        return

    user_opts = {u.id: f"{u.username} ({u.nama}) - {u.role}" for u in users}
    sel_id = st.selectbox(
        "Pilih User", options=list(user_opts.keys()),
        format_func=lambda x: user_opts[x]
    )

    col1, col2 = st.columns([1, 2])

    with col1:
        if st.button("Buat Reset Code (24 jam)", type="primary", use_container_width=True):
            target = db.query(User).filter(User.id == sel_id).first()
            if not target:
                st.error("User tidak ditemukan.")
            else:
                code = "".join([str(secrets.randbelow(10)) for _ in range(6)])
                target.reset_code_hash = hash_text(code)
                target.reset_code_expiry = datetime.now() + timedelta(hours=24)
                db.commit()

                st.success("Reset code berhasil dibuat. Salin dan kirim ke user (sekali pakai).")
                st.code(code, language="text")

    with col2:
        st.caption("Status Reset Code")
        target = db.query(User).filter(User.id == sel_id).first()
        if target and target.reset_code_hash and target.reset_code_expiry:
            st.write(f"Reset code aktif sampai: **{target.reset_code_expiry}**")
            st.warning("Kode tidak bisa ditampilkan lagi. Buat ulang jika user kehilangan.")
        else:
            st.write("Tidak ada reset code aktif untuk user ini.")

    st.markdown("---")
    st.caption("Opsional: force reset (tanpa kode).")
    with st.form("force_reset_form"):
        new_pw = st.text_input("Set Password Baru", type="password", key="force_pw")
        if st.form_submit_button("Set Password User Ini", type="secondary"):
            if not new_pw:
                st.error("Password tidak boleh kosong.")
            else:
                target = db.query(User).filter(User.id == sel_id).first()
                target.password = hash_pass(new_pw)
                target.reset_code_hash = None
                target.reset_code_expiry = None
                db.commit()
                st.success("Password user berhasil di-set ulang.")

    db.close()


# =====================================================================
# MAIN ROUTING
# =====================================================================
if st.session_state.logged_in:
    from streamlit_option_menu import option_menu

    role = st.session_state.user_role
    username = st.session_state.username

    with st.sidebar:
        st.title("🔬 Lab System")
        st.caption(f"User: {username} ({role})")
        st.markdown("---")

        if role == 'manager':
            # Manager Dashboard
            menu_opts = ["Dashboard", "Data Master", "Prediksi", "Laporan", "Keluar"]
            icons = ["speedometer2", "database", "graph-up-arrow", "file-text", "box-arrow-left"]
        elif role == 'purchasing':
            # Hapus Dashboard dari menu Purchasing
            menu_opts = ["Data Master", "Input Logistik", "Keluar"]
            icons = ["pencil-square", "cart-plus", "box-arrow-left"]
        else:
            menu_opts = ["Keluar"]
            icons = ["box-arrow-left"]

        selected = option_menu(
            "Navigasi", menu_opts, icons=icons,
            menu_icon="cast", default_index=0
        )

    if selected == "Dashboard":
        dashboard_page()
    elif selected == "Data Master":
        master_data_page()
    elif selected == "Input Logistik":
        transaction_page()
    elif selected == "Prediksi":
        prediction_page()
    elif selected == "Laporan":
        report_page()
    elif selected == "Manajemen User":
        user_management_page()
    elif selected == "Keluar":
        logout()

else:
    login_page()