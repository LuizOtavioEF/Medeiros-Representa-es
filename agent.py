import os
import logging
from datetime import datetime
from playwright.sync_api import sync_playwright
import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
log = logging.getLogger(__name__)

def _fechar_popup(page):
    try:
        btn = page.locator("text=Fechar")
        if btn.is_visible(timeout=3000):
            btn.click()
    except Exception:
        pass

def _baixar_relatorio(page, ano, pasta_destino):
    data_ini = f"01/01/{ano}"
    data_fim = f"31/12/{ano}"
    destino = os.path.join(pasta_destino, f"fat{ano}.cliente.fab")
    log.info("Baixando %d (%s a %s)...", ano, data_ini, data_fim)

    frame_menu = None
    for frame in page.frames:
        if "Menu" in frame.url:
            frame_menu = frame
            break
    if not frame_menu:
        raise Exception("Frame menu nao encontrado")

    frame_menu.click("text=Produção")
    page.wait_for_timeout(2000)
    page.wait_for_load_state("networkidle")

    frame_rel = None
    for frame in page.frames:
        if "RelatorioProducao" in frame.url:
            frame_rel = frame
            break
    if not frame_rel:
        raise Exception("Frame RelatorioProducao nao encontrado")

    log.info("  Frame: %s", frame_rel.url)

    frame_rel.click("#TXT_DTInicial", click_count=3)
    frame_rel.fill("#TXT_DTInicial", data_ini)
    log.info("  Data Inicial: %s", data_ini)

    frame_rel.click("#TXT_DTFinal", click_count=3)
    frame_rel.fill("#TXT_DTFinal", data_fim)
    log.info("  Data Final: %s", data_fim)

    if not frame_rel.is_checked("#CHK_EXCEL"):
        frame_rel.check("#CHK_EXCEL")
    log.info("  Exp. Excel marcado")

    log.info("  Clicando Imprimir...")
    frame_rel.click("#CMD_Imprimir")

    log.info("  Aguardando gerar relatorio (ate 5 min)...")
    frame_rel.wait_for_selector("text=Clique aqui para abrir o arquivo", timeout=300000)

    link = frame_rel.query_selector("a:has-text('Clique aqui para abrir o arquivo')")
    href = link.get_attribute("href")
    log.info("  Link: %s", href)

    with page.expect_download(timeout=60000) as dl_info:
        link.click()

    download = dl_info.value
    download.save_as(destino)
    log.info("  Salvo: %s", destino)
    return destino

def run_agent():
    os.makedirs(config.FORMS_DIR, exist_ok=True)
    os.makedirs(config.RAW_DIR, exist_ok=True)
    ano_atual = datetime.now().year
    anos = [ano_atual - 1, ano_atual]
    arquivos = []
    log.info("AGENTE RPA — anos: %s", anos)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=300)
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()
        try:
            page.goto(config.LOGIN_URL, wait_until="networkidle")
            page.fill("#txt_cdusuario", config.USERNAME)
            page.fill("#txt_nmsenha", config.PASSWORD)
            page.keyboard.press("Tab")
            page.wait_for_timeout(2000)
            page.click("#btn_ok")
            page.wait_for_load_state("networkidle")
            _fechar_popup(page)

            for ano in anos:
                try:
                    arq = _baixar_relatorio(page, ano, config.FORMS_DIR)
                    if arq:
                        arquivos.append(arq)
                except Exception as e:
                    log.error("Erro ano %d: %s", ano, e)
                    page.screenshot(path=os.path.join(config.BASE_DIR, f"erro_{ano}.png"))
        except Exception as e:
            log.error("Erro geral: %s", e)
            page.screenshot(path=os.path.join(config.BASE_DIR, "erro_geral.png"))
        finally:
            browser.close()

    return arquivos

if __name__ == "__main__":
    resultado = run_agent()
    print("\nBaixados:", resultado if resultado else "nenhum")