# Misrtal AI — Render

Полноценный агентный кодинг (Claude Code style):
- тёмный UI (чат, мысли, файлы, диффы)
- план → Accept / Reject
- Codestral tool-calling
- Cloudinary realtime
- upload любых файлов

## Деплой на Render (5 мин)

1. Залей эту папку на GitHub (новый репо)
2. [render.com](https://render.com) → New → Web Service → Connect repo
3. Settings:
   - **Runtime:** Python
   - **Build:** `pip install -r requirements.txt`
   - **Start:** `uvicorn server:app --host 0.0.0.0 --port $PORT`
4. **Environment** → Add:
   - `MISTRAL_API_KEY` = ключ с https://console.mistral.ai/
   - `MISTRAL_MODEL` = `codestral-latest` (опционально)
   - Cloudinary (опционально):
     - `CLOUDINARY_CLOUD_NAME`
     - `CLOUDINARY_API_KEY`
     - `CLOUDINARY_API_SECRET`
5. Create Web Service → жди деплой → открой URL

Или через Blueprint: New → Blueprint → этот `render.yaml`.

## Локально

```bash
pip install -r requirements.txt
cp .env.example .env   # впиши ключ
python server.py
# http://localhost:7860
```

## Важно

- Free tier Render засыпает ~15 мин без трафика — первый запрос после сна ~30 сек
- Файлы workspace на free **не персистентны** между деплоями — Cloudinary для сохранения
- Ключи только в Environment, не в код
