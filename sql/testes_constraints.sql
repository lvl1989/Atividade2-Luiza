-- =====================================================================
-- TechFix — Testes das restrições do schema (dados fictícios)
-- Executar no SQL Editor do Supabase. Ao final, os dados de teste
-- são removidos (ON DELETE CASCADE também é testado).
-- =====================================================================
create temp table if not exists _testes (teste text, resultado text);
truncate _testes;

do $$
declare v_cli bigint; v_os bigint; v_t1 timestamptz; v_t2 timestamptz;
begin
  -- 1-2. Inserções válidas
  insert into public.clientes (nome, endereco, email, celular_whatsapp)
  values ('Cliente Teste', 'Rua Fictícia, 100', 'teste@exemplo.com', '11987654321') returning id into v_cli;
  insert into _testes values ('1. insert cliente válido', 'OK id=' || v_cli);

  insert into public.ordens_servico (cliente_id, modelo_computador, problema_relatado)
  values (v_cli, 'Notebook Fictício X1', 'Não liga') returning id, data_atualizacao into v_os, v_t1;
  insert into _testes select '2. insert OS (status padrão)', 'OK status=' || status from public.ordens_servico where id = v_os;

  -- 3-9. Inserções/alterações inválidas (devem ser bloqueadas)
  begin insert into public.clientes (nome, endereco, email, celular_whatsapp) values ('Outro','Rua B','teste@exemplo.com','11999999999');
        insert into _testes values ('3. e-mail duplicado', 'FALHOU (aceitou)');
  exception when unique_violation then insert into _testes values ('3. e-mail duplicado', 'BLOQUEADO: ' || sqlerrm); end;

  begin insert into public.clientes (nome, endereco, email, celular_whatsapp) values ('Outro','Rua B','email-invalido','11999999999');
        insert into _testes values ('4. e-mail inválido', 'FALHOU (aceitou)');
  exception when check_violation then insert into _testes values ('4. e-mail inválido', 'BLOQUEADO: ' || sqlerrm); end;

  begin insert into public.clientes (nome, endereco, email, celular_whatsapp) values ('Outro','Rua B','b@exemplo.com','(11)9999-999');
        insert into _testes values ('5. celular com símbolos', 'FALHOU (aceitou)');
  exception when check_violation then insert into _testes values ('5. celular com símbolos', 'BLOQUEADO: ' || sqlerrm); end;

  begin insert into public.clientes (nome, endereco, email, celular_whatsapp) values ('Outro','Rua B','c@exemplo.com','123456789');
        insert into _testes values ('6. celular 9 dígitos', 'FALHOU (aceitou)');
  exception when check_violation then insert into _testes values ('6. celular 9 dígitos', 'BLOQUEADO: ' || sqlerrm); end;

  begin update public.ordens_servico set status = 'Cancelado' where id = v_os;
        insert into _testes values ('7. status inválido', 'FALHOU (aceitou)');
  exception when check_violation then insert into _testes values ('7. status inválido', 'BLOQUEADO: ' || sqlerrm); end;

  begin insert into public.ordens_servico (cliente_id, modelo_computador, problema_relatado) values (999999, 'X', 'Y');
        insert into _testes values ('8. FK cliente inexistente', 'FALHOU (aceitou)');
  exception when foreign_key_violation then insert into _testes values ('8. FK cliente inexistente', 'BLOQUEADO: ' || sqlerrm); end;

  begin insert into public.clientes (nome, endereco, email, celular_whatsapp) values ('   ','Rua B','d@exemplo.com','11999999999');
        insert into _testes values ('9. nome em branco', 'FALHOU (aceitou)');
  exception when check_violation then insert into _testes values ('9. nome em branco', 'BLOQUEADO: ' || sqlerrm); end;

  -- 10. Trigger de data_atualizacao
  --     Dentro de um mesmo bloco, now() é sempre o horário de início da
  --     transação. Por isso o teste tenta gravar uma data antiga (2000) e
  --     confere se o trigger a substituiu pela data atual.
  update public.ordens_servico
     set status = 'Em análise', data_atualizacao = '2000-01-01'
   where id = v_os
  returning data_atualizacao into v_t2;
  insert into _testes values ('10. trigger data_atualizacao',
    case when v_t2 > '2000-01-02'::timestamptz then 'OK (trigger sobrescreveu com now())' else 'FALHOU' end);

  -- 11. View
  insert into _testes select '11. view vw_ordens_servico', 'OK linhas=' || count(*) from public.vw_ordens_servico;

  -- 12. ON DELETE CASCADE (e limpeza dos dados de teste)
  delete from public.clientes where id = v_cli;
  insert into _testes select '12. ON DELETE CASCADE', case when count(*) = 0 then 'OK (OS removida junto)' else 'FALHOU' end
    from public.ordens_servico where id = v_os;
end $$;

select * from _testes;

-- Reinicia a numeração (as tabelas ficaram vazias após o teste),
-- para que o primeiro cadastro real seja o cliente 1 e a OS 1.
alter table public.clientes       alter column id restart with 1;
alter table public.ordens_servico alter column id restart with 1;
