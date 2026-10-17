# CV-Automation

Plataforma local de automação de e-mails para campanhas de contato. A base persistente usa TiDB Serverless com SQLAlchemy/Alembic e conexão TLS com validação do certificado e hostname.

## Requisitos locais

- Python 3.12 ou superior.
- Acesso ao TiDB não é necessário para iniciar a API de saúde.

## Preparação no Windows

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
cv-automation-api
```

A API escuta em `127.0.0.1:8000` por padrão. A rota `GET /health/live` confirma apenas que o processo está respondendo; ela não testa o banco nem o transporte de e-mail. A documentação interativa fica disponível em `/docs` somente no ambiente de desenvolvimento.

As rotas de dados ficam em `/api/v1` e exigem `Authorization: Bearer <token>`. Um token local aleatório foi gravado no `.env` desta instalação. Para outra instalação, gere um token com `python -c "import secrets; print(secrets.token_urlsafe(48))"` e configure `CV_AUTOMATION_API_TOKEN` no `.env`. A API recusa qualquer endereço de escuta que não seja loopback nesta etapa.

## Configuração do TiDB

As variáveis `CV_AUTOMATION_DB_*` são opcionais para a rota de saúde. Para habilitar a conexão, configure todas em um `.env` protegido, incluindo o caminho do certificado CA. O engine usa `URL.create`, exige verificação do certificado e da identidade do servidor, e define o fuso da sessão como UTC. A conexão não é aberta automaticamente durante a inicialização da API.

Não coloque credenciais em `.env.example`, no Git, em URLs copiadas para logs ou em mensagens de erro. A conta da aplicação deve manter somente permissões de leitura e escrita de dados. Migrações Alembic precisam de uma conta de implantação com privilégios DDL no banco `email_automation`; não amplie os privilégios da conta da aplicação para esse fim.

## Estrutura persistente inicial

A primeira migração cria `contacts`, `email_suppressions`, `email_templates`, `campaigns`, `email_jobs` e `email_attempts`. Ela é aditiva e não remove dados. O downgrade automático da migração inicial é bloqueado para evitar exclusão acidental. Os endereços são mantidos na fila como snapshot; conteúdo de CV e erros SMTP brutos não são armazenados nessas tabelas.

Para aplicar migrações em um ambiente com credenciais DDL, execute `python -m alembic upgrade head`. A conta configurada no `.env` deste projeto é a conta runtime e não deve receber permissões de criação ou alteração de schema. No TiDB Cloud, também é possível aplicar a versão SQL gerada por `python -m alembic upgrade head --sql` usando uma sessão administrativa do SQL Editor.

A API local permite cadastrar e consultar contatos, criar supressões, templates e campanhas, adicionar destinatários ativos não suprimidos a uma campanha em rascunho e agendá-la. Agendar a campanha não envia e-mail. O processo `cv-automation-worker` é separado da API e só inicia quando executado explicitamente.

## Worker e SMTP

Antes de iniciar o worker, configure no `.env` o host e o endereço remetente SMTP. Se o servidor exigir autenticação, configure também usuário e senha. O transporte exige STARTTLS ou TLS implícito com validação de certificado; conexão sem criptografia não é aceita. A senha fica somente no `.env` local.

`cv-automation-worker --once` processa um lote elegível e encerra. `cv-automation-worker` monitora a fila continuamente. Se o comando não estiver disponível no ambiente, use `.\.venv\Scripts\python.exe -m app.worker_cli --once` ou remova `--once` para monitoramento contínuo. Ambos podem enviar e-mails reais das campanhas já agendadas, portanto revise destinatários e templates antes de iniciá-los. O worker verifica a lista de supressão novamente imediatamente antes de cada envio.

O worker registra tentativas e usa retentativas exponenciais para respostas SMTP temporárias. Falhas que deixam incerto se o servidor aceitou a mensagem ficam em estado `uncertain` e não são repetidas automaticamente. A resolução desses casos ainda é manual.

O fluxo aparece em `/docs`: `POST /contacts` → `POST /templates` → `POST /campaigns` → `POST /campaigns/{id}/recipients` → `POST /campaigns/{id}/schedule`. Consulte os destinatários e seus estados em `GET /campaigns/{id}/jobs`. As rotas de dados precisam do bearer token armazenado no `.env`.

## Dependências

O `pyproject.toml` define faixas de versões compatíveis. Ainda não há lockfile; ele será adicionado quando o gerenciador de ambiente for escolhido.
