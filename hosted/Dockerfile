FROM python:3.11-slim

WORKDIR /app

COPY hosted/requirements.txt /app/hosted/requirements.txt
RUN pip install --no-cache-dir -r /app/hosted/requirements.txt

# Shared prompt builder + its bare-name deps.
COPY wim/api/prompt_builder.py /app/wim/api/
COPY wim/api/l1_pack.py        /app/wim/api/
COPY wim/api/domain_pack.py    /app/wim/api/
COPY wim/api/lang_packs        /app/wim/api/lang_packs

COPY hosted/ /app/hosted/

WORKDIR /app/hosted
ENV PORT=8080
EXPOSE 8080

CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-8080}"]
