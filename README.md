# Atividade2-Luiza
Gerenciamento de OS - Banco de Dados na nuvem + Gradio + Streamlit 
# TechFix Informática — Sistema de Ordens de Serviço

Atividade Aula 2: integração de interface web (**Gradio**) e painel administrativo (**Streamlit**) com banco de dados em nuvem (**Supabase / PostgreSQL**).

| Aplicação | Arquivo | Uso |
|---|---|---|
| Atendimento | `app_gradio.py` | Balcão ou celular: cadastra cliente, equipamento e problema |
| Painel administrativo | `app_streamlit.py` | Gerente/técnico: consulta, filtra, cadastra, edita, exclui e acompanha indicadores |
| Banco de dados | `sql/schema.sql` | Tabelas, restrições, índices, trigger, view e políticas de acesso |

```
[Celular / Navegador]        [Navegador do Gerente]
          |                            |
   App Gradio (cadastro)    App Streamlit (gerenciamento)
          |      supabase-py (API REST)      |
          +-----------> SUPABASE <-----------+
                  (PostgreSQL na nuvem)
```

## Estrutura

```
techfix/
├── sql/
│   ├── schema.sql               # script completo de criação do banco
│   └── testes_constraints.sql   # testes das restrições (dados fictícios)
├── app_gradio.py                # interface de cadastro
├── app_streamlit.py             # painel de gerenciamento
├── requirements.txt             # dependências
├── .env.example                 # nomes das variáveis, sem valores
├── .streamlit/
│   └── secrets.toml.example     # alternativa ao .env para o Streamlit
├── .gitignore                   # ignora .env e secrets.toml
├── README.md
└── evidencias/                  # prints das telas e das tabelas
```

## 1. Banco de dados (Supabase)

1. Crie um projeto em [supabase.com](https://supabase.com).
2. No **SQL Editor**, execute `sql/schema.sql`.
3. (Opcional) Execute `sql/testes_constraints.sql` para conferir as restrições. Todos os testes devem retornar `OK` ou `BLOQUEADO`; o script apaga os dados de teste ao final.

### Modelagem

- **clientes**: `id` (PK, identity), `nome`, `endereco`, `email` (UNIQUE), `celular_whatsapp`, `data_cadastro` (padrão `now()`).
- **ordens_servico**: `id` (PK, número da OS), `cliente_id` (FK → clientes), `modelo_computador`, `problema_relatado`, `status`, `data_abertura` (padrão `now()`), `data_atualizacao`.
- Relacionamento 1:N: um cliente pode ter várias OS ao longo do tempo.

### Regras de integridade

| Regra | Implementação |
|---|---|
| Chave primária | `generated always as identity primary key` nas duas tabelas |
| Chave estrangeira | `ordens_servico.cliente_id → clientes.id` com **`ON DELETE CASCADE`** (excluir o cliente exclui as OS dele) |
| Campos essenciais | `NOT NULL` + `CHECK` impedindo textos só com espaços |
| E-mail | `UNIQUE` + `CHECK` com expressão regular de formato |
| Celular | `CHECK (celular_whatsapp ~ '^[0-9]{10,13}$')`: somente dígitos, 10 a 13 |
| Status | `CHECK` aceitando apenas `Aberto`, `Em análise`, `Aguardando peça`, `Concluído`, `Entregue` (padrão `Aberto`) |

Também foram criados:

- **Índices** na FK, no status e em `lower(nome)`, para os filtros do painel.
- **Trigger** `trg_os_data_atualizacao`, que atualiza `data_atualizacao` a cada alteração da OS.
- **View** `vw_ordens_servico` (OS + dados do cliente) com `security_invoker = true`, usada no painel.
- **RLS (Row Level Security)** ativo nas duas tabelas, com políticas de `select/insert/update/delete` para o papel `anon`.
  > Como a atividade não tem login de usuários, o CRUD foi liberado para a chave pública. Em produção, o correto seria exigir autenticação (papel `authenticated`) ou um backend próprio.

## 2. Instalação

Requer Python 3.10 ou superior.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    |    Linux/Mac: source .venv/bin/activate
pip install -r requirements.txt
```

### Credenciais

Copie `.env.example` para `.env` e preencha com a **Project URL** e a chave **anon/publishable** (Supabase → Project Settings → API):

```
SUPABASE_URL=https://<seu-projeto>.supabase.co
SUPABASE_KEY=<chave anon ou publishable>
```

O painel Streamlit também aceita `.streamlit/secrets.toml` (veja o `.example`). O `.env` e o `secrets.toml` estão no `.gitignore`, e nenhuma chave aparece no código.

## 3. Execução

### Atendimento (Gradio)

```bash
python app_gradio.py
```

Abre um endereço local e um **link público temporário** (`*.gradio.live`, gerado por `share=True`) para usar no celular.

- O formulário é feito com `gr.Blocks`, `gr.Row` e `gr.Column`; em telas pequenas as colunas são empilhadas.
- Antes de gravar, valida os campos obrigatórios, o formato do e-mail e se o celular tem só números (10 a 13 dígitos).
- **Cadastrar**: se o e-mail já existir, a OS é vinculada ao mesmo cliente; senão, o cliente é criado. A OS é aberta com status `Aberto` e a mensagem mostra o número dela.
- **Limpar**: esvazia todos os campos.

### Painel administrativo (Streamlit)

```bash
streamlit run app_streamlit.py
```

- **Barra lateral**: filtros por nome, e-mail e status, aplicados a todas as abas.
- **Consultar**: tabela de OS com os dados do cliente e botão **Exportar CSV** dos dados filtrados (desafio opcional).
- **Cadastrar**: abertura manual de nova OS, com as mesmas regras do Gradio.
- **Editar/Excluir**: alterar o status da OS e editar os dados do cliente. As exclusões pedem confirmação; a de cliente avisa quantas OS serão apagadas junto.
- **Indicadores**: `st.metric` com o total e a quantidade por status, e `st.bar_chart` com as OS por status.

## 4. Segurança e boas práticas

- As credenciais ficam fora do código (`.env` / `secrets.toml`), e esses arquivos estão no `.gitignore`.
- Usa-se apenas a chave pública (anon). A `service_role` nunca é usada.
- Toda operação no banco fica em `try/except`, com mensagens amigáveis (falha de rede, permissão negada, e-mail duplicado, formato inválido).
- A validação é feita em duas camadas: na aplicação, antes do envio, e no banco, pelas restrições `CHECK`/`UNIQUE`.
- Os testes usam apenas dados fictícios (LGPD).

## 5. Evidências

Veja a pasta `evidencias/`:

| Item | Arquivo |
|---|---|
| Testes das restrições no SQL Editor | `00_sql_testes_restricoes.png` |
| (a) Tela do Gradio no celular | `celular_gradio.jpg` |
| (b) Mensagem de cadastro realizado | `cadastro_realizado.jpg` |
| (c) Tabelas no Table Editor do Supabase | `table_supabase1.png`, `table_supabase2.png`, `table_supabase3.png` |
| (d) Painel Streamlit: consulta, edição e indicadores | `d1_streamlit_consultar.png`, `d2_streamlit_editar_excluir.png`, `d3_streamlit_indicadores.png` |
| (e) Painel Streamlit Celular: consulta, edição e indicadores | `celular_streamlit1.jpg`, `celular_streamlit2.jpg`, `celular_streamlit3.jpg`, `celular_streamlit4.jpg`, `celular_streamlit5.jpg` |
