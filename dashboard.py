import streamlit as st
import pandas as pd
import plotly.express as px
import os
import hmac

# ─── Autenticação ─────────────────────────────────────────────────────────────

def check_password():
    def password_entered():
        if hmac.compare_digest(st.session_state["password"], "medeiros"):
            st.session_state["password_correct"] = True
            del st.session_state["password"]
        else:
            st.session_state["password_correct"] = False

    if st.session_state.get("password_correct", False):
        return True

    st.title("Medeiros Representacoes")
    st.text_input("Senha", type="password", on_change=password_entered, key="password")
    if "password_correct" in st.session_state:
        st.error("Senha incorreta!")
    return False

if not check_password():
    st.stop()

# ─── Paths ────────────────────────────────────────────────────────────────────

BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
CARTEIRA_PATH = os.path.join(BASE_DIR, "data", "historico_carteira.csv")
FATURADO_PATH = os.path.join(BASE_DIR, "data", "historico_faturado.csv")
VENDEDOR_PATH = os.path.join(BASE_DIR, "data", "historico_vendedor.csv")

NOMES_MESES = {
    1: "Jan", 2: "Fev",  3: "Mar", 4: "Abr",
    5: "Mai", 6: "Jun",  7: "Jul", 8: "Ago",
    9: "Set", 10: "Out", 11: "Nov", 12: "Dez",
}
ORDEM_MESES = list(NOMES_MESES.values())

# ─── Carregamento de dados ────────────────────────────────────────────────────

@st.cache_data(ttl=3600)
def carregar_dados():
    df_c = pd.read_csv(CARTEIRA_PATH, sep=";", encoding="utf-8")
    df_f = pd.read_csv(FATURADO_PATH, sep=";", encoding="utf-8")

    for df in [df_c, df_f]:
        df["data_emissao_dt"] = pd.to_datetime(df["data_emissao_dt"], errors="coerce")
        df["valor_num"]       = pd.to_numeric(df["valor_num"], errors="coerce").fillna(0)
        df["ano_arquivo"]     = df["ano_arquivo"].astype(int)
        df["mes"]             = pd.to_numeric(df["mes"], errors="coerce").fillna(0).astype(int)

    df_v = pd.DataFrame()
    if os.path.exists(VENDEDOR_PATH):
        df_v = pd.read_csv(VENDEDOR_PATH, sep=";", encoding="utf-8")
        df_v["valor_num"]   = pd.to_numeric(df_v["valor_num"],   errors="coerce").fillna(0)
        df_v["qtde_num"]    = pd.to_numeric(df_v["qtde_num"],    errors="coerce").fillna(0).astype(int)
        df_v["ano_arquivo"] = df_v["ano_arquivo"].astype(int)
        df_v["mes"]         = pd.to_numeric(df_v["mes"], errors="coerce").fillna(0).astype(int)
        df_v["ano"]         = pd.to_numeric(df_v["ano"], errors="coerce").fillna(0).astype(int)

    return df_c, df_f, df_v

try:
    df_carteira, df_faturado, df_vendedor = carregar_dados()
except FileNotFoundError:
    st.error("Rode: python scheduler.py --consolidar")
    st.stop()

# ─── Sidebar — Filtros globais ────────────────────────────────────────────────

with st.sidebar:
    st.markdown("## Filtros")

    visao = st.radio("Visão", ["Faturado Realizado", "Carteira Completa", "Comparativo"])
    base = df_faturado if visao == "Faturado Realizado" else df_carteira

    anos_disp = sorted(base["ano_arquivo"].unique(), reverse=True)
    anos_sel  = st.multiselect("Ano", anos_disp, default=anos_disp)

    # ── Filtro de Mês (global) ──────────────────────────────────────────────
    meses_disp = sorted([m for m in base["mes"].unique() if 1 <= m <= 12])
    meses_sel  = st.multiselect(
        "Mês",
        meses_disp,
        default=[],
        format_func=lambda m: NOMES_MESES.get(m, str(m)),
    )

    reps_disp    = sorted(base["representada"].dropna().unique())
    reps_sel     = st.multiselect("Representada", reps_disp, default=[])

    clientes_disp = sorted(base["cliente"].dropna().unique())
    clientes_sel  = st.multiselect("Cliente", clientes_disp, default=[])

    # Filtro de Vendedor (usa df_vendedor se disponível)
    vendedores_sel = []
    if not df_vendedor.empty:
        vends_disp     = sorted(df_vendedor["vendedor"].dropna().unique())
        vendedores_sel = st.multiselect("Vendedor", vends_disp, default=[])

    status_sel = "Todos"
    if visao == "Carteira Completa":
        status_sel = st.radio("Status", ["Todos", "Faturado", "Em aberto"])

    if st.button("Recarregar", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

# ─── Funções de filtro ────────────────────────────────────────────────────────

def filtrar(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    if anos_sel:     d = d[d["ano_arquivo"].isin(anos_sel)]
    if meses_sel:    d = d[d["mes"].isin(meses_sel)]
    if reps_sel:     d = d[d["representada"].isin(reps_sel)]
    if clientes_sel: d = d[d["cliente"].isin(clientes_sel)]
    if status_sel == "Faturado":   d = d[d["faturado_flag"] == True]
    elif status_sel == "Em aberto": d = d[d["faturado_flag"] == False]
    return d

def filtrar_vendedor(df: pd.DataFrame) -> pd.DataFrame:
    """Aplica filtros de ano, mês, representada e vendedor ao dataframe de vendedor."""
    d = df.copy()
    if anos_sel:       d = d[d["ano_arquivo"].isin(anos_sel)]
    if meses_sel:      d = d[d["mes"].isin(meses_sel)]
    if reps_sel:       d = d[d["representada"].isin(reps_sel)]
    if vendedores_sel: d = d[d["vendedor"].isin(vendedores_sel)]
    return d

df  = filtrar(df_faturado if visao == "Faturado Realizado" else df_carteira)
dff = filtrar(df_faturado)
dfc = filtrar(df_carteira)
dfv = filtrar_vendedor(df_vendedor) if not df_vendedor.empty else pd.DataFrame()

# ─── Helpers de visualização ──────────────────────────────────────────────────

def fmt(v) -> str:
    return "R$ {:,.0f}".format(v).replace(",", ".")

def layout_bar(fig, horizontal=False):
    cfg = dict(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font_color="#9ca3af",
    )
    if horizontal:
        cfg["xaxis"] = dict(gridcolor="#1e2130", showticklabels=False, title="")
        cfg["yaxis"] = dict(gridcolor="#1e2130")
    else:
        cfg["xaxis"] = dict(gridcolor="#1e2130", type="category")
        cfg["yaxis"] = dict(gridcolor="#1e2130", tickprefix="R$ ", tickformat=",.0f")
    fig.update_layout(**cfg)
    fig.update_traces(textposition="outside")
    return fig

def layout_line(fig):
    fig.update_traces(textposition="top center")
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font_color="#9ca3af",
        yaxis=dict(gridcolor="#1e2130", tickprefix="R$ ", tickformat=",.0f"),
        xaxis=dict(gridcolor="#1e2130"),
    )
    return fig

CORES_ANOS = ["#2563eb", "#7c3aed", "#0891b2", "#059669", "#d97706", "#dc2626"]

# ─── Cabeçalho e última atualização ──────────────────────────────────────────

col_titulo, col_data = st.columns([3, 1])
with col_titulo:
    st.title("Medeiros Representacoes")
with col_data:
    ultima = pd.to_datetime(df_faturado["_consolidado_em"].max())
    st.markdown(
        "<p style='text-align:right;color:#6b7280;font-size:0.8rem;margin-top:2rem;'>"
        "Atualizado em<br><b>" + ultima.strftime("%d/%m/%Y %H:%M") + "</b></p>",
        unsafe_allow_html=True,
    )

st.markdown(
    "<style>[data-testid='stMetricValue']{font-size:1rem!important}</style>",
    unsafe_allow_html=True,
)

# ─── Abas ────────────────────────────────────────────────────────────────────

tab_geral, tab_vendedor = st.tabs(["📊 Análise Geral", "👤 Por Vendedor"])

# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — ANÁLISE GERAL
# ══════════════════════════════════════════════════════════════════════════════

with tab_geral:

    # KPIs
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Faturado",  fmt(dff["valor_num"].sum()))
    c2.metric("Carteira",  fmt(dfc["valor_num"].sum()))
    c3.metric("Pedidos",   "{:,}".format(len(df)).replace(",", "."))
    c4.metric("Clientes",  "{:,}".format(df["cliente"].nunique()).replace(",", "."))
    st.markdown("---")

    # ── Faturamento por Ano ───────────────────────────────────────────────
    st.subheader("Faturamento por Ano")
    if visao == "Comparativo":
        a = dff.groupby("ano_arquivo")["valor_num"].sum().reset_index(); a["v"] = "Faturado"
        b = dfc.groupby("ano_arquivo")["valor_num"].sum().reset_index(); b["v"] = "Carteira"
        por_ano = pd.concat([a, b])
        por_ano["rotulo"]      = por_ano["valor_num"].apply(fmt)
        por_ano["ano_arquivo"] = por_ano["ano_arquivo"].astype(str)
        fig = px.bar(
            por_ano, x="ano_arquivo", y="valor_num", color="v", barmode="group",
            text="rotulo",
            color_discrete_map={"Faturado": "#2563eb", "Carteira": "#7c3aed"},
        )
    else:
        por_ano = df.groupby("ano_arquivo")["valor_num"].sum().reset_index()
        por_ano["rotulo"]      = por_ano["valor_num"].apply(fmt)
        por_ano["ano_arquivo"] = por_ano["ano_arquivo"].astype(str)
        fig = px.bar(
            por_ano, x="ano_arquivo", y="valor_num",
            text="rotulo", color_discrete_sequence=["#2563eb"],
        )
    st.plotly_chart(layout_bar(fig), use_container_width=True)

    # ── Sazonalidade Mensal ───────────────────────────────────────────────
    st.subheader("Faturamento por Mês")
    dm = df.copy()
    dm["mes_num"]    = dm["data_emissao_dt"].dt.month
    dm["mes_abrev"]  = dm["mes_num"].map(NOMES_MESES)
    dm["ano_str"]    = dm["ano_arquivo"].astype(str)
    pm = (
        dm.groupby(["mes_num", "mes_abrev", "ano_str"])["valor_num"]
        .sum().reset_index().sort_values("mes_num")
    )
    pm["rotulo"] = pm["valor_num"].apply(fmt)
    fig2 = px.line(
        pm, x="mes_abrev", y="valor_num", color="ano_str",
        markers=True, text="rotulo",
        category_orders={"mes_abrev": ORDEM_MESES},
        color_discrete_sequence=CORES_ANOS,
    )
    st.plotly_chart(layout_line(fig2), use_container_width=True)

    # ── Top Representadas + Top Clientes ─────────────────────────────────
    ca, cb = st.columns(2)
    with ca:
        st.subheader("Top Representadas")
        tr = (
            df.groupby("representada")["valor_num"].sum()
            .reset_index().sort_values("valor_num", ascending=True).tail(15)
        )
        tr["rotulo"] = tr["valor_num"].apply(fmt)
        st.plotly_chart(
            layout_bar(
                px.bar(tr, x="valor_num", y="representada", orientation="h",
                       text="rotulo", color_discrete_sequence=["#2563eb"]),
                horizontal=True,
            ),
            use_container_width=True,
        )
    with cb:
        st.subheader("Top Clientes")
        tc = (
            df.groupby("cliente")["valor_num"].sum()
            .reset_index().sort_values("valor_num", ascending=True).tail(15)
        )
        tc["rotulo"] = tc["valor_num"].apply(fmt)
        st.plotly_chart(
            layout_bar(
                px.bar(tc, x="valor_num", y="cliente", orientation="h",
                       text="rotulo", color_discrete_sequence=["#7c3aed"]),
                horizontal=True,
            ),
            use_container_width=True,
        )

    # ── Pivot Representada × Ano ──────────────────────────────────────────
    st.subheader("Detalhe por Representada × Ano")
    tab_pivot = (
        df.groupby(["representada", "ano_arquivo"])["valor_num"]
        .sum().unstack(fill_value=0)
    )
    tab_pivot.columns = tab_pivot.columns.astype(str)
    tab_pivot["TOTAL"] = tab_pivot.sum(axis=1)
    st.dataframe(
        tab_pivot.sort_values("TOTAL", ascending=False).map(fmt),
        use_container_width=True, height=400,
    )

# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — POR VENDEDOR
# ══════════════════════════════════════════════════════════════════════════════

with tab_vendedor:

    if dfv.empty:
        st.info(
            "Dados de vendedor ainda não disponíveis. "
            "Execute o agente para baixar os arquivos fat*.vendedor.fab "
            "e depois rode consolidar.py."
        )
        st.stop()

    # ── KPIs ────────────────────────────────────────────────────────────────
    total_vend   = dfv["valor_num"].sum()
    total_itens  = dfv["qtde_num"].sum()
    n_vendedores = dfv["vendedor"].nunique()
    n_reps_v     = dfv["representada"].nunique()

    v1, v2, v3, v4 = st.columns(4)
    v1.metric("Total Vendas",   fmt(total_vend))
    v2.metric("Total Itens",    "{:,}".format(int(total_itens)).replace(",", "."))
    v3.metric("Vendedores",     str(n_vendedores))
    v4.metric("Representadas",  str(n_reps_v))
    st.markdown("---")

    # ── Vendas por Vendedor por Ano (barras agrupadas) ────────────────────
    st.subheader("Vendas por Vendedor — por Ano")
    pv_ano = (
        dfv.groupby(["vendedor", "ano_arquivo"])["valor_num"]
        .sum().reset_index()
    )
    pv_ano["rotulo"]      = pv_ano["valor_num"].apply(fmt)
    pv_ano["ano_arquivo"] = pv_ano["ano_arquivo"].astype(str)
    fig_vano = px.bar(
        pv_ano, x="vendedor", y="valor_num", color="ano_arquivo",
        barmode="group", text="rotulo",
        color_discrete_sequence=CORES_ANOS,
    )
    st.plotly_chart(layout_bar(fig_vano), use_container_width=True)

    # ── Evolução Mensal por Vendedor (linha) ──────────────────────────────
    st.subheader("Evolução Mensal por Vendedor")
    pv_mes = (
        dfv.groupby(["mes", "vendedor", "ano_arquivo"])["valor_num"]
        .sum().reset_index().sort_values("mes")
    )
    pv_mes["mes_abrev"] = pv_mes["mes"].map(NOMES_MESES)
    pv_mes["serie"]     = pv_mes["vendedor"] + " / " + pv_mes["ano_arquivo"].astype(str)
    pv_mes["rotulo"]    = pv_mes["valor_num"].apply(fmt)

    fig_vmes = px.line(
        pv_mes, x="mes_abrev", y="valor_num", color="serie",
        markers=True, text="rotulo",
        category_orders={"mes_abrev": ORDEM_MESES},
        color_discrete_sequence=CORES_ANOS,
    )
    st.plotly_chart(layout_line(fig_vmes), use_container_width=True)

    # ── Participação dos Vendedores (pizza) ───────────────────────────────
    st.subheader("Participação por Vendedor")
    pv_part = dfv.groupby("vendedor")["valor_num"].sum().reset_index()
    fig_pizza = px.pie(
        pv_part, names="vendedor", values="valor_num",
        color_discrete_sequence=CORES_ANOS,
    )
    fig_pizza.update_traces(textinfo="label+percent", textposition="outside")
    fig_pizza.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        font_color="#9ca3af",
        showlegend=True,
    )
    st.plotly_chart(fig_pizza, use_container_width=True)

    # ── Top Representadas por Vendedor ────────────────────────────────────
    st.subheader("Top Representadas por Vendedor")

    vendedores_lista = sorted(dfv["vendedor"].unique())
    vend_sel = st.selectbox(
        "Selecione o Vendedor",
        ["Todos"] + vendedores_lista,
        key="vend_sel_rep",
    )

    df_rep_vend = dfv if vend_sel == "Todos" else dfv[dfv["vendedor"] == vend_sel]
    top_reps = (
        df_rep_vend.groupby("representada")["valor_num"]
        .sum().reset_index()
        .sort_values("valor_num", ascending=True).tail(15)
    )
    top_reps["rotulo"] = top_reps["valor_num"].apply(fmt)
    fig_rep = px.bar(
        top_reps, x="valor_num", y="representada", orientation="h",
        text="rotulo", color_discrete_sequence=["#0891b2"],
    )
    st.plotly_chart(layout_bar(fig_rep, horizontal=True), use_container_width=True)

    # ── Pivot Vendedor × Representada × Ano ──────────────────────────────
    st.subheader("Pivot Vendedor × Representada × Ano")
    pivot_vr = (
        dfv.groupby(["vendedor", "representada", "ano_arquivo"])["valor_num"]
        .sum().unstack(fill_value=0)
    )
    pivot_vr.columns = pivot_vr.columns.astype(str)
    pivot_vr["TOTAL"] = pivot_vr.sum(axis=1)
    st.dataframe(
        pivot_vr.sort_values("TOTAL", ascending=False).map(fmt),
        use_container_width=True, height=450,
    )

    # ── Pivot Vendedor × Mês (ano selecionado) ────────────────────────────
    st.subheader("Vendedor × Mês")
    anos_vend_disp = sorted(dfv["ano_arquivo"].unique(), reverse=True)
    ano_pivot_sel  = st.selectbox(
        "Ano para pivot mensal",
        anos_vend_disp,
        key="ano_pivot_mes",
    )
    df_pivot_mes = dfv[dfv["ano_arquivo"] == ano_pivot_sel].copy()
    df_pivot_mes["mes_abrev"] = df_pivot_mes["mes"].map(NOMES_MESES)
    pivot_mes = (
        df_pivot_mes.groupby(["vendedor", "mes_abrev"])["valor_num"]
        .sum().unstack(fill_value=0)
    )
    # Reordena colunas por mês
    cols_ordenadas = [m for m in ORDEM_MESES if m in pivot_mes.columns]
    pivot_mes = pivot_mes[cols_ordenadas]
    pivot_mes["TOTAL"] = pivot_mes.sum(axis=1)
    st.dataframe(
        pivot_mes.sort_values("TOTAL", ascending=False).map(fmt),
        use_container_width=True, height=350,
    )
