"""
TechFix Informática — Painel Administrativo (Streamlit)

Painel do gerente/técnico para consultar, filtrar, cadastrar, editar,
excluir ordens de serviço e clientes, e acompanhar indicadores.

Execução:
    streamlit run app_streamlit.py

Credenciais: lidas de .streamlit/secrets.toml (SUPABASE_URL e SUPABASE_KEY)
ou, na falta dele, das variáveis de ambiente / arquivo .env.
Nunca escreva as chaves diretamente no código.
"""

import os
import re
from datetime import datetime

import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from postgrest.exceptions import APIError
from supabase import Client, create_client

# ---------------------------------------------------------------------
# Configuração geral
# ---------------------------------------------------------------------
st.set_page_config(page_title="TechFix — Painel", page_icon="🛠️", layout="wide")
load_dotenv()

STATUS = ["Aberto", "Em análise", "Aguardando peça", "Concluído", "Entregue"]
STATUS_ICONE = {
    "Aberto": "🟦",
    "Em análise": "🔍",
    "Aguardando peça": "⏳",
    "Concluído": "✅",
    "Entregue": "📦",
}
FUSO = "America/Sao_Paulo"

# Mesmas regras usadas nas restrições CHECK do schema.sql
REGEX_EMAIL = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
REGEX_CELULAR = re.compile(r"^[0-9]{10,13}$")


# ---------------------------------------------------------------------
# Conexão com o Supabase
# ---------------------------------------------------------------------
def ler_credencial(nome: str) -> str | None:
    """Procura a credencial no secrets.toml e, depois, nas variáveis de ambiente."""
    try:
        if nome in st.secrets:
            return st.secrets[nome]
    except Exception:
        pass  # secrets.toml não existe: segue para as variáveis de ambiente
    return os.environ.get(nome)


@st.cache_resource
def get_supabase() -> Client:
    url = ler_credencial("SUPABASE_URL")
    key = ler_credencial("SUPABASE_KEY")
    if not url or not key:
        raise RuntimeError(
            "Credenciais do Supabase não encontradas. Configure SUPABASE_URL e SUPABASE_KEY "
            "em .streamlit/secrets.toml ou no arquivo .env (veja .env.example)."
        )
    return create_client(url, key)


def mensagem_erro(e: Exception) -> str:
    """Converte exceções em mensagens amigáveis."""
    if isinstance(e, RuntimeError):
        return str(e)
    if isinstance(e, APIError):
        texto = f"{e.message or ''} {e.details or ''}"
        if e.code == "23505":
            return "Já existe um cliente com este e-mail."
        if e.code == "23514":
            if "email" in texto:
                return "O banco recusou o e-mail: formato inválido."
            if "celular" in texto:
                return "O banco recusou o celular: use apenas números (10 a 13 dígitos)."
            if "status" in texto:
                return "Status inválido."
            return "O banco recusou os dados: algum campo está fora do formato permitido."
        if e.code in ("42501", "PGRST301"):
            return "Sem permissão para esta operação. Verifique a chave e as políticas de acesso (RLS)."
        return f"Erro no banco de dados: {e.message}"
    return f"Falha de comunicação com o banco ({type(e).__name__}). Verifique a conexão e tente novamente."


def avisar_e_recarregar(msg: str):
    """Guarda uma mensagem de sucesso, limpa o cache e recarrega a página."""
    st.session_state["flash"] = msg
    st.cache_data.clear()
    st.rerun()


# ---------------------------------------------------------------------
# Leitura de dados (com cache curto para não consultar a cada clique)
# ---------------------------------------------------------------------
def _formatar_datas(df: pd.DataFrame, colunas: list[str]) -> pd.DataFrame:
    for col in colunas:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], utc=True).dt.tz_convert(FUSO).dt.tz_localize(None)
    return df


@st.cache_data(ttl=60, show_spinner="Carregando ordens de serviço...")
def carregar_ordens() -> pd.DataFrame:
    resp = get_supabase().table("vw_ordens_servico").select("*").order("os_id", desc=True).execute()
    colunas = ["os_id", "status", "modelo_computador", "problema_relatado", "data_abertura",
               "data_atualizacao", "cliente_id", "nome", "email", "celular_whatsapp", "endereco"]
    df = pd.DataFrame(resp.data, columns=colunas)
    return _formatar_datas(df, ["data_abertura", "data_atualizacao"])


@st.cache_data(ttl=60, show_spinner="Carregando clientes...")
def carregar_clientes() -> pd.DataFrame:
    resp = get_supabase().table("clientes").select("*").order("nome").execute()
    colunas = ["id", "nome", "endereco", "email", "celular_whatsapp", "data_cadastro"]
    df = pd.DataFrame(resp.data, columns=colunas)
    return _formatar_datas(df, ["data_cadastro"])


# ---------------------------------------------------------------------
# Validação e gravação
# ---------------------------------------------------------------------
def validar_cliente(nome, endereco, email, celular) -> list[str]:
    erros = []
    if not nome:
        erros.append("Informe o nome do cliente.")
    if not endereco:
        erros.append("Informe o endereço.")
    if not email:
        erros.append("Informe o e-mail.")
    elif not REGEX_EMAIL.match(email):
        erros.append("E-mail em formato inválido (exemplo: nome@dominio.com).")
    if not celular:
        erros.append("Informe o celular/WhatsApp.")
    elif not celular.isdigit():
        erros.append("Celular/WhatsApp deve conter apenas números.")
    elif not REGEX_CELULAR.match(celular):
        erros.append("Celular/WhatsApp deve ter de 10 a 13 dígitos (exemplo: 11987654321).")
    return erros


def obter_ou_criar_cliente(sb: Client, nome, endereco, email, celular) -> tuple[dict, bool]:
    """Reaproveita o cliente pelo e-mail; se não existir, cria um novo."""
    resp = sb.table("clientes").select("id, nome").eq("email", email).limit(1).execute()
    if resp.data:
        return resp.data[0], False
    novo = sb.table("clientes").insert({
        "nome": nome, "endereco": endereco, "email": email, "celular_whatsapp": celular,
    }).execute()
    return novo.data[0], True


# ---------------------------------------------------------------------
# Diálogos de confirmação de exclusão
# ---------------------------------------------------------------------
@st.dialog("Confirmar exclusão da OS")
def dialogo_excluir_os(os_id: int, descricao: str):
    st.write(f"Tem certeza de que deseja excluir a **OS nº {os_id}**?")
    st.caption(descricao)
    st.warning("Esta ação não pode ser desfeita.")
    c1, c2 = st.columns(2)
    if c1.button("Sim, excluir", type="primary", width="stretch"):
        try:
            resp = get_supabase().table("ordens_servico").delete().eq("id", os_id).execute()
            if not resp.data:
                st.error("OS não encontrada (pode já ter sido excluída).")
                return
        except Exception as e:
            st.error(mensagem_erro(e))
            return
        avisar_e_recarregar(f"OS nº {os_id} excluída.")
    if c2.button("Cancelar", width="stretch"):
        st.rerun()


@st.dialog("Confirmar exclusão do cliente")
def dialogo_excluir_cliente(cliente_id: int, nome: str, qtd_os: int):
    st.write(f"Tem certeza de que deseja excluir o cliente **{nome}**?")
    if qtd_os:
        st.error(
            f"Atenção: {qtd_os} ordem(ns) de serviço deste cliente também será(ão) "
            "excluída(s) (ON DELETE CASCADE)."
        )
    st.warning("Esta ação não pode ser desfeita.")
    c1, c2 = st.columns(2)
    if c1.button("Sim, excluir", type="primary", width="stretch"):
        try:
            resp = get_supabase().table("clientes").delete().eq("id", cliente_id).execute()
            if not resp.data:
                st.error("Cliente não encontrado (pode já ter sido excluído).")
                return
        except Exception as e:
            st.error(mensagem_erro(e))
            return
        avisar_e_recarregar(f"Cliente {nome} excluído (e {qtd_os} OS vinculada(s)).")
    if c2.button("Cancelar", width="stretch"):
        st.rerun()


# ---------------------------------------------------------------------
# Cabeçalho e carga inicial
# ---------------------------------------------------------------------
st.title("🛠️ TechFix Informática — Painel Administrativo")

if "flash" in st.session_state:
    st.success(st.session_state.pop("flash"))

try:
    df_os = carregar_ordens()
    df_cli = carregar_clientes()
except Exception as e:
    st.error(f"Não foi possível carregar os dados. {mensagem_erro(e)}")
    st.stop()

# ---------------------------------------------------------------------
# Barra lateral — filtros
# ---------------------------------------------------------------------
with st.sidebar:
    st.header("🔎 Filtros")
    f_nome = st.text_input("Nome do cliente", placeholder="Parte do nome")
    f_email = st.text_input("E-mail", placeholder="Parte do e-mail")
    f_status = st.multiselect("Status", STATUS, default=STATUS)
    st.divider()
    if st.button("🔄 Recarregar dados", width="stretch"):
        st.cache_data.clear()
        st.rerun()
    st.caption("Os filtros valem para todas as abas.")


def aplicar_filtros(df: pd.DataFrame, usar_status: bool = True) -> pd.DataFrame:
    filtrado = df
    if f_nome:
        filtrado = filtrado[filtrado["nome"].str.contains(f_nome, case=False, na=False, regex=False)]
    if f_email:
        filtrado = filtrado[filtrado["email"].str.contains(f_email, case=False, na=False, regex=False)]
    if usar_status:
        filtrado = filtrado[filtrado["status"].isin(f_status)]
    return filtrado


df_os_f = aplicar_filtros(df_os)
df_cli_f = aplicar_filtros(df_cli, usar_status=False)

aba_consultar, aba_cadastrar, aba_editar, aba_indicadores = st.tabs(
    ["📋 Consultar", "➕ Cadastrar", "✏️ Editar/Excluir", "📊 Indicadores"]
)

# ---------------------------------------------------------------------
# Aba 1 — Consultar
# ---------------------------------------------------------------------
with aba_consultar:
    st.subheader("Ordens de serviço")
    st.caption(f"{len(df_os_f)} de {len(df_os)} OS exibidas com os filtros atuais.")

    if df_os_f.empty:
        st.info("Nenhuma OS encontrada com os filtros selecionados.")
    else:
        exibir = df_os_f[["os_id", "status", "nome", "email", "celular_whatsapp", "endereco",
                          "modelo_computador", "problema_relatado", "data_abertura", "data_atualizacao"]]
        st.dataframe(
            exibir,
            hide_index=True,
            width="stretch",
            column_config={
                "os_id": st.column_config.NumberColumn("OS nº", format="%d"),
                "status": "Status",
                "nome": "Cliente",
                "email": "E-mail",
                "celular_whatsapp": "Celular/WhatsApp",
                "endereco": "Endereço",
                "modelo_computador": "Modelo",
                "problema_relatado": st.column_config.TextColumn("Problema", width="large"),
                "data_abertura": st.column_config.DatetimeColumn("Abertura", format="DD/MM/YYYY HH:mm"),
                "data_atualizacao": st.column_config.DatetimeColumn("Atualização", format="DD/MM/YYYY HH:mm"),
            },
        )

        # Desafio opcional: exportar os dados filtrados em CSV
        #   - cabeçalhos em português; separador ";" e UTF-8 com BOM abrem direto no Excel
        cabecalhos = {
            "os_id": "OS", "status": "Status", "nome": "Cliente", "email": "E-mail",
            "celular_whatsapp": "Celular/WhatsApp", "endereco": "Endereço",
            "modelo_computador": "Modelo", "problema_relatado": "Problema",
            "data_abertura": "Data de abertura", "data_atualizacao": "Última atualização",
        }
        csv = (
            exibir.rename(columns=cabecalhos)
            .to_csv(index=False, sep=";", date_format="%d/%m/%Y %H:%M")
            .encode("utf-8-sig")
        )
        st.download_button(
            "⬇️ Exportar CSV (dados filtrados)",
            data=csv,
            file_name=f"ordens_servico_{datetime.now():%Y%m%d_%H%M}.csv",
            mime="text/csv",
        )

# ---------------------------------------------------------------------
# Aba 2 — Cadastrar nova OS
# ---------------------------------------------------------------------
with aba_cadastrar:
    st.subheader("Nova ordem de serviço")
    st.caption("Se o e-mail já estiver cadastrado, a OS é vinculada ao cliente existente.")

    with st.form("form_nova_os", clear_on_submit=False):
        c1, c2 = st.columns(2)
        with c1:
            nome = st.text_input("Nome do Cliente *", placeholder="Ex.: Maria da Silva")
            endereco = st.text_input("Endereço *", placeholder="Ex.: Rua das Flores, 123 - Centro")
            email = st.text_input("E-mail *", placeholder="Ex.: maria@exemplo.com")
            celular = st.text_input("Celular/WhatsApp *", placeholder="Somente números. Ex.: 11987654321",
                                    max_chars=13)
        with c2:
            modelo = st.text_input("Modelo do Computador *", placeholder="Ex.: Notebook Dell Inspiron 15")
            problema = st.text_area("Problema Apresentado *", placeholder="Descreva o defeito relatado",
                                    height=150)
        enviado = st.form_submit_button("Cadastrar OS", type="primary")

    if enviado:
        nome, endereco, modelo, problema = (v.strip() for v in (nome, endereco, modelo, problema))
        email, celular = email.strip().lower(), celular.strip()

        erros = validar_cliente(nome, endereco, email, celular)
        if not modelo:
            erros.append("Informe o modelo do computador.")
        if not problema:
            erros.append("Descreva o problema apresentado.")

        if erros:
            st.error("Corrija os dados:\n\n" + "\n".join(f"- {e}" for e in erros))
        else:
            try:
                sb = get_supabase()
                cliente, criado = obter_ou_criar_cliente(sb, nome, endereco, email, celular)
                nova = sb.table("ordens_servico").insert({
                    "cliente_id": cliente["id"],
                    "modelo_computador": modelo,
                    "problema_relatado": problema,
                    "status": "Aberto",
                }).execute().data[0]
            except Exception as e:
                st.error(f"Não foi possível cadastrar. {mensagem_erro(e)}")
            else:
                origem = "novo cliente" if criado else f"cliente existente: {cliente['nome']}"
                avisar_e_recarregar(f"OS nº {nova['id']} aberta com status 'Aberto' ({origem}).")

# ---------------------------------------------------------------------
# Aba 3 — Editar / Excluir
# ---------------------------------------------------------------------
with aba_editar:
    st.caption("As listas abaixo respeitam os filtros da barra lateral.")
    col_os, col_cli = st.columns(2, gap="large")

    # ---- Ordens de serviço ------------------------------------------
    with col_os:
        st.subheader("Ordem de serviço")
        if df_os_f.empty:
            st.info("Nenhuma OS com os filtros atuais.")
        else:
            os_por_id = df_os_f.set_index("os_id")
            os_id = st.selectbox(
                "Selecione a OS",
                options=os_por_id.index.tolist(),
                format_func=lambda i: f"OS {i} — {os_por_id.at[i, 'nome']} — {os_por_id.at[i, 'status']}",
                key="sel_os",
            )
            linha = os_por_id.loc[os_id]
            st.markdown(
                f"**Cliente:** {linha['nome']}  \n"
                f"**Modelo:** {linha['modelo_computador']}  \n"
                f"**Problema:** {linha['problema_relatado']}  \n"
                f"**Aberta em:** {linha['data_abertura']:%d/%m/%Y %H:%M}"
            )

            with st.form("form_status"):
                novo_status = st.selectbox("Status", STATUS, index=STATUS.index(linha["status"]))
                salvar_status = st.form_submit_button("💾 Salvar status", type="primary")
            if salvar_status:
                if novo_status == linha["status"]:
                    st.info("O status selecionado é igual ao atual.")
                else:
                    try:
                        get_supabase().table("ordens_servico").update(
                            {"status": novo_status}
                        ).eq("id", os_id).execute()
                    except Exception as e:
                        st.error(f"Não foi possível atualizar. {mensagem_erro(e)}")
                    else:
                        avisar_e_recarregar(f"OS nº {os_id}: status alterado para '{novo_status}'.")

            if st.button("🗑️ Excluir esta OS", key="btn_excluir_os"):
                dialogo_excluir_os(int(os_id), f"{linha['nome']} — {linha['modelo_computador']}")

    # ---- Clientes ----------------------------------------------------
    with col_cli:
        st.subheader("Cliente")
        if df_cli_f.empty:
            st.info("Nenhum cliente com os filtros atuais.")
        else:
            cli_por_id = df_cli_f.set_index("id")
            cli_id = st.selectbox(
                "Selecione o cliente",
                options=cli_por_id.index.tolist(),
                format_func=lambda i: f"{cli_por_id.at[i, 'nome']} — {cli_por_id.at[i, 'email']}",
                key="sel_cli",
            )
            cli = cli_por_id.loc[cli_id]
            qtd_os = int((df_os["cliente_id"] == cli_id).sum())
            st.caption(f"Cliente desde {cli['data_cadastro']:%d/%m/%Y} · {qtd_os} OS no total")

            # A key do formulário inclui o id, para os campos mudarem ao trocar de cliente
            with st.form(f"form_cliente_{cli_id}"):
                e_nome = st.text_input("Nome", value=cli["nome"])
                e_endereco = st.text_input("Endereço", value=cli["endereco"])
                e_email = st.text_input("E-mail", value=cli["email"])
                e_celular = st.text_input("Celular/WhatsApp", value=cli["celular_whatsapp"], max_chars=13)
                salvar_cli = st.form_submit_button("💾 Salvar cliente", type="primary")

            if salvar_cli:
                e_nome, e_endereco = e_nome.strip(), e_endereco.strip()
                e_email, e_celular = e_email.strip().lower(), e_celular.strip()
                erros = validar_cliente(e_nome, e_endereco, e_email, e_celular)
                if erros:
                    st.error("Corrija os dados:\n\n" + "\n".join(f"- {e}" for e in erros))
                else:
                    try:
                        get_supabase().table("clientes").update({
                            "nome": e_nome,
                            "endereco": e_endereco,
                            "email": e_email,
                            "celular_whatsapp": e_celular,
                        }).eq("id", cli_id).execute()
                    except Exception as e:
                        st.error(f"Não foi possível atualizar. {mensagem_erro(e)}")
                    else:
                        avisar_e_recarregar(f"Dados do cliente {e_nome} atualizados.")

            if st.button("🗑️ Excluir este cliente", key="btn_excluir_cli"):
                dialogo_excluir_cliente(int(cli_id), cli["nome"], qtd_os)

# ---------------------------------------------------------------------
# Aba 4 — Indicadores (seguem os filtros da barra lateral)
# ---------------------------------------------------------------------
with aba_indicadores:
    st.subheader("Indicadores")
    st.caption("Os números consideram os filtros aplicados na barra lateral.")

    contagem = df_os_f["status"].value_counts().reindex(STATUS, fill_value=0)

    st.metric("Total de OS", int(contagem.sum()))
    colunas = st.columns(len(STATUS))
    for col, status in zip(colunas, STATUS):
        col.metric(f"{STATUS_ICONE[status]} {status}", int(contagem[status]))

    st.markdown("#### OS por status")
    grafico = pd.DataFrame({"Status": STATUS, "Quantidade": contagem.values})
    st.bar_chart(grafico, x="Status", y="Quantidade", sort=False)
