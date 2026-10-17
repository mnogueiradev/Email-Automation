# ADR 0001: Stack inicial e limites do primeiro incremento

- **Data:** 2026-10-13
- **Estado:** Aceita para iniciar a implementação

## Contexto

O projeto parte de uma pasta vazia, sem repositório Git ou aplicação existente. A stack aprovada para planejamento é Python, FastAPI, TiDB com SQLAlchemy/PyMySQL/Alembic, worker separado e Postfix condicionado à viabilidade da Oracle Cloud.

## Decisão

- Usar Python 3.12+ e um monólito modular.
- Usar FastAPI/Uvicorn para a API, Pydantic Settings para configuração e SQLAlchemy/PyMySQL para persistência futura.
- Preparar a conexão TiDB com CA e verificação de certificado e hostname obrigatórias.
- Manter a API em loopback por padrão.
- Iniciar com uma rota de saúde de processo, sem acesso a dados.
- Adiar schema, migrações, worker e envio até que seus contratos e critérios estejam definidos.

## Consequências

- O primeiro incremento pode ser executado e inspecionado sem credenciais, TiDB, OCI ou MTA.
- A conexão com o banco não é comprovada até haver credenciais e teste de integração em ambiente autorizado.
- As faixas de dependência estão definidas, mas o lockfile ainda depende da disponibilidade do runtime Python aprovado.

## Riscos e pendências

- O ambiente disponível tem Python 3.10.11; não atende ao requisito de runtime.
- O acesso ao cluster existente e qualquer migração continuam fora deste incremento.
- A saída SMTP na OCI e a exposição de qualquer rota pública seguem condicionadas à validação e aprovação específicas.

## Atualização

O schema relacional e as operações locais iniciais foram implementados posteriormente; ver [ADR 0002](0002-schema-inicial.md). A decisão de manter o usuário runtime sem privilégios DDL permanece vigente.
