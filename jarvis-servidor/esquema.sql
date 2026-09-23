-- Esquema do servidor de licenças.
--
-- SQLite por enquanto, com todo o SQL isolado em banco.py: trocar por
-- Postgres depois é mexer num arquivo só. Nada aqui usa recurso exclusivo do
-- SQLite justamente por isso.

CREATE TABLE IF NOT EXISTS usuarios (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    email       TEXT    NOT NULL UNIQUE,
    senha_hash  TEXT    NOT NULL,
    nome        TEXT    NOT NULL DEFAULT '',
    admin       INTEGER NOT NULL DEFAULT 0,
    bloqueado   INTEGER NOT NULL DEFAULT 0,
    criado_em   TEXT    NOT NULL
);

-- Uma assinatura por usuário. Sem gateway ainda: quem muda estes campos é o
-- painel administrativo, quando o Pix cai.
CREATE TABLE IF NOT EXISTS assinaturas (
    usuario_id         INTEGER PRIMARY KEY REFERENCES usuarios(id) ON DELETE CASCADE,
    plano              TEXT    NOT NULL DEFAULT 'base',
    aparelhos_pagos    INTEGER NOT NULL DEFAULT 0,
    validade           TEXT,                              -- ISO; nulo = nunca ativada
    situacao           TEXT    NOT NULL DEFAULT 'vencida', -- ativa | vencida | bloqueada
    provedor           TEXT    NOT NULL DEFAULT 'manual',
    referencia_externa TEXT    NOT NULL DEFAULT '',        -- id no gateway, no dia que houver
    atualizado_em      TEXT    NOT NULL
);

-- `impressao` é o hash da impressão digital do aparelho, nunca o dado bruto:
-- se este banco vazar, ninguém remonta o identificador da máquina de ninguém.
CREATE TABLE IF NOT EXISTS aparelhos (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id    INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    impressao     TEXT    NOT NULL,
    apelido       TEXT    NOT NULL DEFAULT '',
    plataforma    TEXT    NOT NULL DEFAULT '',
    criado_em     TEXT    NOT NULL,
    ultimo_acesso TEXT    NOT NULL,
    UNIQUE (usuario_id, impressao)
);

-- Uma linha por sessão. O refresh token só existe aqui como hash: quem ler o
-- banco não consegue se passar por ninguém.
CREATE TABLE IF NOT EXISTS sessoes (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id   INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    aparelho_id  INTEGER NOT NULL REFERENCES aparelhos(id) ON DELETE CASCADE,
    refresh_hash TEXT    NOT NULL UNIQUE,
    criado_em    TEXT    NOT NULL,
    expira_em    TEXT    NOT NULL,
    revogada_em  TEXT
);

-- Toda recusa vira linha aqui: é onde o abuso aparece (mesma conta tentando
-- dez aparelhos, senha errada em série, licença vencida insistindo).
CREATE TABLE IF NOT EXISTS recusas (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    quando    TEXT NOT NULL,
    email     TEXT NOT NULL DEFAULT '',
    impressao TEXT NOT NULL DEFAULT '',
    motivo    TEXT NOT NULL,
    detalhe   TEXT NOT NULL DEFAULT '',
    ip        TEXT NOT NULL DEFAULT ''
);

-- Histórico bruto do que o gateway mandou, para conferir depois sem depender
-- do painel dele. `evento_id` é único para o mesmo aviso não valer duas vezes.
CREATE TABLE IF NOT EXISTS eventos_cobranca (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    provedor   TEXT NOT NULL,
    evento_id  TEXT NOT NULL,
    tipo       TEXT NOT NULL DEFAULT '',
    usuario_id INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    conteudo   TEXT NOT NULL DEFAULT '',
    recebido_em TEXT NOT NULL,
    UNIQUE (provedor, evento_id)
);

-- Pedidos de compra vindos do site. Nascem sem dono quando a pessoa ainda
-- nao tem conta; o `usuario_id` e preenchido assim que ela cria uma com o
-- mesmo e-mail.
CREATE TABLE IF NOT EXISTS pedidos (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id   INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    email        TEXT    NOT NULL,
    nome         TEXT    NOT NULL DEFAULT '',
    telefone     TEXT    NOT NULL DEFAULT '',
    plano        TEXT    NOT NULL DEFAULT 'base',
    aparelhos    INTEGER NOT NULL DEFAULT 0,   -- adicionais pedidos
    observacao   TEXT    NOT NULL DEFAULT '',
    situacao     TEXT    NOT NULL DEFAULT 'novo',  -- novo | atendido | recusado
    quando       TEXT    NOT NULL,
    atendido_em  TEXT,
    ip           TEXT    NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_pedidos_situacao ON pedidos(situacao);

-- De onde cada aparelho se conectou. Uma linha por (aparelho, IP), com
-- contagem: um cliente honesto troca de IP o tempo todo (roteador reiniciou,
-- celular mudou de antena), entao guardar um registro por acesso encheria o
-- banco sem dizer mais nada.
CREATE TABLE IF NOT EXISTS acessos (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id  INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    aparelho_id INTEGER REFERENCES aparelhos(id) ON DELETE CASCADE,
    ip          TEXT    NOT NULL,
    primeiro    TEXT    NOT NULL,
    ultimo      TEXT    NOT NULL,
    vezes       INTEGER NOT NULL DEFAULT 1,
    UNIQUE (aparelho_id, ip)
);

-- IPs que voce bloqueou na mao, olhando a aba de acessos.
CREATE TABLE IF NOT EXISTS ips_bloqueados (
    ip      TEXT PRIMARY KEY,
    motivo  TEXT NOT NULL DEFAULT '',
    quando  TEXT NOT NULL,
    por     TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_acessos_usuario ON acessos(usuario_id);
CREATE INDEX IF NOT EXISTS idx_acessos_ip ON acessos(ip);

CREATE INDEX IF NOT EXISTS idx_sessoes_usuario  ON sessoes(usuario_id);
CREATE INDEX IF NOT EXISTS idx_sessoes_aparelho ON sessoes(aparelho_id);
CREATE INDEX IF NOT EXISTS idx_aparelhos_usuario ON aparelhos(usuario_id);
CREATE INDEX IF NOT EXISTS idx_recusas_quando   ON recusas(quando);
