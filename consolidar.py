"""
consolidar.py — Processa TODOS os arquivos fat*.cliente.fab de uma pasta
e gera dois históricos:
  - historico_carteira.csv   → tudo (pedidos faturados + em aberto)
  - historico_faturado.csv   → só pedidos efetivamente faturados (deduplicados)

Uso:
    python consolidar.py                          # usa FORMS_DIR do config.py
    python consolidar.py "C:/caminho/da/pasta"    # pasta customizada
"""

import os
import sys
import glob
import logging
import re
import pandas as pd
from datetime import datetime

import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("consolidar.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)


# ─── Parse hierárquico ────────────────────────────────────────────────────────

def _parse_arquivo(csv_path: str) -> pd.DataFrame:
    rows = []
    cliente_atual = None

    for enc in ["utf-8", "latin-1", "cp1252"]:
        try:
            lines = open(csv_path, encoding=enc).readlines()
            break
        except UnicodeDecodeError:
            continue
    else:
        log.error("Não foi possível decodificar: %s", csv_path)
        return pd.DataFrame()

    for line in lines:
        line = line.strip()
        if not line:
            continue
        parts = line.split(";")

        if parts[0].strip() == "Cliente" and len(parts) == 2:
            cliente_atual = parts[1].strip()
            continue
        if parts[0].strip() == "Representada":
            continue
        if parts[0].strip() == "-" and "TOTAL" in line:
            continue
        if cliente_atual and len(parts) >= 7 and parts[0].strip() != "-":
            rows.append({
                "cliente":            cliente_atual,
                "representada":       parts[0].strip(),
                "pedido":             parts[1].strip(),
                "data_emissao":       parts[2].strip(),
                "data_prev":          parts[3].strip(),
                "valor":              parts[4].strip(),
                "faturado":           parts[5].strip(),
                "qtde":               parts[6].strip(),
                "melhor_compra":      parts[7].strip() if len(parts) > 7 else "",
                "data_melhor_compra": parts[8].strip() if len(parts) > 8 else "",
            })

    return pd.DataFrame(rows)


# ─── Conversão de tipos ───────────────────────────────────────────────────────

def _to_float(serie: pd.Series) -> pd.Series:
    return (
        serie.astype(str)
        .str.replace(r"R\$\s*", "", regex=True)
        .str.replace(r"\.", "", regex=True)
        .str.replace(",", ".", regex=False)
        .str.strip()
        .pipe(pd.to_numeric, errors="coerce")
    )


def _converter_tipos(df: pd.DataFrame) -> pd.DataFrame:
    df["valor_num"]       = _to_float(df["valor"])
    df["qtde_num"]        = pd.to_numeric(df["qtde"], errors="coerce")
    df["data_emissao_dt"] = pd.to_datetime(df["data_emissao"], dayfirst=True, errors="coerce")
    df["faturado_dt"]     = pd.to_datetime(df["faturado"],     dayfirst=True, errors="coerce")
    df["faturado_flag"]   = df["faturado_dt"].notna()   # True = faturado
    df["ano"]             = df["data_emissao_dt"].dt.year.astype("Int64")
    df["mes"]             = df["data_emissao_dt"].dt.month.astype("Int64")
    df["mes_nome"]        = df["data_emissao_dt"].dt.strftime("%b/%Y")
    return df


# ─── Processar um arquivo ─────────────────────────────────────────────────────

def processar_arquivo(csv_path: str) -> pd.DataFrame:
    """Lê e converte um arquivo. Retorna DataFrame COMPLETO (sem filtros ainda)."""
    nome = os.path.basename(csv_path)
    match = re.search(r"(\d{4})", nome)
    ano_arquivo = int(match.group(1)) if match else 0

    df = _parse_arquivo(csv_path)
    if df.empty:
        log.warning("  Nenhuma linha extraída de: %s", nome)
        return pd.DataFrame()

    df = _converter_tipos(df)
    df["ano_arquivo"]     = ano_arquivo
    df["_arquivo_origem"] = nome

    log.info("  %s → %d linhas | R$ %.2f (bruto total)",
             nome, len(df), df["valor_num"].sum())
    return df


# ─── Gerar carteira (tudo, dedup por pedido+ano) ─────────────────────────────

def _gerar_carteira(df: pd.DataFrame) -> pd.DataFrame:
    """
    Carteira completa: faturados + em aberto.
    Dedup: pedidos parcelados aparecem múltiplas vezes → mantém a linha mais recente
    (último faturamento ou, se nenhum, a última data de emissão).
    """
    # Para parcelados faturados, mantém o mais recente; para em aberto, mantém 1 linha
    df_sorted = df.sort_values(
        ["faturado_dt", "data_emissao_dt"], ascending=[False, False]
    )
    df_dedup = df_sorted.drop_duplicates(
        subset=["pedido", "ano_arquivo"], keep="first"
    ).sort_values(["ano_arquivo", "data_emissao_dt"]).reset_index(drop=True)

    log.info("Carteira: %d pedidos únicos | R$ %.2f",
             len(df_dedup), df_dedup["valor_num"].sum())
    return df_dedup


# ─── Gerar faturado (só faturados, dedup) ────────────────────────────────────

def _gerar_faturado(df: pd.DataFrame) -> pd.DataFrame:
    """
    Receita realizada: apenas pedidos com data de faturamento,
    deduplicados (parcelados contam 1 vez pelo valor original do pedido).
    """
    df_fat = df[df["faturado_flag"]].copy()

    # Dedup: mesmo pedido+ano → mantém faturamento mais recente
    df_fat = (
        df_fat.sort_values("faturado_dt", ascending=False)
              .drop_duplicates(subset=["pedido", "ano_arquivo"], keep="first")
              .sort_values(["ano_arquivo", "data_emissao_dt"])
              .reset_index(drop=True)
    )

    log.info("Faturado: %d pedidos únicos | R$ %.2f",
             len(df_fat), df_fat["valor_num"].sum())
    return df_fat


# ─── Consolidação principal ───────────────────────────────────────────────────

def consolidar(pasta: str) -> dict | None:
    os.makedirs(config.CLEAN_DIR, exist_ok=True)

    padroes = [
        os.path.join(pasta, "fat*.cliente.fab"),
        os.path.join(pasta, "fat*.csv"),
        os.path.join(pasta, "FAT*.cliente.fab"),
    ]
    arquivos = sorted(set(
        arq for p in padroes for arq in glob.glob(p)
    ))

    if not arquivos:
        log.error("Nenhum arquivo encontrado em: %s", pasta)
        return None

    log.info("=" * 65)
    log.info("Consolidando %d arquivo(s) de: %s", len(arquivos), pasta)
    log.info("=" * 65)

    frames = []
    resumo = []

    for arq in arquivos:
        log.info("Processando: %s", os.path.basename(arq))
        df = processar_arquivo(arq)
        if not df.empty:
            frames.append(df)
            resumo.append(os.path.basename(arq))

    if not frames:
        log.error("Nenhum dado extraído.")
        return None

    df_all = pd.concat(frames, ignore_index=True)
    df_all["_consolidado_em"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ── Gerar os dois CSVs ──────────────────────────────────────────────────
    log.info("")
    log.info("Gerando CARTEIRA (faturado + em aberto)...")
    df_carteira = _gerar_carteira(df_all)

    log.info("Gerando FATURADO (receita realizada)...")
    df_faturado = _gerar_faturado(df_all)

    # Caminhos de saída (ao lado do master original)
    carteira_path = config.MASTER_FILE.replace(
        "historico_master.csv", "historico_carteira.csv"
    )
    faturado_path = config.MASTER_FILE.replace(
        "historico_master.csv", "historico_faturado.csv"
    )
    # Fallback se o nome do MASTER_FILE for diferente
    base = os.path.dirname(config.MASTER_FILE)
    carteira_path = os.path.join(base, "historico_carteira.csv")
    faturado_path = os.path.join(base, "historico_faturado.csv")

    df_carteira.to_csv(carteira_path, index=False, encoding="utf-8", sep=";")
    df_faturado.to_csv(faturado_path, index=False, encoding="utf-8", sep=";")

    # ── Relatório final ─────────────────────────────────────────────────────
    anos = sorted(df_all["ano_arquivo"].unique())

    log.info("")
    log.info("╔═══════════════════════════════════════════════════════════════╗")
    log.info("║                   CONSOLIDAÇÃO CONCLUÍDA                     ║")
    log.info("╠═══════════════════════════════════════════════════════════════╣")
    log.info("║  Anos cobertos: %-47s  ║", ", ".join(str(a) for a in anos))
    log.info("╠═════════════════════════════════╦═══════════╦════════════════╣")
    log.info("║  Visão                          ║  Pedidos  ║  Valor Total   ║")
    log.info("╠═════════════════════════════════╬═══════════╬════════════════╣")
    log.info("║  Carteira (faturado + em aberto)║  %-8d  ║ R$ %-11.2f  ║",
             len(df_carteira), df_carteira["valor_num"].sum())
    log.info("║  Faturado realizado             ║  %-8d  ║ R$ %-11.2f  ║",
             len(df_faturado), df_faturado["valor_num"].sum())
    log.info("╠═════════════════════════════════╩═══════════╩════════════════╣")
    log.info("║  historico_carteira.csv → %-38s  ║", os.path.basename(carteira_path))
    log.info("║  historico_faturado.csv → %-38s  ║", os.path.basename(faturado_path))
    log.info("╚═══════════════════════════════════════════════════════════════╝")

    return {"carteira": carteira_path, "faturado": faturado_path}


# ─── Execução ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    pasta = sys.argv[1] if len(sys.argv) > 1 else config.FORMS_DIR
    resultado = consolidar(pasta)
    if resultado:
        print(f"\nCarteira : {resultado['carteira']}")
        print(f"Faturado : {resultado['faturado']}")
    else:
        print("\nFalha na consolidação. Verifique os logs.")
