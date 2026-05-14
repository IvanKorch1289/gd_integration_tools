-- LangMem baseline migration: таблица для episodic, semantic и procedural памяти.
-- K4 Sprint-3 Wave 1: LangMem baseline.
--
-- Схема:
--   entry_id     — UUID, первичный ключ
--   kind         — тип памяти: episodic | semantic | procedural
--   agent_id     — идентификатор агента-владельца
--   content      — текстовое содержимое
--   metadata     — произвольный JSONB-контекст
--   timestamp    — время создания (UTC)
--   embedding_id — point_id в Qdrant (только для kind='semantic'; NULL иначе)

CREATE TABLE IF NOT EXISTS langmem_entries (
    entry_id UUID PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('episodic', 'semantic', 'procedural')),
    agent_id TEXT NOT NULL,
    content TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}',
    timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
    embedding_id TEXT  -- Qdrant point ID, NULL if not semantic
);

CREATE INDEX IF NOT EXISTS idx_langmem_agent_kind ON langmem_entries(agent_id, kind);
CREATE INDEX IF NOT EXISTS idx_langmem_metadata ON langmem_entries USING GIN (metadata);
