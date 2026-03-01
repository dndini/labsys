import sqlalchemy
from sqlalchemy import create_engine, Column, Integer, String, Date, Float, ForeignKey, Text, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
import hashlib

# --- Konfigurasi Database ---
DATABASE_URL = "sqlite:///lab_geoenvi_final.db"

Base = declarative_base()

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# --- Definisi Tabel ---

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    nama = Column(String)
    username = Column(String, unique=True, index=True)
    password = Column(String)
    role = Column(String)  # 'manager' atau 'purchasing'

    # Forgot Password: Reset Code (hash + expiry)
    reset_code_hash = Column(String, nullable=True)
    reset_code_expiry = Column(DateTime, nullable=True)


class Proyek(Base):
    __tablename__ = "proyek"
    id = Column(Integer, primary_key=True, index=True)
    nama_proyek = Column(String)
    tgl_mulai = Column(Date)
    tgl_selesai = Column(Date)
    deskripsi = Column(Text)


class Bahan(Base):
    __tablename__ = "bahan"
    id = Column(Integer, primary_key=True, index=True)
    nama_bahan = Column(String)
    kategori = Column(String)  # Solvent / Padatan
    satuan = Column(String)
    stok_awal = Column(Integer)
    stok_minimum = Column(Integer)
    keterangan = Column(Text)


class Alat(Base):
    __tablename__ = "alat"
    id = Column(Integer, primary_key=True, index=True)
    nama_alat = Column(String)
    kategori = Column(String)  # Consumable
    satuan = Column(String)  # pcs, set, unit, dll
    stok_awal = Column(Integer)
    stok_minimum = Column(Integer)
    keterangan = Column(Text)


class Pemakaian(Base):
    __tablename__ = "pemakaian"
    id = Column(Integer, primary_key=True, index=True)
    id_proyek = Column(Integer, ForeignKey("proyek.id"))
    tgl_pemakaian = Column(Date)
    user_id = Column(Integer, ForeignKey("users.id"))
    keterangan = Column(Text)

    proyek = relationship("Proyek")
    user = relationship("User")


class DetailPemakaianBahan(Base):
    __tablename__ = "detail_pemakaian_bahan"
    id = Column(Integer, primary_key=True, index=True)
    id_pemakaian = Column(Integer, ForeignKey("pemakaian.id"))
    id_bahan = Column(Integer, ForeignKey("bahan.id"))
    jumlah_pakai = Column(Integer)

    bahan = relationship("Bahan")


class DetailPemakaianAlat(Base):
    __tablename__ = "detail_pemakaian_alat"
    id = Column(Integer, primary_key=True, index=True)
    id_pemakaian = Column(Integer, ForeignKey("pemakaian.id"))
    id_alat = Column(Integer, ForeignKey("alat.id"))
    jumlah_pakai = Column(Integer)

    alat = relationship("Alat")


# --- Helper Functions ---

def create_default_users(db):
    """Membuat user default"""
    pw_default = hashlib.sha256("123456".encode()).hexdigest()

    if not db.query(User).filter(User.username == "manager").first():
        db.add(User(nama="Ibu Manager", username="manager", password=pw_default, role="manager"))

    if not db.query(User).filter(User.username == "purchase").first():
        db.add(User(nama="Staf Purchasing", username="purchase", password=pw_default, role="purchasing"))

    db.commit()


def init_db():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    create_default_users(db)
    db.close()


def reset_database():
    Base.metadata.drop_all(bind=engine)
    init_db()


# Jalankan init saat modul di-load
init_db()