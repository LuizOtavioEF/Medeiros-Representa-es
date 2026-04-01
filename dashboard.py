import streamlit as st
import pandas as pd
import plotly.express as px
import os
import hmac

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

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CARTEIRA_PATH = os.path.join(BASE_DIR, "data", "historico_carteira.csv")
FATURADO_PATH = os.path.join(BASE_DIR, "data", "historico_faturado.csv")

@st.cache_data(ttl=3600)
def carregar_dados():
    df_c = pd.read_csv(CARTEIRA_PATH, sep=";", encoding="utf-8")
    df_f = pd.read_csv(FATURADO_PATH, sep=";", encoding="utf-8")
    for df in [df_c, df_f]:
        df["data_emissao_dt"] = pd.to_datetime(df["data_emissao_dt"], errors="coerce")
        df["valor_num"] = pd.to_numeric(df["valor_num"], errors="coerce").fillna(0)
        df["ano_arquivo"] = df["ano_arquivo"].astype(int)
    return df_c, df_f

try:
    df_carteira, df_faturado = carregar_dados()
except FileNotFoundError:
    st.error("Rode: python scheduler.py --consolidar")
    st.stop()

with st.sidebar:
    st.markdown("## Filtros")
    visao = st.radio("Visao", ["Faturado Realizado", "Carteira Completa", "Comparativo"])
    base = df_faturado if visao == "Faturado Realizado" else df_carteira
    anos_disp = sorted(base["ano_arquivo"].unique(), reverse=True)
    anos_sel = st.multiselect("Ano", anos_disp, default=anos_disp)
    reps_disp = sorted(base["representada"].dropna().unique())
    reps_sel = st.multiselect("Representada", reps_disp, default=[])
    clientes_disp = sorted(base["cliente"].dropna().unique())
    clientes_sel = st.multiselect("Cliente", clientes_disp, default=[])
    status_sel = "Todos"
    if visao == "Carteira Completa":
        status_sel = st.radio("Status", ["Todos", "Faturado", "Em aberto"])
    if st.button("Recarregar", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

def filtrar(df):
    d = df.copy()
    if anos_sel: d = d[d["ano_arquivo"].isin(anos_sel)]
    if reps_sel: d = d[d["representada"].isin(reps_sel)]
    if clientes_sel: d = d[d["cliente"].isin(clientes_sel)]
    if status_sel == "Faturado": d = d[d["faturado_flag"] == True]
    elif status_sel == "Em aberto": d = d[d["faturado_flag"] == False]
    return d

df = filtrar(df_faturado if visao == "Faturado Realizado" else df_carteira)
dff = filtrar(df_faturado)
dfc = filtrar(df_carteira)

def fmt(v): return "R$ {:,.0f}".format(v).replace(",", ".")

def layout_bar(fig, horizontal=False):
    cfg = dict(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font_color="#9ca3af")
    if horizontal:
        cfg["xaxis"] = dict(gridcolor="#1e2130", showticklabels=False, title="")
        cfg["yaxis"] = dict(gridcolor="#1e2130")
    else:
        cfg["xaxis"] = dict(gridcolor="#1e2130", type="category")
        cfg["yaxis"] = dict(gridcolor="#1e2130", tickprefix="R$ ", tickformat=",.0f")
    fig.update_layout(**cfg)
    fig.update_traces(textposition="outside")
    return fig

st.title("Medeiros Representacoes")
st.markdown("<style>[data-testid='stMetricValue']{font-size:1rem!important}</style>", unsafe_allow_html=True)
c1, c2, c3, c4 = st.columns(4)
c1.metric("Faturado", fmt(dff["valor_num"].sum()))
c2.metric("Carteira", fmt(dfc["valor_num"].sum()))
c3.metric("Pedidos", "{:,}".format(len(df)).replace(",", "."))
c4.metric("Clientes", "{:,}".format(df["cliente"].nunique()).replace(",", "."))
st.markdown("---")

st.subheader("Faturamento por Ano")
if visao == "Comparativo":
    a = dff.groupby("ano_arquivo")["valor_num"].sum().reset_index(); a["v"] = "Faturado"
    b = dfc.groupby("ano_arquivo")["valor_num"].sum().reset_index(); b["v"] = "Carteira"
    por_ano = pd.concat([a, b])
    por_ano["rotulo"] = por_ano["valor_num"].apply(fmt)
    por_ano["ano_arquivo"] = por_ano["ano_arquivo"].astype(str)
    fig = px.bar(por_ano, x="ano_arquivo", y="valor_num", color="v", barmode="group",
                 text="rotulo", color_discrete_map={"Faturado": "#2563eb", "Carteira": "#7c3aed"})
else:
    por_ano = df.groupby("ano_arquivo")["valor_num"].sum().reset_index()
    por_ano["rotulo"] = por_ano["valor_num"].apply(fmt)
    por_ano["ano_arquivo"] = por_ano["ano_arquivo"].astype(str)
    fig = px.bar(por_ano, x="ano_arquivo", y="valor_num", text="rotulo", color_discrete_sequence=["#2563eb"])
st.plotly_chart(layout_bar(fig), use_container_width=True)

st.subheader("Faturamento por Mes")
dm = df.copy()
dm["mes_num"] = dm["data_emissao_dt"].dt.month
dm["mes_nome"] = dm["data_emissao_dt"].dt.strftime("%b")
dm["ano_arquivo"] = dm["ano_arquivo"].astype(str)
pm = dm.groupby(["mes_num", "mes_nome", "ano_arquivo"])["valor_num"].sum().reset_index().sort_values("mes_num")
pm["rotulo"] = pm["valor_num"].apply(fmt)
meses_ordem = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
fig2 = px.line(pm, x="mes_nome", y="valor_num", color="ano_arquivo", markers=True,
               text="rotulo", category_orders={"mes_nome": meses_ordem},
               color_discrete_sequence=["#2563eb","#7c3aed","#0891b2","#059669"])
fig2.update_traces(textposition="top center")
fig2.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    font_color="#9ca3af", yaxis=dict(gridcolor="#1e2130", tickprefix="R$ ", tickformat=",.0f"),
    xaxis=dict(gridcolor="#1e2130", title="Mes"))
st.plotly_chart(fig2, use_container_width=True)

ca, cb = st.columns(2)
with ca:
    st.subheader("Top Representadas")
    tr = df.groupby("representada")["valor_num"].sum().reset_index().sort_values("valor_num", ascending=True).tail(15)
    tr["rotulo"] = tr["valor_num"].apply(fmt)
    st.plotly_chart(layout_bar(px.bar(tr, x="valor_num", y="representada", orientation="h",
        text="rotulo", color_discrete_sequence=["#2563eb"]), horizontal=True), use_container_width=True)
with cb:
    st.subheader("Top Clientes")
    tc = df.groupby("cliente")["valor_num"].sum().reset_index().sort_values("valor_num", ascending=True).tail(15)
    tc["rotulo"] = tc["valor_num"].apply(fmt)
    st.plotly_chart(layout_bar(px.bar(tc, x="valor_num", y="cliente", orientation="h",
        text="rotulo", color_discrete_sequence=["#7c3aed"]), horizontal=True), use_container_width=True)

st.subheader("Detalhe por Representada x Ano")
tab = df.groupby(["representada", "ano_arquivo"])["valor_num"].sum().unstack(fill_value=0)
tab["TOTAL"] = tab.sum(axis=1)
st.dataframe(tab.sort_values("TOTAL", ascending=False).map(fmt), use_container_width=True, height=400)
