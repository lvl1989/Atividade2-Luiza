"""
TechFix Informática — Aplicação de Atendimento (Gradio)

Formulário responsivo (PC e celular) para cadastrar o cliente, o
equipamento e o problema relatado, gravando no Supabase.

Execução:
    python app_gradio.py

Credenciais: lidas das variáveis de ambiente SUPABASE_URL e SUPABASE_KEY
(arquivo .env carregado com python-dotenv). Nunca escreva as chaves aqui.
"""

import os
import re

import gradio as gr
from dotenv import load_dotenv
from postgrest.exceptions import APIError
from supabase import Client, create_client

# ---------------------------------------------------------------------
# Configuração e conexão
# ---------------------------------------------------------------------
load_dotenv()  # carrega o .env (se existir) para as variáveis de ambiente

# Mesmas regras usadas nas restrições CHECK do schema.sql
REGEX_EMAIL = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
REGEX_CELULAR = re.compile(r"^[0-9]{10,13}$")

STATUS_INICIAL = "Aberto"

_supabase: Client | None = None


def get_supabase() -> Client:
    """Cria (uma única vez) e devolve o cliente Supabase."""
    global _supabase
    if _supabase is None:
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_KEY")
        if not url or not key:
            raise RuntimeError(
                "Credenciais do Supabase não encontradas. "
                "Crie o arquivo .env com SUPABASE_URL e SUPABASE_KEY (veja .env.example)."
            )
        _supabase = create_client(url, key)
    return _supabase


# ---------------------------------------------------------------------
# Validação
# ---------------------------------------------------------------------
def validar(nome, endereco, email, celular, modelo, problema) -> list[str]:
    """Devolve a lista de erros encontrados (vazia se tudo estiver certo)."""
    erros = []
    obrigatorios = {
        "Nome do Cliente": nome,
        "Endereço": endereco,
        "E-mail": email,
        "Celular/WhatsApp": celular,
        "Modelo do Computador": modelo,
        "Problema Apresentado": problema,
    }
    vazios = [rotulo for rotulo, valor in obrigatorios.items() if not valor]
    if vazios:
        erros.append("Preencha os campos obrigatórios: " + ", ".join(vazios) + ".")

    if email and not REGEX_EMAIL.match(email):
        erros.append("E-mail em formato inválido (exemplo: nome@dominio.com).")

    if celular and not celular.isdigit():
        erros.append("Celular/WhatsApp deve conter apenas números, sem espaços, traços ou parênteses.")
    elif celular and not REGEX_CELULAR.match(celular):
        erros.append("Celular/WhatsApp deve ter de 10 a 13 dígitos (exemplo: 11987654321).")

    return erros


# ---------------------------------------------------------------------
# Operações no banco
# ---------------------------------------------------------------------
def buscar_cliente_por_email(sb: Client, email: str) -> dict | None:
    resp = sb.table("clientes").select("id, nome").eq("email", email).limit(1).execute()
    return resp.data[0] if resp.data else None


def obter_ou_criar_cliente(sb: Client, nome, endereco, email, celular) -> tuple[dict, bool]:
    """
    Reaproveita o cliente se o e-mail já existir; senão, cria um novo.
    Devolve (cliente, criado_agora).
    """
    existente = buscar_cliente_por_email(sb, email)
    if existente:
        return existente, False

    try:
        resp = (
            sb.table("clientes")
            .insert({
                "nome": nome,
                "endereco": endereco,
                "email": email,
                "celular_whatsapp": celular,
            })
            .execute()
        )
        return resp.data[0], True
    except APIError as e:
        # Outro atendente pode ter cadastrado o mesmo e-mail no mesmo instante
        if e.code == "23505":
            existente = buscar_cliente_por_email(sb, email)
            if existente:
                return existente, False
        raise


def criar_ordem_servico(sb: Client, cliente_id: int, modelo: str, problema: str) -> dict:
    resp = (
        sb.table("ordens_servico")
        .insert({
            "cliente_id": cliente_id,
            "modelo_computador": modelo,
            "problema_relatado": problema,
            "status": STATUS_INICIAL,
        })
        .execute()
    )
    return resp.data[0]


def mensagem_erro_banco(e: APIError) -> str:
    """Traduz os erros mais comuns do PostgreSQL para mensagens amigáveis."""
    texto = f"{e.message or ''} {e.details or ''}"
    if e.code == "23514":  # violação de CHECK
        if "email" in texto:
            return "O banco recusou o e-mail: formato inválido."
        if "celular" in texto:
            return "O banco recusou o celular: use apenas números (10 a 13 dígitos)."
        return "O banco recusou os dados: algum campo está fora do formato permitido."
    if e.code == "23505":
        return "Já existe um cliente com este e-mail."
    if e.code in ("42501", "PGRST301"):
        return "Sem permissão para gravar no banco. Verifique a chave e as políticas de acesso (RLS)."
    return f"Erro no banco de dados: {e.message}"


# ---------------------------------------------------------------------
# Ações dos botões
# ---------------------------------------------------------------------
CAMPOS_VAZIOS = ("", "", "", "", "", "")


def cadastrar(nome, endereco, email, celular, modelo, problema):
    # Normalização: remove espaços nas pontas; e-mail sempre em minúsculas
    nome = (nome or "").strip()
    endereco = (endereco or "").strip()
    email = (email or "").strip().lower()
    celular = (celular or "").strip()
    modelo = (modelo or "").strip()
    problema = (problema or "").strip()
    valores_atuais = (nome, endereco, email, celular, modelo, problema)

    erros = validar(nome, endereco, email, celular, modelo, problema)
    if erros:
        msg = "### ⚠️ Corrija os dados abaixo\n" + "\n".join(f"- {e}" for e in erros)
        return (msg, *valores_atuais)

    try:
        sb = get_supabase()
        cliente, criado = obter_ou_criar_cliente(sb, nome, endereco, email, celular)
        os_ = criar_ordem_servico(sb, cliente["id"], modelo, problema)
    except RuntimeError as e:  # credenciais ausentes
        return (f"### ❌ Configuração incompleta\n{e}", *valores_atuais)
    except APIError as e:
        return (f"### ❌ Não foi possível cadastrar\n{mensagem_erro_banco(e)}", *valores_atuais)
    except Exception as e:  # rede, timeout etc.
        return (
            "### ❌ Não foi possível cadastrar\n"
            f"Falha de comunicação com o banco. Verifique a conexão e tente novamente.\n\n`{type(e).__name__}`",
            *valores_atuais,
        )

    situacao_cliente = (
        "Cliente **novo** cadastrado."
        if criado
        else f"Cliente **já cadastrado** reaproveitado ({cliente['nome']})."
    )
    msg = (
        f"### ✅ Ordem de Serviço nº {os_['id']} aberta com sucesso!\n"
        f"- {situacao_cliente}\n"
        f"- Status inicial: **{os_['status']}**\n\n"
        "O formulário foi limpo para o próximo atendimento."
    )
    # Limpa os campos após o sucesso (evita cadastrar a mesma OS duas vezes)
    return (msg, *CAMPOS_VAZIOS)


def limpar():
    return ("", *CAMPOS_VAZIOS)


# ---------------------------------------------------------------------
# Interface (gr.Blocks)
# ---------------------------------------------------------------------
with gr.Blocks(title="TechFix — Atendimento") as app:
    gr.Markdown(
        "# 🛠️ TechFix Informática — Abertura de Ordem de Serviço\n"
        "Preencha os dados do cliente e do equipamento e toque em **Cadastrar**. "
        "Se o e-mail já estiver cadastrado, a nova OS é vinculada ao mesmo cliente. "
        "Todos os campos são obrigatórios.\n\n"
        "*Use apenas dados fictícios nos testes (LGPD).*"
    )

    # Em telas pequenas, as colunas são empilhadas automaticamente (min_width)
    with gr.Row(equal_height=False):
        with gr.Column(min_width=300):
            gr.Markdown("### 👤 Dados do cliente")
            nome = gr.Textbox(label="Nome do Cliente", placeholder="Ex.: Maria da Silva")
            endereco = gr.Textbox(label="Endereço", placeholder="Ex.: Rua das Flores, 123 - Centro - Cidade/UF")
            with gr.Row():
                email = gr.Textbox(label="E-mail", placeholder="Ex.: maria@exemplo.com", type="email", min_width=200)
                celular = gr.Textbox(
                    label="Celular/WhatsApp",
                    placeholder="Somente números, com DDD. Ex.: 11987654321",
                    max_length=13,
                    min_width=200,
                )

        with gr.Column(min_width=300):
            gr.Markdown("### 💻 Equipamento")
            modelo = gr.Textbox(label="Modelo do Computador", placeholder="Ex.: Notebook Dell Inspiron 15 3520")
            problema = gr.Textbox(
                label="Problema Apresentado",
                placeholder="Descreva o defeito relatado pelo cliente. Ex.: não liga, tela azul ao iniciar...",
                lines=6,
            )

    with gr.Row():
        btn_cadastrar = gr.Button("Cadastrar", variant="primary", min_width=150)
        btn_limpar = gr.Button("Limpar", variant="secondary", min_width=150)

    resultado = gr.Markdown()

    campos = [nome, endereco, email, celular, modelo, problema]
    btn_cadastrar.click(cadastrar, inputs=campos, outputs=[resultado, *campos])
    btn_limpar.click(limpar, inputs=None, outputs=[resultado, *campos])


if __name__ == "__main__":
    # 0.0.0.0 aceita conexoes da rede local (sem isso o app fica preso no 127.0.0.1)
    # no celular, no mesmo Wi-Fi: http://192.168.0.46:7860  (conferir o IP com ipconfig)
    # share=True nao funciona nesta maquina: o Defender bloqueia o binario frpc do tunel
    app.launch(server_name="0.0.0.0", server_port=7860, theme=gr.themes.Soft())
