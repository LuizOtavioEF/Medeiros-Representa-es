import os
import sys
import logging
import csv
import subprocess
import webbrowser
from datetime import datetime
from playwright.sync_api import sync_playwright
import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# Dashboard Streamlit Cloud
DASHBOARD_URL      = "https://medeiros-representa-es.streamlit.app"
DASHBOARD_PASSWORD = "medeiros"


def _fechar_popup(page):
    try:
        btn = page.locator("text=Fechar")
        if btn.is_visible(timeout=3000):
            btn.click()
    except Exception:
        pass


def _ir_para_producao(page):
    frame_menu = None
    for frame in page.frames:
        if "Menu" in frame.url:
            frame_menu = frame
            break
    if not frame_menu:
        raise Exception("Frame menu não encontrado")
    frame_menu.click("text=Produção")
    page.wait_for_timeout(2000)
    page.wait_for_load_state("networkidle")
    for frame in page.frames:
        if "RelatorioProducao" in frame.url:
            log.info("  Frame: %s", frame.url)
            return frame
    raise Exception("Frame RelatorioProducao não encontrado")


def _preencher_datas(frame_rel, page, data_ini, data_fim):
    frame_rel.click("#TXT_DTInicial", click_count=3)
    frame_rel.fill("#TXT_DTInicial", data_ini)
    frame_rel.press("#TXT_DTInicial", "Tab")
    page.wait_for_timeout(500)
    log.info("  Data Inicial: %s", data_ini)
    frame_rel.click("#TXT_DTFinal", click_count=3)
    frame_rel.fill("#TXT_DTFinal", data_fim)
    frame_rel.press("#TXT_DTFinal", "Tab")
    page.wait_for_timeout(500)
    log.info("  Data Final: %s", data_fim)


def _garantir_excel(frame_rel, page):
    frame_rel.uncheck("#CHK_EXCEL")
    page.wait_for_timeout(300)
    frame_rel.check("#CHK_EXCEL")
    log.info("  Exp. Excel: marcado")


def _garantir_sem_excel(frame_rel, page):
    try:
        if frame_rel.is_checked("#CHK_EXCEL"):
            frame_rel.uncheck("#CHK_EXCEL")
            page.wait_for_timeout(300)
        log.info("  Exp. Excel: desmarcado")
    except Exception:
        pass


def _toggle_checkbox_by_label(frame_rel, page, label_text, marcar):
    for fn in [
        lambda: frame_rel.get_by_label(label_text),
        lambda: frame_rel.locator(f"label:has-text('{label_text}') input"),
        lambda: frame_rel.locator("input[type='checkbox']").filter(
            has=frame_rel.locator(f":text('{label_text}')")
        ),
    ]:
        try:
            chk = fn()
            chk.wait_for(timeout=2000)
            atual = chk.is_checked()
            if marcar and not atual:
                chk.check()
            elif not marcar and atual:
                chk.uncheck()
            page.wait_for_timeout(200)
            log.info("  Checkbox '%s': %s", label_text, "✓" if marcar else "✗")
            return
        except Exception:
            continue
    log.warning("  Checkbox '%s' não encontrado", label_text)


def _configurar_form_cliente(frame_rel, page):
    page.wait_for_timeout(500)
    for fn in [
        lambda: frame_rel.locator("input[type='radio']").nth(0).check(),
        lambda: frame_rel.get_by_label("Cliente").check(),
    ]:
        try:
            fn(); page.wait_for_timeout(300); log.info("  Radio: Cliente"); break
        except Exception:
            continue
    for label in ["Total Mensal P/Rep.", "Total Mensal P/Ven.", "Total Mensal P/Est."]:
        _toggle_checkbox_by_label(frame_rel, page, label, False)


def _configurar_form_vendedor(frame_rel, page):
    page.wait_for_timeout(500)
    for fn in [
        lambda: frame_rel.locator("input[type='radio']").nth(2).check(),
        lambda: frame_rel.get_by_label("Representada").check(),
    ]:
        try:
            fn(); page.wait_for_timeout(300); log.info("  Radio: Representada"); break
        except Exception:
            continue
    _toggle_checkbox_by_label(frame_rel, page, "Total Mensal P/Rep.", False)
    _toggle_checkbox_by_label(frame_rel, page, "Total Mensal P/Ven.", True)
    _toggle_checkbox_by_label(frame_rel, page, "Total Mensal P/Est.", False)


def _baixar_relatorio_cliente(page, ano, pasta_destino):
    data_ini = f"01/01/{ano}"
    data_fim = f"31/12/{ano}"
    destino  = os.path.join(pasta_destino, f"fat{ano}.cliente.fab")
    log.info("▶ Cliente %d (%s → %s)", ano, data_ini, data_fim)
    frame_rel = _ir_para_producao(page)
    _configurar_form_cliente(frame_rel, page)
    _preencher_datas(frame_rel, page, data_ini, data_fim)
    _garantir_excel(frame_rel, page)
    log.info("  Clicando Imprimir...")
    frame_rel.click("#CMD_Imprimir")
    try:
        frame_rel.wait_for_selector("text=Clique aqui para abrir o arquivo", state="hidden", timeout=15000)
        log.info("  Link antigo removido, aguardando novo...")
    except Exception:
        log.info("  Sem link antigo, aguardando geração...")
    log.info("  Aguardando relatório (até 5 min)...")
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


def _scrape_relatorio_vendedor(page, ano, pasta_destino):
    """
    Para o relatório sintético por Vendedor NÃO usamos Excel export —
    ele não gera link de download nesse modo. Em vez disso:
    1. Clica Imprimir sem Excel marcado
    2. Aguarda a tabela HTML renderizar
    3. Extrai os dados via JavaScript
    4. Salva como CSV (;) em fat{ano}.vendedor.fab
    """
    data_ini = f"01/01/{ano}"
    data_fim = f"31/12/{ano}"
    destino  = os.path.join(pasta_destino, f"fat{ano}.vendedor.fab")
    log.info("▶ Vendedor %d (%s → %s) — scraping HTML", ano, data_ini, data_fim)

    frame_rel = _ir_para_producao(page)
    _configurar_form_vendedor(frame_rel, page)
    _preencher_datas(frame_rel, page, data_ini, data_fim)
    _garantir_sem_excel(frame_rel, page)

    log.info("  Clicando Imprimir...")
    frame_rel.click("#CMD_Imprimir")

    log.info("  Aguardando tabela de resultados (até 10 min)...")
    frame_rel.wait_for_selector("text=TOTAL VENDEDOR", timeout=600000)
    page.wait_for_timeout(3000)

    log.info("  Extraindo dados da tabela HTML...")
    rows_data = frame_rel.evaluate("""
        () => {
            const rows = [];
            document.querySelectorAll('table tr').forEach(tr => {
                const cells = [];
                tr.querySelectorAll('td, th').forEach(td => {
                    cells.push(td.innerText.replace(/\\n/g, ' ').trim());
                });
                if (cells.length > 0) rows.push(cells);
            });
            return rows;
        }
    """)

    if not rows_data:
        log.warning("  Tabela vazia — fallback por innerText do body...")
        body_text = frame_rel.evaluate("() => document.body.innerText")
        rows_data = [line.split('\t') for line in body_text.split('\n') if line.strip()]

    log.info("  %d linhas extraídas", len(rows_data))
    for r in rows_data[:10]:
        log.info("    %s", r)

    os.makedirs(pasta_destino, exist_ok=True)
    with open(destino, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerows(rows_data)

    log.info("  Salvo: %s", destino)

    try:
        frame_rel.screenshot(path=os.path.join(config.BASE_DIR, f"vendedor_{ano}_ok.png"))
        log.info("  Screenshot salvo: vendedor_%d_ok.png", ano)
    except Exception:
        pass

    return destino


def _consolidar():
    """Roda consolidar.py no mesmo interpretador Python atual."""
    consolidar_path = os.path.join(config.BASE_DIR, "consolidar.py")
    if not os.path.exists(consolidar_path):
        log.warning("consolidar.py não encontrado em %s — pulando.", config.BASE_DIR)
        return False

    log.info("")
    log.info("━━━ CONSOLIDAÇÃO ━━━")
    log.info("  Executando consolidar.py...")
    result = subprocess.run(
        [sys.executable, consolidar_path],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.stdout:
        for line in result.stdout.strip().splitlines():
            log.info("  [consolidar] %s", line)
    if result.stderr:
        for line in result.stderr.strip().splitlines():
            log.warning("  [consolidar STDERR] %s", line)
    if result.returncode == 0:
        log.info("  Consolidação concluída com sucesso.")
        return True
    else:
        log.error("  consolidar.py retornou código %d.", result.returncode)
        return False


def _abrir_dashboard():
    """
    Abre o dashboard do Streamlit Cloud em uma janela do Chromium,
    preenche a senha automaticamente e deixa o navegador aberto até
    o usuário pressionar Enter no terminal.
    """
    log.info("")
    log.info("━━━ ABRINDO DASHBOARD ━━━")
    log.info("  URL: %s", DASHBOARD_URL)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)
            context = browser.new_context()
            page    = context.new_page()
            page.goto(DASHBOARD_URL, wait_until="networkidle", timeout=60000)

            # Streamlit Cloud pode mostrar tela "wake up" antes de carregar.
            # Espera o input de senha aparecer (até 90s).
            try:
                page.wait_for_selector('input[type="password"]', timeout=90000)
                page.fill('input[type="password"]', DASHBOARD_PASSWORD)
                page.press('input[type="password"]', "Enter")
                log.info("  Senha preenchida automaticamente.")
                page.wait_for_timeout(2000)
            except Exception as e:
                log.warning("  Não foi possível preencher a senha: %s", e)
                log.info("  Faça login manualmente na janela aberta.")

            log.info("")
            log.info("  Dashboard pronto. Pressione ENTER no terminal para fechar...")
            try:
                input()
            except (EOFError, KeyboardInterrupt):
                pass
            browser.close()
    except Exception as e:
        log.warning("  Erro com Playwright (%s) — abrindo no navegador padrão.", e)
        try:
            webbrowser.open(DASHBOARD_URL)
            log.info("  Senha: %s", DASHBOARD_PASSWORD)
        except Exception as e2:
            log.warning("  Falhou: %s", e2)
            log.info("  Acesse manualmente: %s (senha: %s)", DASHBOARD_URL, DASHBOARD_PASSWORD)


def run_agent(consolidar=True, open_dashboard=False):
    os.makedirs(config.FORMS_DIR, exist_ok=True)
    os.makedirs(config.RAW_DIR, exist_ok=True)

    ano_atual = datetime.now().year
    anos = [ano_atual - 1, ano_atual]   # só ano anterior + atual

    log.info("=" * 60)
    log.info("AGENTE RPA — %s", datetime.now().strftime("%d/%m/%Y %H:%M"))
    log.info("  Cliente  → %s", anos)
    log.info("  Vendedor → %s", anos)
    log.info("  (anos antigos ficam estáticos, não são re-baixados)")
    log.info("=" * 60)

    arquivos = []
    erros    = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=300)
        context = browser.new_context(accept_downloads=True)
        page    = context.new_page()

        try:
            page.goto(config.LOGIN_URL, wait_until="networkidle")
            page.fill("#txt_cdusuario", config.USERNAME)
            page.fill("#txt_nmsenha",   config.PASSWORD)
            page.keyboard.press("Tab")
            page.wait_for_timeout(2000)
            page.click("#btn_ok")
            page.wait_for_load_state("networkidle")
            _fechar_popup(page)

            # ── FASE 1: Cliente ────────────────────────────────────────────
            log.info("")
            log.info("━━━ FASE 1: Relatórios Cliente ━━━")
            for ano in anos:
                try:
                    arq = _baixar_relatorio_cliente(page, ano, config.FORMS_DIR)
                    if arq:
                        arquivos.append(arq)
                except Exception as e:
                    log.error("Erro cliente %d: %s", ano, e)
                    erros.append(f"cliente {ano}: {e}")
                    page.screenshot(path=os.path.join(config.BASE_DIR, f"erro_cliente_{ano}.png"))

            # ── FASE 2: Vendedor ───────────────────────────────────────────
            log.info("")
            log.info("━━━ FASE 2: Relatórios Vendedor (scraping HTML) ━━━")
            for ano in anos:
                try:
                    arq = _scrape_relatorio_vendedor(page, ano, config.FORMS_DIR)
                    if arq:
                        arquivos.append(arq)
                except Exception as e:
                    log.error("Erro vendedor %d: %s", ano, e)
                    erros.append(f"vendedor {ano}: {e}")
                    page.screenshot(path=os.path.join(config.BASE_DIR, f"erro_vendedor_{ano}.png"))

        except Exception as e:
            log.error("Erro geral: %s", e)
            erros.append(f"geral: {e}")
            page.screenshot(path=os.path.join(config.BASE_DIR, "erro_geral.png"))
        finally:
            browser.close()

    # ── RESUMO ────────────────────────────────────────────────────────────
    log.info("")
    log.info("Arquivos baixados (%d):", len(arquivos))
    for a in arquivos:
        log.info("  %s", a)

    if erros:
        log.warning("Erros encontrados (%d):", len(erros))
        for e in erros:
            log.warning("  ✗ %s", e)

    # ── CONSOLIDAÇÃO ──────────────────────────────────────────────────────
    if consolidar and arquivos:
        _consolidar()
    elif not arquivos:
        log.warning("Nenhum arquivo baixado — consolidação ignorada.")

    # ── DASHBOARD (só em execução manual) ─────────────────────────────────
    if open_dashboard:
        _abrir_dashboard()

    return arquivos


if __name__ == "__main__":
    # Execução manual: roda tudo + abre o dashboard ao final
    resultado = run_agent(consolidar=True, open_dashboard=True)
    print("\nBaixados:", resultado if resultado else "nenhum")