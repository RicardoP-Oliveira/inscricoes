CREATE EXTENSION IF NOT EXISTS pgcrypto;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'status_evento') THEN
    CREATE TYPE status_evento AS ENUM ('RASCUNHO','ABERTO','ENCERRADO','FINALIZADO');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'status_inscricao') THEN
    CREATE TYPE status_inscricao AS ENUM ('PENDENTE_CONFIRMACAO','CONFIRMADO','LISTA_ESPERA',
      'CONVOCADO_LISTA_ESPERA','EXPIRADO','CANCELADO','PRESENTE','CERTIFICADO_LIBERADO');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'tipo_vaga') THEN
    CREATE TYPE tipo_vaga AS ENUM ('TITULAR','RESERVA');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'perfil_usuario') THEN
    CREATE TYPE perfil_usuario AS ENUM ('ADMIN','ORGANIZADOR','APOIO');
  END IF;
END $$;

CREATE TABLE usuario (
  id serial PRIMARY KEY,
  nome text NOT NULL,
  username text NOT NULL UNIQUE,
  email text,
  senha_hash text NOT NULL,
  perfil perfil_usuario NOT NULL DEFAULT 'APOIO',
  ativo boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE evento (
  id serial PRIMARY KEY,
  titulo text NOT NULL,
  descricao text,
  data_evento timestamptz NOT NULL,
  local text,
  vagas_titulares int NOT NULL CHECK (vagas_titulares > 0),
  vagas_reserva int NOT NULL DEFAULT 0 CHECK (vagas_reserva >= 0),
  prazo_confirmacao_horas int NOT NULL DEFAULT 24 CHECK (prazo_confirmacao_horas > 0),
  status status_evento NOT NULL DEFAULT 'RASCUNHO',
  inscricoes_encerram_em timestamptz,
  criado_por_id int REFERENCES usuario(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX evento_status_idx ON evento (status, data_evento);

CREATE TABLE evento_usuario (
  evento_id int NOT NULL REFERENCES evento(id) ON DELETE CASCADE,
  usuario_id int NOT NULL REFERENCES usuario(id) ON DELETE CASCADE,
  papel perfil_usuario NOT NULL,
  PRIMARY KEY (evento_id, usuario_id)
);

CREATE TABLE inscricao (
  id bigserial PRIMARY KEY,
  evento_id int NOT NULL REFERENCES evento(id) ON DELETE CASCADE,
  nome text NOT NULL,
  documento text NOT NULL,
  email text NOT NULL,
  telefone text,
  status status_inscricao NOT NULL,
  tipo_vaga tipo_vaga NOT NULL,
  origem_lista_espera boolean NOT NULL DEFAULT false,
  ordem_espera int,
  prazo_confirmacao_horas int NOT NULL,
  ocupa_vaga boolean GENERATED ALWAYS AS (
    status IN ('PENDENTE_CONFIRMACAO','CONVOCADO_LISTA_ESPERA',
                     'CONFIRMADO','PRESENTE','CERTIFICADO_LIBERADO')) STORED,
  token_hash text,
  token_expira_em timestamptz,
  convocado_em timestamptz,
  confirmado_em timestamptz,
  presente_em timestamptz,
  cancelado_em timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ordem_positiva CHECK (ordem_espera IS NULL OR ordem_espera > 0),
  CONSTRAINT email_normalizado CHECK (email = lower(email))
);
CREATE UNIQUE INDEX inscricao_doc_viva ON inscricao (evento_id, documento)
  WHERE status NOT IN ('EXPIRADO','CANCELADO');
CREATE UNIQUE INDEX inscricao_token_unico ON inscricao (token_hash)
  WHERE token_hash IS NOT NULL;
CREATE UNIQUE INDEX inscricao_ordem_unica ON inscricao (evento_id, ordem_espera)
  WHERE ordem_espera IS NOT NULL;
CREATE INDEX inscricao_fila_idx ON inscricao (evento_id, ordem_espera)
  WHERE status = 'LISTA_ESPERA';
CREATE INDEX inscricao_vencendo_idx ON inscricao (token_expira_em)
  WHERE status IN ('PENDENTE_CONFIRMACAO','CONVOCADO_LISTA_ESPERA');
CREATE INDEX inscricao_ocupa_idx ON inscricao (evento_id) WHERE ocupa_vaga;

CREATE TABLE inscricao_historico (
  id bigserial PRIMARY KEY,
  inscricao_id bigint NOT NULL REFERENCES inscricao(id) ON DELETE CASCADE,
  status_anterior status_inscricao,
  status_novo status_inscricao NOT NULL,
  motivo text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE email_outbox (
  id bigserial PRIMARY KEY,
  inscricao_id bigint REFERENCES inscricao(id) ON DELETE CASCADE,
  destinatario text NOT NULL,
  assunto text NOT NULL,
  corpo text NOT NULL,
  enviado_em timestamptz,
  erro text,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX email_pendente_idx ON email_outbox (id) WHERE enviado_em IS NULL;

CREATE TABLE sessao (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  usuario_id int NOT NULL REFERENCES usuario(id) ON DELETE CASCADE,
  token_hash text NOT NULL UNIQUE,
  csrf_token text NOT NULL,
  ip inet,
  user_agent text,
  criado_em timestamptz NOT NULL DEFAULT now(),
  expira_em timestamptz NOT NULL,
  revogada_em timestamptz
);

CREATE TABLE tentativa_login (
  id bigserial PRIMARY KEY,
  username text,
  ip inet,
  sucesso boolean NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX tentativa_ip_idx ON tentativa_login (ip, created_at DESC);

CREATE VIEW vw_evento_funil AS
SELECT e.id AS evento_id,
  count(i.id) FILTER (WHERE i.status NOT IN ('EXPIRADO','CANCELADO')) AS inscritos,
  count(i.id) FILTER (WHERE i.status IN ('CONFIRMADO','PRESENTE','CERTIFICADO_LIBERADO')) AS confirmados,
  count(i.id) FILTER (WHERE i.status IN ('PRESENTE','CERTIFICADO_LIBERADO')) AS presentes,
  count(i.id) FILTER (WHERE i.status = 'LISTA_ESPERA') AS na_fila,
  count(i.id) FILTER (WHERE i.status = 'CONVOCADO_LISTA_ESPERA') AS convocados,
  count(i.id) FILTER (WHERE i.status IN ('EXPIRADO','CANCELADO')) AS perdidos
FROM evento e LEFT JOIN inscricao i ON i.evento_id = e.id
GROUP BY e.id;

CREATE VIEW vw_evento_inscricoes_dia AS
SELECT evento_id,
       (created_at AT TIME ZONE 'America/Sao_Paulo')::date AS dia,
       count(*) AS total,
       count(*) FILTER (WHERE tipo_vaga = 'RESERVA') AS reservas
FROM inscricao GROUP BY 1, 2;

CREATE VIEW vw_evento_ocupacao AS
SELECT e.id AS evento_id, e.titulo, e.status, e.data_evento,
       e.vagas_titulares, e.vagas_reserva,
       count(i.id) FILTER (WHERE i.ocupa_vaga) AS ocupantes,
       e.vagas_titulares - count(i.id) FILTER (WHERE i.ocupa_vaga) AS livres,
       round(100.0 * count(i.id) FILTER (WHERE i.ocupa_vaga) / e.vagas_titulares, 1) AS pct_ocupacao
FROM evento e LEFT JOIN inscricao i ON i.evento_id = e.id
GROUP BY e.id, e.titulo, e.status, e.data_evento, e.vagas_titulares, e.vagas_reserva;
