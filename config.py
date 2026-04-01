"""
config.py — Configurações centrais do agente RPA
Edite apenas este arquivo para adaptar ao seu sistema.
"""

import os
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ─── URLs ─────────────────────────────────────────────────────────────────────
LOGIN_HOME  = "http://www.formesonline.com.br/default.asp"
LOGIN_URL   = "http://www.formesonline.com.br/srep_bb/logon.aspx"

# ─── Credenciais ──────────────────────────────────────────────────────────────
USERNAME    = "LUIZ"
PASSWORD    = "1234"        # ← preencha aqui
EMPRESA     = "MEDEIROS COMERCIO E REPRESENTACOES LTDA"

# ─── Pastas ───────────────────────────────────────────────────────────────────
# Pasta do OneDrive onde ficam os fat*.cliente.fab
FORMS_DIR   = r"C:\Users\Luiz Otávio\OneDrive\Medeiros Repre\Forms"

# Pastas internas do projeto
RAW_DIR     = os.path.join(BASE_DIR, "data", "raw")
CLEAN_DIR   = os.path.join(BASE_DIR, "data", "clean")
MASTER_FILE = os.path.join(BASE_DIR, "data", "historico_master.csv")

# ─── Configurações do CSV ─────────────────────────────────────────────────────
CSV_ENCODING    = "utf-8"
CSV_SEPARATOR   = ";"
CSV_SKIPROWS    = 0
COLUMN_RENAME   = {}
NUMERIC_COLS    = []
DATE_COL        = None

# ─── Agendamento ──────────────────────────────────────────────────────────────
SCHEDULE_TIME   = "07:00"    # download diário (HH:MM)
SCHEDULE_WEEKLY = "08:00"    # consolidação semanal — todo domingo (HH:MM)
