CREATE TABLE evento (
  id serial PRIMARY KEY,
  titulo text NOT NULL,
  descricao text,
  data_evento timestamptz NOT NULL,
  local text,
  vagas_titulares int NOT NULL CHECK (vagas_titulares > 0),
  vagas_reserva int NOT NULL DEFAULT 0 CHECK (vagas_reserva >= 0),
  status text NOT NULL DEFAULT 'RASCUNHO',
  created_at timestamptz NOT NULL DEFAULT now()
);

INSERT INTO evento (titulo, descricao, data_evento, local,
                    vagas_titulares, vagas_reserva, status)
VALUES ('Treinamento de Brigada', 'Evento de teste da etapa 2',
        now() + interval '15 days', 'Auditorio', 30, 10, 'ABERTO');
