-- =====================================================================
-- Seed inicial — usuário admin padrão
-- ATENÇÃO: troque a senha no primeiro login!
-- Credenciais iniciais:
--   usuário: admin
--   senha:   admin123
-- =====================================================================

INSERT INTO users (username, full_name, email, password_hash, role)
VALUES (
    'admin',
    'Administrador',
    NULL,
    -- bcrypt hash de "admin123" (cost=12)
    '$2b$12$3cW6RtqF1rQR49MGOqzviu32eQwavDpER6ZNV8jMVjnDVuDVas3nC',
    'ADMIN'
)
ON CONFLICT (username) DO NOTHING;

-- Equipes do evento (poderia virar tabela futura, por ora está como constante em utils.py)
-- Alguns vendedores de exemplo — remova ou edite à vontade:
INSERT INTO sellers (name, active) VALUES
    ('Caixa 01', TRUE),
    ('Caixa 02', TRUE),
    ('Caixa 03', TRUE)
ON CONFLICT DO NOTHING;
