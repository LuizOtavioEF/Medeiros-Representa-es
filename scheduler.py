"""
scheduler.py — Orquestra download (diário) e consolidação (semanal)
"""

import logging
import schedule
import time
from datetime import datetime

from agent import run_agent
import consolidar
import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("rpa_erp.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)


def pipeline_diario():
    """Baixa os relatórios do ano anterior e ano atual do ERP."""
    log.info("=" * 60)
    log.info("PIPELINE DIÁRIO — %s", datetime.now().strftime("%d/%m/%Y %H:%M:%S"))
    log.info("=" * 60)

    arquivos = run_agent()

    if not arquivos:
        log.error("Nenhum arquivo baixado.")
        return

    log.info("Download concluído: %d arquivo(s)", len(arquivos))
    for f in arquivos:
        log.info("  %s", f)

    # Após download, reconsolida automaticamente
    pipeline_semanal()


def pipeline_semanal():
    """Reprocessa todos os arquivos e atualiza carteira + faturado."""
    log.info("=" * 60)
    log.info("CONSOLIDAÇÃO — %s", datetime.now().strftime("%d/%m/%Y %H:%M:%S"))
    log.info("=" * 60)

    resultado = consolidar.consolidar(config.FORMS_DIR)
    if resultado:
        log.info("Consolidação concluída!")
        log.info("  Carteira : %s", resultado["carteira"])
        log.info("  Faturado : %s", resultado["faturado"])
        # Push automático para o GitHub
        import subprocess
        log.info("Enviando dados atualizados para o GitHub...")
        subprocess.run(["git", "add", "data/historico_carteira.csv", "data/historico_faturado.csv"], check=True)
        subprocess.run(["git", "commit", "-m", f"atualiza dados {datetime.now().strftime('%d/%m/%Y')}"], check=True)
        subprocess.run(["git", "push"], check=True)
        log.info("GitHub atualizado!")
    else:
        log.error("Falha na consolidação.")


def main():
    log.info("Agendador iniciado.")
    log.info("  Diário  : todos os dias às %s", config.SCHEDULE_TIME)
    log.info("  Semanal : todo domingo às %s", config.SCHEDULE_WEEKLY)

    schedule.every().day.at(config.SCHEDULE_TIME).do(pipeline_diario)
    schedule.every().sunday.at(config.SCHEDULE_WEEKLY).do(pipeline_semanal)

    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    import sys

    if "--now" in sys.argv:
        pipeline_diario()
    elif "--consolidar" in sys.argv:
        pipeline_semanal()
    else:
        main()
