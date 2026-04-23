# Sistema Mercadinho — Versão Cloud

Sistema de Estoque + PDV multiusuário hospedado na nuvem. Migração do app Streamlit
local original para funcionar com PostgreSQL e autenticação.

> **Evento:** VI Despertar 2026
> **Stack:** Streamlit · PostgreSQL · bcrypt · Altair

---

## ✨ O que mudou em relação à versão local

| Antes (local) | Agora (cloud) |
|---|---|
| SQLite num arquivo `.db` | PostgreSQL gerenciado (Neon/Supabase) |
| Sem autenticação | Login com bcrypt + papéis (ADMIN / OPERADOR / GERENCIAL) |
| Monolito de 1.410 linhas em `app.py` | Módulos (`db.py`, `auth.py`, `views/*.py`) |
| Sem log de quem fez o quê | Tabela `audit_log` com trilha completa |
| PDV sem lock de linha | `SELECT ... FOR UPDATE` — 10 caixas simultâneos sem overselling |
| Roda só no PC da secretaria | Qualquer navegador, qualquer lugar |

---

## 🚀 Deploy em 5 passos (~20 minutos)

### Passo 1 — Criar o banco PostgreSQL (Neon, grátis)

1. Acesse [neon.tech](https://neon.tech) e crie uma conta
2. Clique em **Create Project**
   - Name: `estoque-pdv`
   - Postgres version: 16 (padrão)
   - Region: escolha a mais próxima do Brasil (ex: AWS US East)
3. Depois de criado, vá em **Connection Details** e copie a **Connection string** no formato:
   ```
   postgresql://user:senha@ep-xxxx.aws.neon.tech/neondb?sslmode=require
   ```

> **Alternativa:** [Supabase](https://supabase.com) funciona do mesmo jeito.
> A única diferença é a URL de conexão.

### Passo 2 — Aplicar o schema e o seed

No seu terminal local (com `psql` instalado) — ou pelo **SQL Editor** do Neon:

```bash
# Opção A: via psql local
psql "SUA_CONNECTION_STRING" -f schema.sql
psql "SUA_CONNECTION_STRING" -f seed.sql

# Opção B: no painel do Neon/Supabase → SQL Editor → cole o conteúdo e execute
```

Isso cria todas as tabelas (`users`, `products`, `sales`, etc.) e o usuário inicial:

| Usuário | Senha | Papel |
|---|---|---|
| `admin` | `admin123` | ADMIN |

> ⚠️ **Troque a senha no primeiro login** em Configurações → Meu perfil.

### Passo 3 — Subir o código pro GitHub

```bash
cd estoque_pdv_cloud/
git init
git add .
git commit -m "Migração inicial pra cloud"
git branch -M main
git remote add origin https://github.com/SEU_USUARIO/estoque-pdv.git
git push -u origin main
```

> O `.gitignore` já bloqueia `.streamlit/secrets.toml` — **nunca** commite ele.

### Passo 4 — Deploy no Streamlit Community Cloud

1. Acesse [share.streamlit.io](https://share.streamlit.io) e faça login com o GitHub
2. Clique em **Create app → Deploy a public app from GitHub**
3. Configure:
   - Repository: `SEU_USUARIO/estoque-pdv`
   - Branch: `main`
   - Main file path: `app.py`
   - App URL: escolha um subdomínio (ex: `mercadinho-despertar`)
4. **Antes de clicar em Deploy**, abra **Advanced settings → Secrets** e cole:

```toml
[postgres]
url = "postgresql://user:senha@ep-xxxx.aws.neon.tech/neondb?sslmode=require"

[app]
instance_name = "VI Despertar 2026"
session_secret = "troque-isso-por-um-valor-aleatorio-longo-no-mínimo-32-chars"
```

5. Clique em **Deploy** — em ~2 minutos sua URL está no ar.

### Passo 5 — Primeiro login e ajustes

1. Abra a URL do app, entre com `admin` / `admin123`
2. Vá em **Configurações → Meu perfil** e troque a senha
3. Em **Configurações → Novo usuário**, crie contas pros operadores de caixa
4. Cadastre produtos (ou importe do SQLite antigo — ver seção abaixo)
5. Cadastre vendedores/caixas

---

## 🔄 Migrando dados do sistema antigo (SQLite → Postgres)

Se você já tem dados no `estoque_pdv.db` local, rode uma vez:

```bash
# Instale as deps do script (psycopg)
pip install 'psycopg[binary]'

# Configure a URL do banco e rode
export DATABASE_URL='postgresql://user:senha@ep-xxxx.aws.neon.tech/neondb?sslmode=require'
python scripts/migrate_from_sqlite.py /caminho/para/estoque_pdv.db
```

O script preserva os IDs originais e ajusta as sequences automaticamente.
É idempotente (`ON CONFLICT DO NOTHING`), então pode rodar de novo sem medo.

---

## 💻 Rodando localmente (dev)

```bash
# 1) Clonar e entrar no projeto
git clone https://github.com/SEU_USUARIO/estoque-pdv.git
cd estoque-pdv

# 2) Venv + deps
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 3) Secrets
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# edite com sua URL do Neon

# 4) Rodar
streamlit run app.py
```

Abre em `http://localhost:8501`.

---

## 📁 Estrutura do projeto

```
estoque_pdv_cloud/
├── app.py                    # Entrypoint: login gate + router
├── db.py                     # Pool de conexões, query(), transaction()
├── auth.py                   # Login, bcrypt, require_role()
├── audit.py                  # Log de auditoria
├── utils.py                  # money_fmt, constantes, export Excel
├── schema.sql                # DDL PostgreSQL (idempotente)
├── seed.sql                  # Admin padrão + vendedores exemplo
├── requirements.txt
├── .gitignore
├── .streamlit/
│   ├── config.toml           # Tema verde/teal
│   └── secrets.toml.example  # Template (o real não vai pro git)
├── views/                    # Uma página = um arquivo
│   ├── pdv.py                # ⭐ PDV com lock de linha
│   ├── produtos.py
│   ├── vendedores.py
│   ├── consignantes.py
│   ├── movimentacoes.py
│   ├── fiado.py              # Gestão de vendas em aberto
│   ├── dashboard.py          # KPIs, gráficos, rankings
│   └── config.py             # Gestão de usuários + audit log
├── scripts/
│   └── migrate_from_sqlite.py
└── assets/
    └── despertar_logo.png
```

---

## 🔐 Papéis e permissões

| Ação | ADMIN | OPERADOR | GERENCIAL |
|---|:---:|:---:|:---:|
| Ver Dashboard | ✅ | ✅ | ✅ |
| Operar PDV (vender) | ✅ | ✅ | ❌ |
| Consultar produtos | ✅ | ✅ | ✅ |
| Criar/editar produto | ✅ | ✅ | ❌ |
| Excluir produto | ✅ | ❌ | ❌ |
| Registrar movimentação de estoque | ✅ | ✅ | ❌ |
| Quitar venda fiada | ✅ | ✅ | ❌ |
| Cadastrar vendedores / consignantes | ✅ | ❌ | ❌ |
| Gerenciar usuários | ✅ | ❌ | ❌ |
| Ver log de auditoria | ✅ | ❌ | ❌ |

Exclusão de produto com histórico: mesmo ADMIN não consegue apagar —
o sistema desativa (`active = false`) para preservar a trilha de vendas.

---

## 🧪 Concorrência no PDV (por que isso importa)

O problema clássico: dois caixas finalizam venda do último item ao mesmo tempo.
Sem tratamento, ambos passam pela checagem de estoque e ambos decrementam,
deixando o estoque negativo.

A solução está em `views/pdv.py → _finalize_sale()`:

```python
with transaction() as conn:
    # Trava as linhas dos produtos até o commit
    conn.execute(
        "SELECT id, stock FROM products WHERE id = ANY(%s) FOR UPDATE",
        [product_ids]
    )
    # Re-valida estoque (pode ter mudado)
    ...
    # INSERT sales, INSERT sale_items, UPDATE products.stock, INSERT movements
    # Tudo atômico. Commit ou rollback total.
```

`FOR UPDATE` em PostgreSQL serializa acesso às linhas: o segundo caixa espera
o primeiro commitar, e aí revalida. Sem overselling, sem deadlock (IDs em
ordem via `ANY(array)`).

---

## 🐛 Troubleshooting

**"connection refused" ou timeout ao fazer login**
- Verifique se a Connection String tem `?sslmode=require` no final.
- Neon faz "scale to zero" após inatividade — primeira requisição demora 2-5s.

**"permission denied for table users"**
- Rode o `schema.sql` com o mesmo usuário que o app usa (dono do banco).

**Deploy no Streamlit Cloud dá "ModuleNotFoundError"**
- Confira que o `requirements.txt` está na raiz do repo.
- Limpe o cache: App settings → Reboot app.

**Admin esqueceu a senha e não tem outro admin**
- No SQL Editor do Neon, rode:
  ```sql
  -- Hash de "nova_senha_temp" (substitua)
  UPDATE users SET password_hash = '$2b$12$...' WHERE username = 'admin';
  ```
  Gere o hash com: `python -c "import bcrypt; print(bcrypt.hashpw(b'nova_senha_temp', bcrypt.gensalt()).decode())"`

**Dashboard lento com muitas vendas**
- Os índices em `schema.sql` cobrem os casos principais. Se passar de ~100k vendas,
  considere particionar `sales` por mês ou criar materialized views pros KPIs.

---

## 🗺️ Roadmap

### Fase 2 (próxima iteração)
- [ ] Importação em massa de produtos via Excel
- [ ] Impressão de comprovante (PDF) após venda
- [ ] Relatório de repasse de consignantes com filtros
- [ ] Gráfico de evolução horária (útil no meio do evento)

### Fase 3 (pós-evento)
- [ ] App mobile pro caixa (PWA ou React Native)
- [ ] Integração com gateway de pagamento (Asaas / Mercado Pago)
- [ ] Controle de caixa (abertura/fechamento, sangria)
- [ ] Backup automático pro S3 / R2

### Fase 4 (produto)
- Avaliar reescrita em FastAPI + Next.js caso Streamlit vire gargalo (>50 usuários simultâneos).

---

## 📝 Licença

Uso interno Kynera / VI Despertar.
