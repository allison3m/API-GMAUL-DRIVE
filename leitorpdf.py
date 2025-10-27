# main_sanitized.py — versão sanitizada para GitHub
import os
import datetime
import json
import base64
import io
import re
from dotenv import load_dotenv

# carregue .env local (opcional)
load_dotenv()

GOOGLE_TOKEN_PATH = os.getenv("GOOGLE_TOKEN_PATH", "token.json")  # caminho local: NÃO comitar
DRIVE_FOLDER_ID = os.getenv("DRIVE_FOLDER_ID")  # > IMPORTANTE: definir no .env local / secrets
GMAIL_QUERY = os.getenv("GMAIL_QUERY", "GRUPAMENTO APOIO DIST FEDERAL")
ENABLE_DEBUG_FILES = os.getenv("ENABLE_DEBUG_FILES", "false").lower() in ("1", "true", "yes")

# imports do Google dentro de try para falhar graciosamente em ambientes sem libs
try:
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
except Exception as e:
    print("Instale as dependências Google: google-api-python-client google-auth-httplib2 google-auth-oauthlib")
    raise

import pdfplumber  # pip install pdfplumber

def get_month_range():
    hoje = datetime.date.today()
    primeiro_dia = hoje.replace(day=1)
    if hoje.month == 12:
        proximo_mes = hoje.replace(year=hoje.year + 1, month=1, day=1)
    else:
        proximo_mes = hoje.replace(month=hoje.month + 1, day=1)
    ultimo_dia = proximo_mes - datetime.timedelta(days=1)
    return primeiro_dia, ultimo_dia

def limpar_valor(texto):
    if not texto:
        return None
    texto = texto.replace(' ', '')
    if '.' in texto and ',' in texto:
        texto = texto.replace('.', '')
        texto = texto.replace(',', '.')
    elif ',' in texto:
        texto = texto.replace(',', '.')
    elif '.' in texto:
        partes = texto.split('.')
        if len(partes[-1]) == 2 and len(partes) > 1:
            pass
        else:
            texto = texto.replace('.', '')
    try:
        return float(texto)
    except:
        return None

def extrair_dados_pdf(texto_completo):
    dados = {
        "valor_liquido": None,
        "retencao_lei": None,
        "codigo_debito": None,
        "matricula": None,
        "referencia": None,
        "vencimento": None,
        "emissao": None,
        "apresentacao": None,
        "arquivo": None
    }
    # (regex igual ao seu; mantive as tentativas)
    match = re.search(r'GRUPAMENTO.*?FEDERAL.*?\*+\s*R?\$?\s*([\d.,]+)', texto_completo, re.IGNORECASE | re.DOTALL)
    if match:
        dados["valor_liquido"] = limpar_valor(match.group(1))
    if not dados["valor_liquido"]:
        match = re.search(r'TOTAL\s+A\s+PAGAR.*?\*+\s*R?\$?\s*([\d.,]+)', texto_completo, re.IGNORECASE | re.DOTALL)
        if match:
            dados["valor_liquido"] = limpar_valor(match.group(1))
    if not dados["valor_liquido"]:
        match = re.search(r'\*{5,}\s*R?\$?\s*([\d.,]+)', texto_completo)
        if match:
            dados["valor_liquido"] = limpar_valor(match.group(1))
    if not dados["valor_liquido"]:
        match = re.search(r'R?\$\s*([\d]+[.,]\d{2})', texto_completo)
        if match:
            dados["valor_liquido"] = limpar_valor(match.group(1))
    match = re.search(r'VENCIMENTO\s+(\d{2}/\d{2}/\d{4})', texto_completo, re.IGNORECASE)
    if not match:
        match = re.search(r'VENCIMENTO.*?(\d{2}/\d{2}/\d{4})', texto_completo, re.IGNORECASE | re.DOTALL)
    if match:
        dados["vencimento"] = match.group(1).strip()
    # resto dos campos
    m = re.search(r'RET\.?\s*LEI\s*9430/96\s+([\d.,]+)\s*-', texto_completo, re.IGNORECASE)
    if m:
        dados["retencao_lei"] = limpar_valor(m.group(1))
    m = re.search(r'Cód\.\s*débito\s*automático\s*([\d.\-]+)', texto_completo, re.IGNORECASE) or re.search(r'(\d{3}\.\d{2}\.\d{8}-\d)', texto_completo)
    if m:
        dados["codigo_debito"] = m.group(1).strip()
    m = re.search(r'MATR[IÍ]CULA\s+([\d\s]+\d)', texto_completo, re.IGNORECASE)
    if m:
        dados["matricula"] = m.group(1).strip()
    m = re.search(r'REFER[EÊ]NCIA.*?(\d{2}/\d{4})', texto_completo, re.IGNORECASE)
    if m:
        dados["referencia"] = m.group(1).strip()
    m = re.search(r'(\d{2}/\d{2}/\d{4})\s*\(data\s+emiss[aã]o\)', texto_completo, re.IGNORECASE)
    if m:
        dados["emissao"] = m.group(1).strip()
    m = re.search(r'Data\s+da\s+apresenta[cç][aã]o\s*(\d{2}/\d{2}/\d{4})', texto_completo, re.IGNORECASE)
    if m:
        dados["apresentacao"] = m.group(1).strip()
    return dados

def listar_arquivos_email(service, message_id):
    msg = service.users().messages().get(userId="me", id=message_id, format="full").execute()
    anexos_pdf = []
    resultados = []
    def percorrer_partes(parts):
        for part in parts:
            filename = part.get("filename")
            mime = part.get("mimeType", "")
            body = part.get("body", {})
            att_id = body.get("attachmentId")
            if "parts" in part:
                percorrer_partes(part["parts"])
            if filename and att_id and (filename.lower().endswith(".pdf") or mime == "application/pdf"):
                anexos_pdf.append((filename, att_id))
    parts = msg.get("payload", {}).get("parts", [])
    percorrer_partes(parts)
    if not anexos_pdf:
        return []
    for nome, att_id in anexos_pdf:
        if "tutorial" in nome.lower():
            continue
        anexo = service.users().messages().attachments().get(userId="me", messageId=message_id, id=att_id).execute()
        dados_bytes = base64.urlsafe_b64decode(anexo["data"])
        arquivo_memoria = io.BytesIO(dados_bytes)
        texto_completo = ""
        try:
            with pdfplumber.open(arquivo_memoria) as pdf:
                for page in pdf.pages:
                    texto = page.extract_text()
                    if texto:
                        texto_completo += texto + "\n"
        except Exception as e:
            print("Erro ao ler PDF:", e)
            continue
        if not texto_completo.strip():
            continue
        if ENABLE_DEBUG_FILES:
            debug_file = f"debug_texto_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            with open(debug_file, "w", encoding="utf-8") as f:
                f.write(texto_completo)
        dados_extraidos = extrair_dados_pdf(texto_completo)
        dados_extraidos["arquivo"] = nome
        resultados.append(dados_extraidos)
    return resultados

def main():
    if not os.path.exists(GOOGLE_TOKEN_PATH):
        print("token.json não encontrado localmente. Gere com o fluxo de auth (quickstart) e NÃO comite-o.")
        return
    if not DRIVE_FOLDER_ID:
        print("⚠️ DRIVE_FOLDER_ID não definido. Defina a variável de ambiente DRIVE_FOLDER_ID antes de rodar.")
        return

    creds = Credentials.from_authorized_user_file(GOOGLE_TOKEN_PATH)
    service = build("gmail", "v1", credentials=creds)

    inicio, fim = get_month_range()
    query = f'{GMAIL_QUERY} after:{inicio.strftime("%Y/%m/%d")} before:{fim.strftime("%Y/%m/%d")}'
    results = service.users().messages().list(userId="me", labelIds=["INBOX"], q=query).execute()
    messages = results.get("messages", [])

    if not messages:
        print("Nenhum e-mail encontrado nesse período.")
        return

    todos_dados = []
    for msg in messages:
        msg_id = msg["id"]
        dados = listar_arquivos_email(service, msg_id)
        todos_dados.extend(dados)

    if todos_dados:
        nome_arquivo = f"faturas_{datetime.date.today().strftime('%Y%m%d')}.json"
        # NÃO comitar este json se contém dados pessoais — salve localmente e armazene com segurança
        with open(nome_arquivo, "w", encoding="utf-8") as f:
            json.dump(todos_dados, f, indent=2, ensure_ascii=False)
        print(f"Arquivo JSON criado: {nome_arquivo} — verifique antes de commitar.")
    else:
        print("Nenhum dado extraído.")
if __name__ == "__main__":
    main()
