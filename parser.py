"""
parser.py — Lê o CSV hierárquico do ERP, trata, deduplica e consolida
Correções aplicadas automaticamente:
  1. Parseia formato hierárquico (bloco por cliente)
  2. Remove pedidos sem data de faturamento
  3. Deduplica entregas parceladas (mesmo nº pedido → mantém apenas 1 linha)
  4. Converte tipos (datas, valores numéricos)
  5. Anexa ao histórico master acumulado (sem reprocessar dias já importados)
"""

import os
import logging
import pandas as pd
from datetime import datetime

import config

log = logging.getLogger(__name__)


# ─── Parsing hierárquico ──────────────────────────────────────────────────────

def _parse_hierarquico(csv_path: str) -> pd.DataFrame:
    rows = []
    cliente_atual = None
    encoding = config.CSV_ENCODING

    for enc in [encoding, "latin-1", "utf-8"]:
        try:
            lines = open(csv_path, encoding=enc).readlines()
            encoding = enc
            break
        except UnicodeDecodeError:
            continue
    else:
        log.error("Não foi possível decodificar o arquivo: %s", csv_path)
        return pd.DataFrame()

    log.info("Encoding detectado: %s", encoding)

    for line in lines:
        line = line.strip()
        if not line:
            continue
        parts = line.split(config.CSV_SEPARATOR)

        if parts[0].strip() == "Cliente" and len(parts) == 2:
            cliente_atual = parts[1].strip()
            continue
        if parts[0].strip() == "Representada":
            continue
        if parts[0].strip() == "-" and "TOTAL" in line:
            continue
        if cliente_atual and len(parts) >= 7:
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

    df = pd.DataFrame(rows)
    log.info("Linhas brutas lidas: %d", len(df))
    return df


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
    df["ano"]             = df["data_emissao_dt"].dt.year
    df["mes"]             = df["data_emissao_dt"].dt.month
    df["mes_nome"]        = df["data_emissao_dt"].dt.strftime("%b/%Y")
    return df


# ─── Correções de qualidade ───────────────────────────────────────────────────

def _filtrar_nao_faturados(df: pd.DataFrame) -> pd.DataFrame:
    """Remove linhas sem data de faturamento válida (vazio, '-', NaT)."""
    antes = len(df)
    df = df[df["faturado_dt"].notna()].copy()
    log.info("Pedidos sem faturamento removidos: %d", antes - len(df))
    return df


def _deduplicar_entregas_parceladas(df: pd.DataFrame) -> pd.DataFrame:
    """
    Pedidos parcelados repetem o valor total do pedido em cada entrega parcial.
    Para evitar soma inflada: mantém apenas a linha com a faturamento mais recente
    por número de pedido, preservando o valor original uma única vez.
    """
    antes = len(df)
    df = (
        df.sort_values("faturado_dt", ascending=False)
          .drop_duplicates(subset="pedido", keep="first")
          .sort_values("data_emissao_dt")
          .reset_index(drop=True)
    )
    removidos = antes - len(df)
    if removidos:
        log.warning(
            "Entregas parceladas deduplicadas: %d linhas removidas "
            "(pedidos com múltiplas datas de faturamento — valor contado uma vez)",
            removidos,
        )
    return df


# ─── Histórico master ─────────────────────────────────────────────────────────

def _atualizar_master(df_novo: pd.DataFrame) -> None:
    """Anexa novos pedidos ao master sem reimportar pedidos já existentes."""
    if os.path.exists(config.MASTER_FILE):
        master = pd.read_csv(config.MASTER_FILE, sep=";", encoding="utf-8", dtype=str)
        pedidos_existentes = set(master["pedido"].unique())
        df_novos_apenas = df_novo[~df_novo["pedido"].isin(pedidos_existentes)]

        if df_novos_apenas.empty:
            log.info("Nenhum pedido novo para adicionar ao master.")
            return

        master = pd.concat([master, df_novos_apenas.astype(str)], ignore_index=True)
        log.info("Master: +%d pedidos novos adicionados.", len(df_novos_apenas))
    else:
        master = df_novo.astype(str)
        log.info("Master criado com %d pedidos.", len(master))

    master.to_csv(config.MASTER_FILE, index=False, encoding="utf-8", sep=";")
    log.info("Histórico master: %d linhas totais.", len(master))


# ─── Pipeline principal ───────────────────────────────────────────────────────

def processar(csv_path: str) -> str | None:
    os.makedirs(config.RAW_DIR,   exist_ok=True)
    os.makedirs(config.CLEAN_DIR, exist_ok=True)

    log.info("─" * 60)
    log.info("Processando: %s", csv_path)

    df = _parse_hierarquico(csv_path)
    if df.empty:
        log.error("Nenhuma linha extraída.")
        return None

    df = _converter_tipos(df)

    if config.COLUMN_RENAME:
        df = df.rename(columns=config.COLUMN_RENAME)

    log.info("Antes das correções: %d linhas | R$ %.2f", len(df), df["valor_num"].sum())

    df = _filtrar_nao_faturados(df)
    df = _deduplicar_entregas_parceladas(df)

    log.info("Após correções:      %d pedidos únicos | R$ %.2f", len(df), df["valor_num"].sum())

    df["_importado_em"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    nome = os.path.basename(csv_path).replace("relatorio_", "limpo_")
    destino_limpo = os.path.join(config.CLEAN_DIR, nome)
    df.to_csv(destino_limpo, index=False, encoding="utf-8", sep=";")
    log.info("CSV limpo salvo: %s", destino_limpo)

    _atualizar_master(df)
    return destino_limpo


# ─── Execução direta ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    if len(sys.argv) < 2:
        print("Uso: python parser.py caminho/do/relatorio.csv")
        sys.exit(1)
    resultado = processar(sys.argv[1])
    print(f"\n{'CSV limpo gerado: ' + resultado if resultado else 'Falha no processamento.'}")
