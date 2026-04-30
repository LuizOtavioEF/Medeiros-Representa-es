"""
consolidar.py — Processa arquivos fat*.cliente.fab e fat*.vendedor.fab
e gera três históricos:
  - historico_carteira.csv   → tudo (pedidos faturados + em aberto)
  - historico_faturado.csv   → só pedidos efetivamente faturados (deduplicados)
  - historico_vendedor.csv   → sintético por vendedor × representada × mês

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

MESES_PT = {
    "janeiro": 1,  "fevereiro": 2, "março": 3,    "marco": 3,
    "abril": 4,    "maio": 5,      "junho": 6,     "julho": 7,
    "agosto": 8,   "setembro": 9,  "outubro": 10,  "novembro": 11,
    "dezembro": 12,
    # abreviações
    "jan": 1, "fev": 2, "mar": 3, "abr": 4, "mai": 5, "jun": 6,
    "jul": 7, "ago": 8, "set": 9, "out": 10, "nov": 11, "dez": 12,
}

NOMES_MESES = ["", "Jan", "Fev", "Mar", "Abr", "Mai", "Jun",
               "Jul", "Ago", "Set", "Out", "Nov", "Dez"]


# ─── Utilitários ──────────────────────────────────────────────────────────────

def _abrir_linhas(path: str) -> list[str]:
    for enc in ["utf-8", "latin-1", "cp1252"]:
        try:
            return open(path, encoding=enc).readlines()
        except UnicodeDecodeError:
            continue
    log.error("Não foi possível decodificar: %s", path)
    return []


def _to_float(serie: pd.Series) -> pd.Series:
    return (
        serie.astype(str)
        .str.replace(r"R\$\s*", "", regex=True)
        .str.replace(r"\.", "", regex=True)
        .str.replace(",", ".", regex=False)
        .str.strip()
        .pipe(pd.to_numeric, errors="coerce")
    )


def _parse_mes_texto(texto: str):
    """
    Extrai (mes_num, ano) de strings como 'Abril/2026', '04/2026', 'Abril 2026'.
    Retorna (None, None) se não conseguir.
    """
    texto_low = texto.lower().strip()
    ano_match = re.search(r"(\d{4})", texto)
    ano = int(ano_match.group(1)) if ano_match else None

    for nome, num in MESES_PT.items():
        if nome in texto_low:
            return num, ano

    m = re.match(r"^(\d{1,2})[/\-](\d{4})$", texto.strip())
    if m:
        return int(m.group(1)), int(m.group(2))

    return None, ano


# ─── Parser do arquivo CLIENTE (relatório detalhado) ─────────────────────────

def _parse_arquivo_cliente(csv_path: str) -> pd.DataFrame:
    rows = []
    cliente_atual = None

    lines = _abrir_linhas(csv_path)
    if not lines:
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


def _converter_tipos_cliente(df: pd.DataFrame) -> pd.DataFrame:
    df["valor_num"]       = _to_float(df["valor"])
    df["qtde_num"]        = pd.to_numeric(df["qtde"], errors="coerce")
    df["data_emissao_dt"] = pd.to_datetime(df["data_emissao"], dayfirst=True, errors="coerce")
    df["faturado_dt"]     = pd.to_datetime(df["faturado"],     dayfirst=True, errors="coerce")
    df["faturado_flag"]   = df["faturado_dt"].notna()
    df["ano"]             = df["data_emissao_dt"].dt.year.astype("Int64")
    df["mes"]             = df["data_emissao_dt"].dt.month.astype("Int64")
    df["mes_nome"]        = df["data_emissao_dt"].dt.strftime("%b/%Y")
    return df


def processar_arquivo_cliente(csv_path: str) -> pd.DataFrame:
    nome = os.path.basename(csv_path)
    match = re.search(r"(\d{4})", nome)
    ano_arquivo = int(match.group(1)) if match else 0

    df = _parse_arquivo_cliente(csv_path)
    if df.empty:
        log.warning("  Nenhuma linha extraída de: %s", nome)
        return pd.DataFrame()

    df = _converter_tipos_cliente(df)
    df["ano_arquivo"]     = ano_arquivo
    df["_arquivo_origem"] = nome

    log.info("  %s → %d linhas | R$ %.2f (bruto total)",
             nome, len(df), df["valor_num"].sum())
    return df


# ─── Parser do arquivo VENDEDOR (relatório sintético) ────────────────────────

def _parse_arquivo_vendedor(csv_path: str) -> pd.DataFrame:
    """
    Lê um arquivo fat{ano}.vendedor.fab (export Excel do relatório sintético
    por Vendedor com Total Mensal P/Ven.) e retorna DataFrame com:
      vendedor, representada, mes, ano, valor_num, qtde_num, mes_nome
    """
    nome = os.path.basename(csv_path)
    match = re.search(r"(\d{4})", nome)
    ano_arquivo = int(match.group(1)) if match else 0

    lines = _abrir_linhas(csv_path)
    if not lines:
        return pd.DataFrame()

    # Log das primeiras linhas para debug de formato
    log.info("  Primeiras linhas de %s:", nome)
    for l in lines[:8]:
        log.info("    %s", l.rstrip())

    rows = []
    mes_num     = None
    ano_linha   = None
    vendedor_atual = None

    # Palavras-chave que indicam linhas a pular
    SKIP_PREFIXOS = {
        "representada", "total vendedor", "total mês", "total mes",
        "tot. geral", "tot.geral", "total geral", "total mês",
        "total do mês", "total do mes",
    }

    for line in lines:
        line_strip = line.strip()
        if not line_strip:
            continue

        parts = [p.strip() for p in line_strip.split(";")]
        p0 = parts[0]
        p0_low = p0.lower()

        # ── Detecta cabeçalho de Mês ──────────────────────────────────────
        if re.match(r"^m[eê]s", p0_low, re.I):
            # Pode ser "Mês;Abril/2026" ou "Mês: Abril/2026" ou apenas "Mês"
            texto_mes = parts[1] if len(parts) >= 2 else p0
            if ":" in p0 and len(parts) == 1:
                texto_mes = p0.split(":", 1)[1].strip()
            mes_num, ano_linha = _parse_mes_texto(texto_mes)
            vendedor_atual = None  # Reseta ao trocar de mês
            continue

        # ── Detecta Vendedor ──────────────────────────────────────────────
        if p0_low in ("vendedor", "vendedor:") or p0_low.startswith("vendedor:"):
            nome_vend = parts[1] if len(parts) >= 2 else p0.split(":", 1)[-1].strip()
            vendedor_atual = nome_vend
            continue

        # ── Pula linhas de total/cabeçalho ───────────────────────────────
        if any(p0_low.startswith(s) for s in SKIP_PREFIXOS):
            continue

        # ── Linha de dados: representada;valor;qtde ───────────────────────
        if (
            vendedor_atual
            and mes_num
            and len(parts) >= 2
            and p0  # tem representada
        ):
            valor_raw = parts[1] if len(parts) >= 2 else ""
            qtde_raw  = parts[2] if len(parts) >= 3 else "0"

            # Valida que segunda coluna parece um número (valor monetário)
            valor_test = (
                valor_raw.replace("R$", "")
                         .replace(".", "")
                         .replace(",", "")
                         .replace(" ", "")
                         .strip()
            )
            if not valor_test or not re.match(r"^\d+$", valor_test):
                continue

            rows.append({
                "vendedor":      vendedor_atual,
                "representada":  p0,
                "valor_raw":     valor_raw,
                "qtde_raw":      qtde_raw,
                "mes":           mes_num,
                "ano":           ano_linha or ano_arquivo,
                "ano_arquivo":   ano_arquivo,
            })

    if not rows:
        log.warning("  Nenhuma linha de vendedor extraída de: %s", nome)
        log.warning("  Total de linhas no arquivo: %d — verifique formato", len(lines))
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df["valor_num"] = _to_float(df["valor_raw"])
    df["qtde_num"]  = pd.to_numeric(df["qtde_raw"], errors="coerce").fillna(0).astype(int)
    df["mes_nome"]  = df.apply(
        lambda r: f"{NOMES_MESES[int(r['mes'])]}/{int(r['ano'])}"
        if pd.notna(r["mes"]) and 1 <= int(r["mes"]) <= 12 else "",
        axis=1,
    )
    df = df.drop(columns=["valor_raw", "qtde_raw"])
    df["_arquivo_origem"] = nome

    log.info(
        "  %s → %d linhas de vendedor | R$ %.2f",
        nome, len(df), df["valor_num"].sum(),
    )
    return df


# ─── Geração dos CSVs de cliente ─────────────────────────────────────────────

def _gerar_carteira(df: pd.DataFrame) -> pd.DataFrame:
    df_sorted = df.sort_values(
        ["faturado_dt", "data_emissao_dt"], ascending=[False, False]
    )
    df_dedup = (
        df_sorted
        .drop_duplicates(subset=["pedido", "ano_arquivo"], keep="first")
        .sort_values(["ano_arquivo", "data_emissao_dt"])
        .reset_index(drop=True)
    )
    log.info("Carteira: %d pedidos únicos | R$ %.2f",
             len(df_dedup), df_dedup["valor_num"].sum())
    return df_dedup


def _gerar_faturado(df: pd.DataFrame) -> pd.DataFrame:
    df_fat = df[df["faturado_flag"]].copy()
    df_fat = (
        df_fat
        .sort_values("faturado_dt", ascending=False)
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
    base = os.path.dirname(config.MASTER_FILE)

    # ── Arquivos CLIENTE ────────────────────────────────────────────────────
    padroes_cli = [
        os.path.join(pasta, "fat*.cliente.fab"),
        os.path.join(pasta, "FAT*.cliente.fab"),
        os.path.join(pasta, "fat*.csv"),
    ]
    arqs_cli = sorted(set(a for p in padroes_cli for a in glob.glob(p)))

    # ── Arquivos VENDEDOR ───────────────────────────────────────────────────
    padroes_vend = [
        os.path.join(pasta, "fat*.vendedor.fab"),
        os.path.join(pasta, "FAT*.vendedor.fab"),
    ]
    arqs_vend = sorted(set(a for p in padroes_vend for a in glob.glob(p)))

    if not arqs_cli and not arqs_vend:
        log.error("Nenhum arquivo encontrado em: %s", pasta)
        return None

    log.info("=" * 65)
    log.info("Consolidando %d cliente(s) + %d vendedor(es) em: %s",
             len(arqs_cli), len(arqs_vend), pasta)
    log.info("=" * 65)

    # ── Processa arquivos CLIENTE ───────────────────────────────────────────
    frames_cli = []
    for arq in arqs_cli:
        log.info("Processando cliente: %s", os.path.basename(arq))
        df = processar_arquivo_cliente(arq)
        if not df.empty:
            frames_cli.append(df)

    df_carteira = df_faturado = pd.DataFrame()
    carteira_path = os.path.join(base, "historico_carteira.csv")
    faturado_path = os.path.join(base, "historico_faturado.csv")

    if frames_cli:
        df_all = pd.concat(frames_cli, ignore_index=True)
        df_all["_consolidado_em"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        log.info("Gerando CARTEIRA...")
        df_carteira = _gerar_carteira(df_all)

        log.info("Gerando FATURADO...")
        df_faturado = _gerar_faturado(df_all)

        df_carteira.to_csv(carteira_path, index=False, encoding="utf-8", sep=";")
        df_faturado.to_csv(faturado_path, index=False, encoding="utf-8", sep=";")
    else:
        log.warning("Nenhum arquivo cliente processado.")

    # ── Processa arquivos VENDEDOR ──────────────────────────────────────────
    frames_vend = []
    for arq in arqs_vend:
        log.info("Processando vendedor: %s", os.path.basename(arq))
        df = _parse_arquivo_vendedor(arq)
        if not df.empty:
            frames_vend.append(df)

    df_vendedor = pd.DataFrame()
    vendedor_path = os.path.join(base, "historico_vendedor.csv")

    if frames_vend:
        df_vendedor = pd.concat(frames_vend, ignore_index=True)
        df_vendedor["_consolidado_em"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        df_vendedor = df_vendedor.sort_values(
            ["ano_arquivo", "mes", "vendedor", "representada"]
        ).reset_index(drop=True)
        df_vendedor.to_csv(vendedor_path, index=False, encoding="utf-8", sep=";")
        log.info("Vendedor: %d linhas | R$ %.2f",
                 len(df_vendedor), df_vendedor["valor_num"].sum())
    else:
        log.warning("Nenhum arquivo vendedor processado.")

    # ── Relatório final ─────────────────────────────────────────────────────
    anos_cli  = sorted(df_carteira["ano_arquivo"].unique()) if not df_carteira.empty else []
    anos_vend = sorted(df_vendedor["ano_arquivo"].unique()) if not df_vendedor.empty else []

    log.info("")
    log.info("╔══════════════════════════════════════════════════════════════╗")
    log.info("║               CONSOLIDAÇÃO CONCLUÍDA                        ║")
    log.info("╠══════════════════════════════════════════════════════════════╣")
    log.info("║  Cliente anos : %-45s ║", ", ".join(str(a) for a in anos_cli))
    log.info("║  Vendedor anos: %-45s ║", ", ".join(str(a) for a in anos_vend))
    log.info("╠═════════════════════════════════╦══════════╦════════════════╣")
    log.info("║  Visão                          ║  Linhas  ║  Valor Total   ║")
    log.info("╠═════════════════════════════════╬══════════╬════════════════╣")
    if not df_carteira.empty:
        log.info("║  Carteira (fat + aberto)        ║  %-7d ║ R$ %-11.2f ║",
                 len(df_carteira), df_carteira["valor_num"].sum())
    if not df_faturado.empty:
        log.info("║  Faturado realizado             ║  %-7d ║ R$ %-11.2f ║",
                 len(df_faturado), df_faturado["valor_num"].sum())
    if not df_vendedor.empty:
        log.info("║  Vendedor (sintético)           ║  %-7d ║ R$ %-11.2f ║",
                 len(df_vendedor), df_vendedor["valor_num"].sum())
    log.info("╚═════════════════════════════════╩══════════╩════════════════╝")

    return {
        "carteira": carteira_path,
        "faturado": faturado_path,
        "vendedor": vendedor_path,
    }


# ─── Execução ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    pasta = sys.argv[1] if len(sys.argv) > 1 else config.FORMS_DIR
    resultado = consolidar(pasta)
    if resultado:
        print(f"\nCarteira : {resultado['carteira']}")
        print(f"Faturado : {resultado['faturado']}")
        print(f"Vendedor : {resultado['vendedor']}")
    else:
        print("\nFalha na consolidação. Verifique os logs.")
