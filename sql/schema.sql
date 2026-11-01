-- =====================================================================
-- TechFix Informática — Sistema de Ordens de Serviço
-- Script de criação do banco (Supabase / PostgreSQL)
-- Executar no SQL Editor do Supabase.
-- =====================================================================

-- ---------------------------------------------------------------------
-- 0. (Opcional) Limpeza para reexecutar o script do zero.
--    ATENÇÃO: apaga todos os dados. Descomente apenas se necessário.
-- ---------------------------------------------------------------------
-- drop view  if exists public.vw_ordens_servico;
-- drop table if exists public.ordens_servico;
-- drop table if exists public.clientes;
-- drop function if exists public.fn_atualiza_data_atualizacao();


-- ---------------------------------------------------------------------
-- 1. Tabela CLIENTES
--    Um cliente pode ter várias ordens de serviço ao longo do tempo
--    (relacionamento 1:N com ordens_servico).
-- ---------------------------------------------------------------------
create table public.clientes (
    -- Chave primária gerada automaticamente pelo banco
    id                bigint generated always as identity primary key,

    -- Campos essenciais: NOT NULL e não podem ser só espaços
    nome              text not null
                      constraint ck_clientes_nome_nao_vazio
                      check (length(trim(nome)) > 0),

    endereco          text not null
                      constraint ck_clientes_endereco_nao_vazio
                      check (length(trim(endereco)) > 0),

    -- E-mail único e com formato básico válido (algo@dominio.ext)
    email             text not null
                      constraint uq_clientes_email unique
                      constraint ck_clientes_email_formato
                      check (email ~* '^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$'),

    -- Celular/WhatsApp: somente dígitos, de 10 a 13 caracteres
    -- (ex.: 11987654321 ou 5511987654321)
    celular_whatsapp  text not null
                      constraint ck_clientes_celular_formato
                      check (celular_whatsapp ~ '^[0-9]{10,13}$'),

    -- Data de cadastro preenchida automaticamente
    data_cadastro     timestamptz not null default now()
);

comment on table  public.clientes is 'Clientes da TechFix Informática';
comment on column public.clientes.celular_whatsapp is 'Somente dígitos, 10 a 13 caracteres';


-- ---------------------------------------------------------------------
-- 2. Tabela ORDENS_SERVICO
--    Cada OS pertence a um cliente (chave estrangeira).
--    ON DELETE CASCADE: ao excluir um cliente, suas OS são excluídas.
-- ---------------------------------------------------------------------
create table public.ordens_servico (
    -- Chave primária (é o "número da OS" exibido ao usuário)
    id                 bigint generated always as identity primary key,

    -- Chave estrangeira para clientes, com comportamento de exclusão definido
    cliente_id         bigint not null
                       constraint fk_os_cliente
                       references public.clientes (id)
                       on update cascade
                       on delete cascade,

    modelo_computador  text not null
                       constraint ck_os_modelo_nao_vazio
                       check (length(trim(modelo_computador)) > 0),

    problema_relatado  text not null
                       constraint ck_os_problema_nao_vazio
                       check (length(trim(problema_relatado)) > 0),

    -- Status restrito aos valores permitidos; toda OS nasce 'Aberto'
    status             text not null default 'Aberto'
                       constraint ck_os_status
                       check (status in ('Aberto', 'Em análise', 'Aguardando peça',
                                         'Concluído', 'Entregue')),

    data_abertura      timestamptz not null default now(),
    data_atualizacao   timestamptz not null default now()
);

comment on table public.ordens_servico is 'Ordens de serviço (equipamentos recebidos para reparo)';


-- ---------------------------------------------------------------------
-- 3. Índices para acelerar consultas e filtros do painel
-- ---------------------------------------------------------------------
-- Índice na FK (o PostgreSQL não cria automaticamente)
create index idx_os_cliente_id on public.ordens_servico (cliente_id);

-- Filtro por status no painel Streamlit
create index idx_os_status on public.ordens_servico (status);

-- Busca por nome do cliente (sem diferenciar maiúsculas/minúsculas)
create index idx_clientes_nome_lower on public.clientes (lower(nome));


-- ---------------------------------------------------------------------
-- 4. Trigger: mantém data_atualizacao sempre atualizada
--    Toda vez que uma OS for alterada (ex.: mudança de status),
--    a coluna data_atualizacao recebe a data/hora atual.
-- ---------------------------------------------------------------------
create or replace function public.fn_atualiza_data_atualizacao()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
    new.data_atualizacao := now();
    return new;
end;
$$;

create trigger trg_os_data_atualizacao
before update on public.ordens_servico
for each row
execute function public.fn_atualiza_data_atualizacao();


-- ---------------------------------------------------------------------
-- 5. View de apoio: OS + dados do cliente (usada no painel Streamlit)
--    security_invoker = true faz a view respeitar as políticas RLS
--    das tabelas de origem.
-- ---------------------------------------------------------------------
create view public.vw_ordens_servico
with (security_invoker = true)
as
select
    os.id                 as os_id,
    os.status,
    os.modelo_computador,
    os.problema_relatado,
    os.data_abertura,
    os.data_atualizacao,
    c.id                  as cliente_id,
    c.nome,
    c.email,
    c.celular_whatsapp,
    c.endereco
from public.ordens_servico os
join public.clientes c on c.id = os.cliente_id;


-- ---------------------------------------------------------------------
-- 6. Segurança: Row Level Security (RLS) e políticas de acesso
--    O Supabase expõe as tabelas pela API REST. Com RLS ativo, nada é
--    acessível sem uma política explícita.
--    Para esta atividade acadêmica (sem login de usuários), liberamos o
--    CRUD para a chave pública (role "anon"). Em produção, o ideal seria
--    exigir autenticação (role "authenticated") ou usar backend próprio.
-- ---------------------------------------------------------------------
alter table public.clientes       enable row level security;
alter table public.ordens_servico enable row level security;

-- Permissões de tabela para os papéis usados pela API
grant select, insert, update, delete on public.clientes       to anon, authenticated;
grant select, insert, update, delete on public.ordens_servico to anon, authenticated;
grant select                         on public.vw_ordens_servico to anon, authenticated;

-- Políticas da tabela CLIENTES
create policy "clientes_select" on public.clientes
    for select to anon, authenticated using (true);

create policy "clientes_insert" on public.clientes
    for insert to anon, authenticated with check (true);

create policy "clientes_update" on public.clientes
    for update to anon, authenticated using (true) with check (true);

create policy "clientes_delete" on public.clientes
    for delete to anon, authenticated using (true);

-- Políticas da tabela ORDENS_SERVICO
create policy "os_select" on public.ordens_servico
    for select to anon, authenticated using (true);

create policy "os_insert" on public.ordens_servico
    for insert to anon, authenticated with check (true);

create policy "os_update" on public.ordens_servico
    for update to anon, authenticated using (true) with check (true);

create policy "os_delete" on public.ordens_servico
    for delete to anon, authenticated using (true);

-- =====================================================================
-- Fim do script
-- =====================================================================
