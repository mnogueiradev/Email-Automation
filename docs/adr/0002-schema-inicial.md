# ADR 0002: Schema relacional inicial

- **Data:** 2026-10-13
- **Estado:** Aceita

## Contexto

O banco lógico `email_automation` no cluster TiDB Serverless estava vazio e a conta runtime possui apenas permissões DML. O projeto precisa de persistência versionada antes de implementar rotas de domínio ou um worker.

## Decisão

- Usar Alembic para versionar a estrutura e SQLAlchemy 2 para mapear os registros.
- Criar contatos, supressões, templates, campanhas, jobs de envio e tentativas.
- Guardar um snapshot do endereço no job para que alterações posteriores no contato não mudem um envio já enfileirado.
- Registrar códigos estruturados de erro e resposta; não persistir corpos de CV nem texto SMTP bruto.
- Manter DDL fora da conta runtime. Aplicações usam DML; migrações usam sessão/credencial de implantação.
- Não oferecer downgrade automático para a migração inicial, pois removê-la apagaria dados.

## Consequências

- A criação da primeira versão de schema não interfere em tabelas antigas: o banco foi verificado vazio antes da migração.
- Na versão inicial, os estados eram strings sem uma enumeração rígida no banco.
- O worker, a reserva transacional da fila e o envio SMTP foram deixados para incrementos posteriores.

## Implementação posterior

O worker de fila e o transporte SMTP foram acrescentados depois desta decisão. Eles usam os campos de lease e tentativa definidos aqui; não foi necessária uma migração adicional. As transições de estado são controladas pelo worker e continuam armazenadas como strings.
