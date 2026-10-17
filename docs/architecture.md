# Arquitetura inicial

## Escopo implementado

O projeto é um monólito modular Python. Há configuração segura, API local protegida por token, engine TiDB com TLS validado, schema relacional versionado por Alembic e um worker de fila separado da API. O worker reserva lotes com `SELECT FOR UPDATE`, aplica leases e envia via SMTP com STARTTLS ou TLS implícito.

```text
Cliente local
    |
    v
FastAPI / Uvicorn (127.0.0.1 por padrão)
    |
    +-- configuração validada (Pydantic Settings)
    |
    +-- API /api/v1 (Bearer token) -> SQLAlchemy -> TiDB (TLS obrigatório)
    |
    +-- schema Alembic: contatos, supressões, templates, campanhas e fila
    |
    +-- worker CLI -> lease da fila -> checagem de supressão -> adapter SMTP/TLS
```

## Persistência inicial

- `contacts` guarda endereço, chave normalizada e dados profissionais básicos.
- `email_suppressions` bloqueia endereços que não devem receber novos envios.
- `email_templates` guarda assunto e corpos texto/HTML reutilizáveis.
- `campaigns` registra estado e agendamento.
- `email_jobs` é a fila durável, com snapshot do destinatário, disponibilidade, lease e resultado do envio.
- `email_attempts` guarda resultado estruturado de cada tentativa, sem corpo de mensagem nem texto SMTP bruto.

Os campos de estado são strings controladas pela aplicação. Datas usam UTC. Os endpoints de domínio só aceitam conexões loopback e exigem token Bearer. A API só cria templates; ainda não os edita. O agendamento cria uma campanha elegível para o worker; ele só envia quando o processo `cv-automation-worker` é iniciado explicitamente. O worker consulta supressões novamente antes de enviar, pois um endereço pode ser bloqueado depois de entrar na fila.

## Fila e entrega

- A reserva usa uma transação curta com `SELECT FOR UPDATE`, seguida pela atualização de estado para `processing` e de `locked_until`. Workers concorrentes podem aguardar a transação; a seleção ordenada e limitada mantém cada reserva pequena.
- Campanhas só entram na fila de entrega quando estão agendadas e `scheduled_at` já chegou. Um lease expirado sem tentativa SMTP iniciada pode ser reservado novamente.
- Uma tentativa SMTP sem resultado persistido quando o lease expira passa para `uncertain` e não é repetida automaticamente. Falhas de transporte com resposta SMTP 4xx usam retentativa exponencial; 5xx encerram como falha.
- A conclusão verifica a mesma data de lease usada na reserva. Isso impede um worker atrasado de sobrescrever a decisão de outro worker depois que perdeu a posse do job.
- O aceite SMTP seguido de falha ao gravar no TiDB ainda deixa uma janela de resultado ambíguo. Esse caso exige revisão manual; SMTP não fornece uma chave idempotente que torne TiDB e o servidor de e-mail uma transação única.
- A supressão é consultada imediatamente antes da chamada SMTP. Uma supressão inserida depois dessa checagem pode competir com um envio já iniciado.
- Campanhas terminam como `completed` ou `completed_with_issues`; jobs individuais usam `pending`, `processing`, `sent`, `failed`, `suppressed` ou `uncertain`.

O conteúdo do template é carregado no início de cada tentativa. A API não possui edição de template nesta etapa. Antes de adicionar edição, é necessário congelar uma versão do conteúdo por campanha.

## Limites de segurança

- A API inicia ligada a loopback e recusa configuração em endereço público nesta etapa.
- Rotas de dados exigem token Bearer guardado em `.env`; `/health/live` permanece sem autenticação e sem consultas ao banco.
- `/health/live` verifica somente o processo. Não revela configuração, estado do banco ou dados pessoais.
- A criação do engine exige configuração completa e um certificado CA existente; valida certificado e identidade TLS.
- A URL do banco é criada por campos separados, sem interpolar manualmente usuário e senha.
- A inicialização da API não abre conexão com o TiDB.
- O usuário runtime mantém permissões DML; migrações devem usar uma sessão de implantação com privilégio DDL.
- A migração inicial é aditiva e não oferece downgrade automático.
- O envio exige configuração SMTP local e não é iniciado junto com a API.

## Próximas etapas

1. Configurar e verificar o servidor SMTP e o endereço remetente antes de iniciar o worker.
2. Adicionar uma ferramenta operacional para revisar jobs `uncertain` e resolver falhas.
3. Versionar o conteúdo usado por campanhas agendadas antes de permitir edição de templates.
4. Definir necessidade e proteção de rotas públicas, como descadastro.
