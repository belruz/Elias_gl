import os
import time
import json
import requests
import datetime
import re
import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from typing import List, Dict, Set, Optional, Tuple
from PyPDF2 import PdfReader

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("scraper.log"),
        logging.StreamHandler()
    ]
)

YEAR = '2025'
DOWNLOAD_DIR_SII = "downloaded_pdfs"
DOWNLOAD_DIR_BCN = "downloaded_pdfs"
os.makedirs(DOWNLOAD_DIR_SII, exist_ok=True)
os.makedirs(DOWNLOAD_DIR_BCN, exist_ok=True)

try:
    EMAIL_SENDER = os.getenv("EMAIL_SENDER_TEST")
    EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD_TEST")
    EMAIL_RECIPIENTS = os.getenv("EMAIL_RECIPIENTS_TEST", "").split(",") 
    
    if not all([EMAIL_SENDER, EMAIL_PASSWORD, EMAIL_RECIPIENTS]):
        raise ValueError("Missing email credentials")
except Exception as e:
    logging.error(f"Email config error: {str(e)}")
    raise

ALLOWED_PREFIXES = [
    "reso", "VENTAS", "RENTA", "OTRAS_NORMAS_ORDINARIO", 
    "OTRAS_NORMAS_RESERVADO", "BCN", "circu"
]

class EmailSender:
    
    @staticmethod
    def send_email(subject: str, body: str, attachments: List[str] = None) -> bool:
        if attachments is None:
            attachments = []
        
        msg = MIMEMultipart()
        msg['From'] = EMAIL_SENDER
        msg['To'] = EMAIL_RECIPIENTS
        msg['Subject'] = subject

        msg.attach(MIMEText(body, 'plain'))

        for attachment in attachments:
            try:
                if not os.path.exists(attachment):
                    logging.warning(f"Attachment not found: {attachment}")
                    continue
                    
                with open(attachment, "rb") as file:
                    part = MIMEApplication(file.read(), _subtype='pdf')
                    part.add_header('Content-Disposition', 'attachment', 
                                  filename=os.path.basename(attachment))
                    msg.attach(part)
            except Exception as e:
                logging.error(f"Attachment error {attachment}: {str(e)}")
                continue

        max_retries = 3
        for attempt in range(max_retries):
            try:
                with smtplib.SMTP('smtp.gmail.com', 587) as server:
                    server.starttls()
                    server.login(EMAIL_SENDER, EMAIL_PASSWORD)
                    server.send_message(msg)
                    logging.info("Email sent successfully!")
                    return True
            except smtplib.SMTPAuthenticationError:
                logging.error("SMTP authentication error")
                break
            except Exception as e:
                logging.error(f"Attempt {attempt + 1} failed. Error: {e}")
                if attempt == max_retries - 1:
                    logging.error("Failed to send email after retries")
                    return False
                time.sleep(5)

        return False

class FileUtils:

    @staticmethod
    def get_pdf_metadata(pdf_paths: List[str]) -> Dict[str, Dict]:
        metadata_dict = {}
        
        for pdf_path in pdf_paths:
            try:
                if not os.path.exists(pdf_path):
                    logging.warning(f"Archivo PDF no encontrado: {pdf_path}")
                    continue
                
                with open(pdf_path, 'rb') as f:
                    reader = PdfReader(f)
                    raw_metadata = reader.metadata or {}
                    
                    full_text = ""
                    for page in reader.pages[:3]:
                        full_text += page.extract_text() or ""
                    
                    materia = "No disponible"
                    fecha = "No disponible"
                    
                    filename = os.path.basename(pdf_path)

                    def extract_date(text, filename):
                        end_patterns = [
                            r"se ha",
                            r"de acuerdo",
                            r"\. de acuerdo",
                            r"\. se ha",
                            r"1\. se ha"
                        ]
                        
                        cut_point = len(text)
                        for pattern in end_patterns:
                            match = re.search(pattern, text, re.IGNORECASE)
                            if match and match.start() < cut_point:
                                cut_point = match.start()
                        
                        search_text = text[:cut_point] if cut_point < len(text) else text
                        
                        patterns = [
                            r"(?:ORD\.|OFICIO|RESOLUCIÓN|CIRCULAR)\s*(?:N°|Nº|N[o°]\s*)?\d+\s*[,-]\s*DE\s*(\d{2}\.\d{2}\.\d{4})",
                            r"(\d{1,2}\s+DE\s+[A-ZÁÉÍÓÚÑ]+\s+DE\s+\d{4})",
                            r"(\d{2}-\w{3}-\d{4})",
                            r"SANTIAGO[,\s]*(\d{1,2}\s+DE\s+[A-ZÁÉÍÓÚÑ]+\s+DE\s+\d{4})",
                            r"FECHA\s*:\s*(\d{1,2}\s+DE\s+[A-ZÁÉÍÓÚÑ]+\s+DE\s+\d{4})",
                            r".*?_(\d{2}_\d{2}_\d{4})\.pdf",
                            r".*?-(\d{2}_\d{2}_\d{4})\.pdf"
                        ]

                        for pattern in patterns:
                            match = re.search(pattern, search_text, re.IGNORECASE)
                            if match:
                                date_str = match.group(1)
                                try:
                                    if "." in date_str:
                                        dia, mes, anio = date_str.split(".")
                                        meses = {
                                            "01": "ENERO", "02": "FEBRERO", "03": "MARZO", "04": "ABRIL",
                                            "05": "MAYO", "06": "JUNIO", "07": "JULIO", "08": "AGOSTO",
                                            "09": "SEPTIEMBRE", "10": "OCTUBRE", "11": "NOVIEMBRE", "12": "DICIEMBRE"
                                        }
                                        return f"{int(dia)} DE {meses[mes]} DE {anio}"
                                    elif "_" in date_str: 
                                        dia, mes, anio = date_str.split("_")
                                        meses = {
                                            "01": "ENERO", "02": "FEBRERO", "03": "MARZO", "04": "ABRIL",
                                            "05": "MAYO", "06": "JUNIO", "07": "JULIO", "08": "AGOSTO",
                                            "09": "SEPTIEMBRE", "10": "OCTUBRE", "11": "NOVIEMBRE", "12": "DICIEMBRE"
                                        }
                                        return f"{int(dia)} DE {meses[mes]} DE {anio}"
                                    elif "-" in date_str and len(date_str.split("-")[1]) == 3: 
                                        dia, mes_abr, anio = date_str.split("-")
                                        meses_abr = {
                                            "ENE": "ENERO", "FEB": "FEBRERO", "MAR": "MARZO", "ABR": "ABRIL",
                                            "MAY": "MAYO", "JUN": "JUNIO", "JUL": "JULIO", "AGO": "AGOSTO",
                                            "SEP": "SEPTIEMBRE", "OCT": "OCTUBRE", "NOV": "NOVIEMBRE", "DIC": "DICIEMBRE"
                                        }
                                        return f"{int(dia)} DE {meses_abr[mes_abr.upper()]} DE {anio}"
                                    else:  
                                        return date_str.upper()
                                except Exception as e:
                                    logging.warning(f"Error formateando fecha {date_str}: {str(e)}")
                                    continue

                        filename_patterns = [
                            r".*?_(\d{2}_\d{2}_\d{4})\.pdf",
                            r".*?-(\d{2}_\d{2}_\d{4})\.pdf"
                        ]
                        
                        for pattern in filename_patterns:
                            match = re.search(pattern, filename)
                            if match:
                                date_str = match.group(1)
                                dia, mes, anio = date_str.split("_")
                                meses = {
                                    "01": "ENERO", "02": "FEBRERO", "03": "MARZO", "04": "ABRIL",
                                    "05": "MAYO", "06": "JUNIO", "07": "JULIO", "08": "AGOSTO",
                                    "09": "SEPTIEMBRE", "10": "OCTUBRE", "11": "NOVIEMBRE", "12": "DICIEMBRE"
                                }
                                return f"{int(dia)} DE {meses[mes]} DE {anio}"
                        
                        return "No disponible"

                    if "BCN_Ley" in filename:
                        materia_match = re.search(
                        r"(Ley\s+\d{4,5}[\s\S]+?)(?=\n*(?:Publicación|Fecha Publicación)|\Z)",
                        full_text,
                        re.IGNORECASE
                    )
                        materia = materia_match.group(1).strip() if materia_match else "No disponible"
                        materia = re.sub(r'(\n\s*)+\n+', '\n\n', materia)
                        materia = re.sub(r'[ \t]{2,}', ' ', materia)
                        materia = re.sub(r'(?<=[A-Z])(ART[ÍI]CULO|ART\.)', r'\n\1', materia)

                        if len(materia) > 500:
                            materia = materia[:497] + '...'

                        fecha_match = re.search(r"Promulgación:\s*(\d{2}-\w{3}-\d{4})", full_text)
                        if not fecha_match:
                            fecha_match = re.search(r"Publicación:\s*(\d{2}-\w{3}-\d{4})", full_text)
                        fecha = fecha_match.group(1) if fecha_match else extract_date(full_text, filename)

                    elif "circu" in filename:
                        materia_match = re.search(
                            r"MATERIA\s*:\s*(.+?)(?=\n*(?:REF\.\s*LEGAL|REFERENCIA|SANTIAGO|[A-Z]{5,}:|\n\s*\n|$))", 
                            full_text, 
                            re.DOTALL | re.IGNORECASE
                        )

                        if not materia_match:
                            materia_match = re.search(
                                r"MATERIA\s+(.+?)(?=\n*(?:REF\.\s*LEGAL|REFERENCIA|SANTIAGO|[A-Z]{5,}:|\n\s*\n|$))", 
                                full_text, 
                                re.DOTALL | re.IGNORECASE
                            )

                        if not materia_match:
                            materia_match = re.search(
                                r"SISTEMA:\s*(.+?)(?=\n*(?:REF\.\s*LEGAL|REFERENCIA|SANTIAGO|[A-Z]{5,}:|\n\s*\n|$))", 
                                full_text, 
                                re.DOTALL | re.IGNORECASE
                            )

                        if not materia_match:
                            materia_match = re.search(
                                r"(SUBDIRECCIÓN[\s\S]+?)(?=\n*(?:REF\.\s*LEGAL|REFERENCIA|SANTIAGO|\Z))",
                                full_text,
                                re.IGNORECASE | re.DOTALL
                            )

                        if not materia_match:
                            materia_match = re.search(
                                r"(DIRECCIÓN[\s\S]+?)(?=\n*(?:REF\.\s*LEGAL|REFERENCIA|SANTIAGO|\Z))",
                                full_text,
                                re.IGNORECASE | re.DOTALL
                            )

                        materia = materia_match.group(1).strip() if materia_match else "No disponible"
                        materia = re.sub(r'\b[A-Z]{2,}\d{5,}\b|\b[A-Za-z]{1,}\s?\d{5,}\b|\b[A-Za-z0-9\-]{2,}\s?-?\d{4,}\s?\d{10,}\b', '', materia, flags=re.IGNORECASE).strip()

                        if len(materia) > 300:
                            materia = materia[:297] + '...'

                        fecha = extract_date(full_text, filename)
                        
                    elif "reso" in filename:
                        materia_match = re.search(
                            r"MATERIA\s*:\s*(.+?)(?=\n*(?:SANTIAGO|[A-Z]{5,}:|\n\s*\n|$))", 
                            full_text, 
                            re.DOTALL | re.IGNORECASE
                        )

                        if not materia_match:
                            materia_match = re.search(
                                r"MATERIA\s+(.+?)(?=\n*(?:SANTIAGO|[A-Z]{5,}:|\n\s*\n|$))", 
                                full_text, 
                                re.DOTALL | re.IGNORECASE
                            )

                        if not materia_match:
                            materia_match = re.search(
                                r"SISTEMA:\s*(.+?)(?=\n*(?:SANTIAGO|[A-Z]{5,}:|\n\s*\n|$))", 
                                full_text, 
                                re.DOTALL | re.IGNORECASE
                            )

                        if not materia_match:
                            materia_match = re.search(
                                r"(SUBDIRECCIÓN[\s\S]+?)(?=\n*(?:SANTIAGO|\Z))",
                                full_text,
                                re.IGNORECASE
                            )

                        if not materia_match:
                            materia_match = re.search(
                                r"(DIRECCIÓN[\s\S]+?)(?=\n*(?:SANTIAGO|\Z))",
                                full_text,
                                re.IGNORECASE
                            )

                        if not materia_match:
                            materia_match = re.search(
                                r"(.*?)(?=\n*SANTIAGO,\s*\d{1,2}\s+DE\s+[A-ZÁÉÍÓÚÑ]+\s+DE\s+\d{4}\.?)",
                                full_text,
                                re.DOTALL | re.IGNORECASE
                            )

                        materia = materia_match.group(1).strip() if materia_match else "No disponible"
                        materia = re.sub(r'\b[A-Z]{2,}\d{5,}\b|\b[A-Za-z]{1,}\s?\d{5,}\b|\b[A-Za-z0-9\-]{2,}\s?-?\d{4,}\s?\d{10,}\b', '', materia, flags=re.IGNORECASE).strip()

                        if len(materia) > 500:
                            materia = materia[:497] + '...'
                    
                        fecha = extract_date(full_text, filename)

                    elif "RENTA" in filename:
                            # Intenta el método original primero
                        materia_match = re.search(
                            r"(RENTA(?: – LEY SOBRE IMPUESTO A LA)?[\s\S]+?)(?=\n*(De acuerdo|Se ha|$))",
                            full_text,
                            re.IGNORECASE
                            )
                            
                         # Si falla, intenta el método alternativo para documentos de IVA/Ventas
                        if not materia_match:
                            materia_match = re.search(
                                    r"(VENTAS Y SERVICIOS – LEY SOBRE IMPUESTO A LAS[\s\S]+?)(?=\n*(De acuerdo|Se ha|$))",
                                    full_text,
                                    re.IGNORECASE
                                )
                            
                        materia = materia_match.group(1).strip() if materia_match else "No disponible"
                        materia = re.sub(r'(\n\s*)+\n+', '\n\n', materia)
                        materia = re.sub(r'[ \t]{2,}', ' ', materia)
                        materia = re.sub(r'(?<=[A-Z])(ART[ÍI]CULO|ART\.)', r'\n\1', materia)
                        materia = re.sub(r'\b[A-Z]{2,}\d{5,}\b|\b[A-Za-z]{1,}\s?\d{5,}\b|\b[A-Za-z0-9\-]{2,}\s?-?\d{4,}\s?\d{10,}\b', '', materia, flags=re.IGNORECASE).strip()

                        if len(materia) > 600:
                            materia = materia[:597] + '...'

                        fecha = extract_date(full_text, filename)

                    elif "VENTAS" in filename:
                        materia_match = re.search(
                            r"(VENTAS Y SERVICIOS(?: – LEY SOBRE IMPUESTO A LA)?[\s\S]+?)(?=\n*(?:Se ha|De acuerdo|1\.|$))",
                            full_text,
                            re.IGNORECASE
                        )

                        materia = materia_match.group(1).strip() if materia_match else "No disponible"
                        materia = re.sub(r'(\n\s*)+\n+', '\n\n', materia)
                        materia = re.sub(r'[ \t]{2,}', ' ', materia)
                        materia = re.sub(r'(?<=[A-Z])(ART[ÍI]CULO|ART\.)', r'\n\1', materia)
                        materia = re.sub(r'\b[A-Z]{2,}\d{5,}\b|\b[A-Za-z]{1,}\s?\d{5,}\b|\b[A-Za-z0-9\-]{2,}\s?-?\d{4,}\s?\d{10,}\b', '', materia, flags=re.IGNORECASE).strip()

                        if len(materia) > 600:
                            materia = materia[:597] + '...'
                        
                        fecha = extract_date(full_text, filename)
                    #Mejorar esta parte
                    elif "OTRAS_NORMAS" in filename:
                        materia_match = re.search(
                            r"(.*?)(?=\n*(?:Se ha|De acuerdo))",
                            full_text,
                            re.DOTALL | re.IGNORECASE
                        )
                        
                        if materia_match:
                            materia = materia_match.group(1).strip()
                        else:
                            clean_text = re.sub(r'[ \t]{2,}', ' ', full_text.strip())
                            clean_text = re.sub(r'(\n\s*)+\n+', '\n\n', clean_text)
                            clean_text = re.sub(r'(?<=[A-Z])(ART[ÍI]CULO|ART\.)', r'\n\1', clean_text)
                            materia = clean_text[:447] + '...' if len(clean_text) > 450 else clean_text
                        
                        materia = re.sub(r'\b[A-Z]{2,}\d{5,}\b|\b[A-Za-z]{1,}\s?\d{5,}\b|\b[A-Za-z0-9\-]{2,}\s?-?\d{4,}\s?\d{10,}\b', '', materia, flags=re.IGNORECASE).strip()
                        
                        if len(materia) > 500:
                            materia = materia[:497] + '...'
                        
                        fecha = extract_date(full_text, filename)

                    metadata_dict[pdf_path] = {
                        'file_name': filename,
                        'page_count': len(reader.pages),
                        'materia': materia,
                        'fecha': fecha,
                        'title': raw_metadata.get('/Title', 'No disponible'),
                        'author': raw_metadata.get('/Author', 'No disponible'),
                        'subject': raw_metadata.get('/Subject', 'No disponible'),
                        'keywords': raw_metadata.get('/Keywords', 'No disponible'),
                        'modification_date': datetime.datetime.fromtimestamp(os.path.getmtime(pdf_path)).strftime('%d/%m/%Y %H:%M:%S')
                    }
                    
            except Exception as e:
                logging.error(f"Error procesando {pdf_path}: {str(e)}")
                metadata_dict[pdf_path] = {
                    'error': str(e),
                    'file_name': os.path.basename(pdf_path)
                }
        
        return metadata_dict
    
    @staticmethod
    def save_metadata_to_json(metadata: Dict, json_path: str) -> None:
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)
    
    @staticmethod
    def get_top_files(files: List[str], pattern: str) -> List[str]:
        files_with_numbers = []
        for file_path in files:
            filename = os.path.basename(file_path)
            try:
                num_match = re.search(pattern, filename)
                if num_match:
                    num = int(num_match.group(1))
                    files_with_numbers.append((num, file_path))
            except:
                continue
        
        files_with_numbers.sort(reverse=True, key=lambda x: x[0])
        top_files = [f[1] for f in files_with_numbers[:42]]
        
        return top_files

    @staticmethod
    def clean_text(text: str) -> str:
        # Reemplazar caracteres especiales
        replacements = {
            '–': '-',
            '°': '°',
            'º': '°',
            'ª': 'a',
            'á': 'a',
            'é': 'e',
            'í': 'i',
            'ó': 'o',
            'ú': 'u',
            'ñ': 'n',
            'Á': 'A',
            'É': 'E',
            'Í': 'I',
            'Ó': 'O',
            'Ú': 'U',
            'Ñ': 'N'
        }
        
        # Aplicar reemplazos
        for old, new in replacements.items():
            text = text.replace(old, new)
        
        # Limpiar espacios múltiples
        text = re.sub(r'\s+', ' ', text)
        
        # Limpiar espacios alrededor de guiones y paréntesis
        text = re.sub(r'\s*-\s*', '-', text)
        text = re.sub(r'\(\s*', '(', text)
        text = re.sub(r'\s*\)', ')', text)
        
        # Limpiar espacios antes de signos de puntuación
        text = re.sub(r'\s+([.,;:])', r'\1', text)
        
        # Limpiar espacios después de signos de puntuación
        text = re.sub(r'([.,;:])\s+', r'\1 ', text)
        
        return text.strip()

class SIIDownloader:
    
    @staticmethod
    def download_with_requests() -> List[str]:
        base_url_resoluciones = 'https://www.sii.cl/normativa_legislacion/resoluciones/'
        base_url_circulares = 'https://www.sii.cl/normativa_legislacion/circulares/'

        def scrape_pdf_links(base_url: str, year: str, prefix: str, max_missing: int = 10) -> List[str]:
            pdf_links = []
            i = 1
            missing_count = 0
            while True:
                pdf_link = f"{base_url}{year}/{prefix}{i}.pdf"
                response = requests.head(pdf_link)
                if response.status_code == 200:
                    pdf_links.append((pdf_link, f"{prefix}{i}.pdf"))
                    missing_count = 0  # Reinicia el contador si encuentra uno válido
                else:
                    missing_count += 1
                    if missing_count >= max_missing:
                        break
                i += 1
            return pdf_links

        def download_file(url: str, filename: str, folder: str) -> str:
            local_filename = os.path.join(folder, filename)
            with requests.get(url, stream=True) as r:
                r.raise_for_status()
                with open(local_filename, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)
            return local_filename

        # Buscar sin límite fijo, solo se detiene tras 10 archivos inexistentes seguidos
        resoluciones_pdf_links = scrape_pdf_links(base_url_resoluciones, YEAR, 'reso', 10)
        circulares_pdf_links = scrape_pdf_links(base_url_circulares, YEAR, 'circu', 10)
        all_pdf_links = resoluciones_pdf_links + circulares_pdf_links

        downloaded_files = set(os.listdir(DOWNLOAD_DIR_SII))
        new_files = []

        for pdf_link, filename in all_pdf_links:
            if filename not in downloaded_files:
                try:
                    pdf_file_path = download_file(pdf_link, filename, DOWNLOAD_DIR_SII)
                    new_files.append(pdf_file_path)
                except Exception as e:
                    logging.error(f"Error descargando {filename}: {e}")
        
        return new_files

    @staticmethod
    def configure_browser() -> Options:
        chrome_options = Options()
        options = Options()


        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--remote-debugging-port=9222")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("--start-maximized")
        chrome_options.add_argument("--disable-notifications")
        chrome_options.page_load_strategy = 'eager'
        chrome_options.add_argument("--disable-extensions")
        chrome_options.add_argument("--blink-settings=imagesEnabled=false")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)


        prefs = {
            "download.default_directory": os.path.abspath(DOWNLOAD_DIR_SII),
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "plugins.always_open_pdf_externally": True,
            "profile.default_content_settings.popups": 0
        }
        chrome_options.add_experimental_option("prefs", prefs)
        
        chrome_options.add_argument("--remote-debugging-address=0.0.0.0")
        chrome_options.add_argument("--remote-debugging-port=9222")
        
        return chrome_options

    @staticmethod
    def navigate_to_page(driver: webdriver.Chrome, url: str) -> bool:
        driver.get(url)
        
        try:
            WebDriverWait(driver, 3).until(
                EC.presence_of_element_located((By.TAG_NAME, "table"))
            )
            return True
        except Exception as e:
            logging.error(f"Page load error: {str(e)}")
            return False

    @staticmethod
    def extract_filename(description: str, prefix: str = None) -> Optional[str]:
        regex_ordinario = re.compile(r"Oficio Ordinario (\d+), de (\d{2})/(\d{2})/(\d{4})")
        regex_general = re.compile(r"Oficio (Ordinario|Reservado) (\d+), de (\d{2})/(\d{2})/(\d{4})", re.IGNORECASE)

        match = regex_ordinario.search(description) if prefix else regex_general.search(description)
        if not match:
            return None

        if prefix:
            numero, dia, mes, anio = match.groups()
            return f"{prefix}_{numero}-{dia}_{mes}_{anio}.pdf"
        else:
            tipo, numero, dia, mes, anio = match.groups()
            return f"OTRAS_NORMAS_{tipo.upper()}_{numero}-{dia}_{mes}_{anio}.pdf"

    @staticmethod
    def is_file_downloaded(filename: str) -> bool:
        return os.path.exists(os.path.join(DOWNLOAD_DIR_SII, filename)) if filename else False

    @staticmethod
    def wait_for_download(before_files: set, timeout: float = 0.5) -> Optional[str]:
        download_path = os.path.abspath(DOWNLOAD_DIR_SII)
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            after_files = set(f for f in os.listdir(download_path) if f.endswith('.pdf'))
            new_files = after_files - before_files
            if new_files:
                new_file = list(new_files)[0]
                if not new_file.endswith(".crdownload"):
                    return new_file
        return None

    @staticmethod
    def download_link(driver: webdriver.Chrome, link, prefix: str = None) -> Optional[str]:
        description = link.text.strip()
        filename = SIIDownloader.extract_filename(description, prefix)
        
        if not filename or SIIDownloader.is_file_downloaded(filename):
            return None

        before_files = set(f for f in os.listdir(DOWNLOAD_DIR_SII) if f.endswith('.pdf'))

        link.click() 
        
        downloaded_file = SIIDownloader.wait_for_download(before_files)
        if downloaded_file:
            # Asegurarse de que el archivo tenga el prefijo correcto
            if not any(downloaded_file.startswith(p) for p in ALLOWED_PREFIXES):
                os.rename(
                    os.path.join(DOWNLOAD_DIR_SII, downloaded_file),
                    os.path.join(DOWNLOAD_DIR_SII, filename)
                )
                return filename
            else:
                # Si ya tiene un prefijo válido, solo moverlo si es necesario
                if downloaded_file != filename:
                    os.rename(
                        os.path.join(DOWNLOAD_DIR_SII, downloaded_file),
                        os.path.join(DOWNLOAD_DIR_SII, filename)
                    )
                return filename
        return None

    @staticmethod
    def find_and_download(driver: webdriver.Chrome, xpath: str, prefix: str = None) -> List[str]:
        links = WebDriverWait(driver, 0.15).until(
            EC.presence_of_all_elements_located((By.XPATH, xpath))
        )
        
        return [result for link in links 
                if (result := SIIDownloader.download_link(driver, link, prefix))]

    @staticmethod
    def download_ventas_renta(driver: webdriver.Chrome) -> List[str]:
        configs = [
            ("https://www.sii.cl/normativa_legislacion/jurisprudencia_administrativa/ley_impuesto_ventas/2025/ley_impuesto_ventas_jadm2025.htm",
             "//a[starts-with(text(),'Ventas y Servicios')]", "VENTAS"),
            ("https://www.sii.cl/normativa_legislacion/jurisprudencia_administrativa/ley_impuesto_renta/2025/ley_impuesto_renta_jadm2025.htm",
             "//a[starts-with(text(),'Renta')]", "RENTA")
        ]

        downloaded_files = []
        for url, xpath, prefix in configs:
            if SIIDownloader.navigate_to_page(driver, url):
                downloaded_files.extend(SIIDownloader.find_and_download(driver, xpath, prefix))
        
        return downloaded_files

    @staticmethod
    def download_other_rules(driver: webdriver.Chrome) -> List[str]:
        url = "https://www.sii.cl/normativa_legislacion/jurisprudencia_administrativa/otras_normas/2025/otras_normas_jadm2025.htm"
        if not SIIDownloader.navigate_to_page(driver, url):
            return []

        WebDriverWait(driver, 1).until(
            EC.presence_of_element_located((By.XPATH, "//a[contains(@href, '.pdf')]"))
        )

        return SIIDownloader.find_and_download(driver, "//a[contains(@href, '.pdf')]")

    @staticmethod
    def download_with_selenium() -> List[str]:
        driver = None
        try:
            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=SIIDownloader.configure_browser())
            
            ventas_renta_files = SIIDownloader.download_ventas_renta(driver)
            other_rules_files = SIIDownloader.download_other_rules(driver)

            return ventas_renta_files + other_rules_files

        except Exception as e:
            logging.error(f"Execution error: {str(e)}")
            return []
        finally:
            if driver:
                driver.quit()

class BCNScraper:
    BASE_URL = "https://www.bcn.cl/leychile/consulta/portada_ulp"
    NORMA_URL = "https://www.bcn.cl/leychile/navegar?idNorma={}"

    def __init__(self, driver: webdriver.Chrome):
        self.driver = driver
        self.wait = WebDriverWait(driver, 0.15)

    def get_recent_laws(self) -> List[Dict[str, str]]:
        logging.info("Getting recent laws...")
        try:
            self.driver.get(self.BASE_URL)
            self.wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "a[href*='idNorma']")))
            elements = self.driver.find_elements(By.CSS_SELECTOR, "a[href*='idNorma']")
            return [{'url': e.get_attribute('href'), 'norma_id': self.extract_norma_id(e.get_attribute('href'))} for e in elements]
        except Exception as e:
            logging.error(f"Error: {str(e)}")
            return [{'url': 'https://www.bcn.cl/leychile/navegar?idNorma=1212060', 'norma_id': '1212060'}]

    def extract_norma_id(self, url: str) -> str:
        return url.split('idNorma=')[1] if 'idNorma=' in url else '0'

    def download_with_selenium(self, law_info: Dict[str, str]) -> bool:
        try:
            main_window = self.driver.current_window_handle
            self.driver.execute_script("window.open('');")
            new_window = [w for w in self.driver.window_handles if w != main_window][0]
            self.driver.switch_to.window(new_window)
            self.driver.get(law_info['url'])

            btn_descarga = self.wait.until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "button[title='Descargar']"))
            )
            self.driver.execute_script("arguments[0].click();", btn_descarga)

            download_link = WebDriverWait(self.driver, 2).until(
                EC.presence_of_element_located((By.XPATH, "//a[contains(., 'Descargar ahora sin firma')]"))
            )
            download_url = download_link.get_attribute('href')

            output_filename = f"BCN_Ley-ID-{law_info['norma_id']}.pdf"
            output_path = os.path.join(DOWNLOAD_DIR_BCN, output_filename)
            
            if os.path.exists(output_path):
                success = True
            else:
                success = self.download_pdf(download_url, output_path)
                logging.info(f"{'Descargado' if success else 'Error'}: {output_filename}")

            self.driver.close()
            self.driver.switch_to.window(main_window)
            return success

        except Exception as e:
            logging.error(f"Error de descarga ID {law_info['norma_id']}: {e}")
            if len(self.driver.window_handles) > 1:
                self.driver.close()
                self.driver.switch_to.window(main_window)
            return False

    def download_pdf(self, url: str, output_path: str) -> bool:
        try:
            r = requests.get(url, timeout=15)
            if r.status_code == 200:
                with open(output_path, 'wb') as f:
                    f.write(r.content)
                return True
            else:
                logging.error(f"Respuesta inválida: {r.status_code}")
                return False
        except Exception as e:
            logging.error(f"Error descargando PDF {url}: {e}")
            return False

class BCNBrowser:
    
    @staticmethod
    def configure() -> webdriver.Chrome:
        options = Options()
        
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--remote-debugging-port=9222")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-notifications")

        prefs = {
            "profile.managed_default_content_settings.images": 2,
            "profile.managed_default_content_settings.stylesheets": 2,
        }
        options.add_experimental_option("prefs", prefs)
        
        options.add_argument("--remote-debugging-address=0.0.0.0")
        options.add_argument("--remote-debugging-port=9222")
        
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
        return driver

class BCNManager:
    
    @staticmethod
    def load_downloaded_ids(path: str = "downloaded_pdfs/descargadas.json") -> Set[str]:
        if not os.path.exists(path):
            return set()
        with open(path, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
                return {entry["id"] for entry in data.get("descargadas", [])}
            except json.JSONDecodeError:
                return set()

    @staticmethod
    def save_downloaded_ids(ids: Set[str], path: str = "downloaded_pdfs/descargadas.json") -> None:
        data = {"descargadas": [{"id": id_} for id_ in ids]}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    @staticmethod
    def clean_missing_files(downloaded_ids: Set[str]) -> Set[str]:
        existing_files = {f.replace("BCN_Ley-ID-", "").replace(".pdf", "") for f in os.listdir(DOWNLOAD_DIR_BCN) if f.endswith(".pdf")}
        cleaned_ids = downloaded_ids.intersection(existing_files)
        logging.info(f"Missing files: {len(downloaded_ids) - len(cleaned_ids)}")
        BCNManager.save_downloaded_ids(cleaned_ids)
        return cleaned_ids

    @staticmethod
    def download() -> List[str]:
        start_time = time.time()

        driver = BCNBrowser.configure()
        scraper = BCNScraper(driver)

        try:
            downloaded_ids = BCNManager.load_downloaded_ids()
            downloaded_ids = BCNManager.clean_missing_files(downloaded_ids)

            laws = scraper.get_recent_laws()
            new_laws = [law for law in laws if law['norma_id'] not in downloaded_ids][:42]  

            success = 0
            for law in new_laws:
                if scraper.download_with_selenium(law):
                    downloaded_ids.add(law['norma_id'])
                    success += 1

            BCNManager.save_downloaded_ids(downloaded_ids)

            total_time = time.time() - start_time
            logging.info(f"\nTotal time: {total_time:.2f} seconds")
            logging.info(f"Successful downloads: {success}/{len(new_laws)}")
            logging.info(f"Saved in: {os.path.abspath(DOWNLOAD_DIR_BCN)}")

            return [os.path.join(DOWNLOAD_DIR_BCN, f"BCN_Ley-ID-{law['norma_id']}.pdf") for law in new_laws if os.path.exists(os.path.join(DOWNLOAD_DIR_BCN, f"BCN_Ley-ID-{law['norma_id']}.pdf"))]

        finally:
            driver.quit()

def main():
    today = datetime.datetime.now()
    is_weekend = today.weekday() >= 5
    
    if is_weekend:
        logging.info("\nHoy es fin de semana. No se realizaron descargas")
        return

    logging.info("\nIniciando proceso de descarga de documentos SII y BCN...")
    start_time = time.time()

    # Sistema de reintentos para SII
    max_retries = 3
    retry_delay = 20  # 20 segundos entre intentos
    all_sii_files = set()
    
    for attempt in range(max_retries):
        logging.info(f"\nIntento {attempt + 1} de {max_retries}")
        
        sii_requests_files = SIIDownloader.download_with_requests()
        sii_selenium_files = SIIDownloader.download_with_selenium()
        current_sii_files = set(sii_requests_files + [os.path.join(DOWNLOAD_DIR_SII, f) for f in sii_selenium_files])
        
        if current_sii_files:
            all_sii_files.update(current_sii_files)
            logging.info(f"Archivos encontrados en este intento: {len(current_sii_files)}")
            
            if attempt < max_retries - 1:
                logging.info(f"Esperando {retry_delay} segundos antes del siguiente intento...")
                time.sleep(retry_delay)
        else:
            logging.info("No se encontraron nuevos archivos en este intento")
            break

    sii_files = list(all_sii_files)
    bcn_files = BCNManager.download()

    logging.info("Resumen de descargas:")
    logging.info(f"- SII (Resoluciones y circulares): {len(sii_files)} archivos totales")
    logging.info(f"- BCN (Leyes recientes): {len(bcn_files)} archivos nuevos")
    
    if sii_files or bcn_files:
        patterns = {
            'circu': r'circu(\d+)\.pdf',
            'reso': r'reso(\d+)\.pdf',
            'VENTAS': r'VENTAS_(\d+)-\d{2}_\d{2}_2025\.pdf',
            'RENTA': r'RENTA_(\d+)-\d{2}_\d{2}_2025\.pdf',
            'OTRAS_NORMAS': r'OTRAS_NORMAS_\w+_(\d+)-\d{2}_\d{2}_2025\.pdf',
            'BCN_Ley': r'BCN_Ley-ID-(\d+)\.pdf'
        }
        
        files_to_send = []
        
        sii_types = {
            'circu': [f for f in sii_files if re.search(patterns['circu'], os.path.basename(f))],
            'reso': [f for f in sii_files if re.search(patterns['reso'], os.path.basename(f))],
            'VENTAS': [f for f in sii_files if re.search(patterns['VENTAS'], os.path.basename(f))],
            'RENTA': [f for f in sii_files if re.search(patterns['RENTA'], os.path.basename(f))],
            'OTRAS_NORMAS': [f for f in sii_files if re.search(patterns['OTRAS_NORMAS'], os.path.basename(f))]
        }
        
        for file_type, files in sii_types.items():
            if files:
                top_files = FileUtils.get_top_files(files, patterns[file_type])
                files_to_send.extend(top_files)
        
        if bcn_files:
            top_bcn_files = FileUtils.get_top_files(bcn_files, patterns['BCN_Ley'])
            files_to_send.extend(top_bcn_files)
        
        logging.info("\nArchivos seleccionados para enviar (2 más recientes de cada tipo):")
        for file in files_to_send:
            logging.info(f"- {os.path.basename(file)}")
        
        if files_to_send:
            metadata = FileUtils.get_pdf_metadata(files_to_send)

            html_content = """\
<html>
  <head>
    <style>
      body {
        font-family: Arial, sans-serif;
        line-height: 1.6;
      }
      ul {
        list-style-type: none;
        padding: 0;
      }
      li {
        margin-bottom: 15px;
      }
      .document-info {
        margin-left: 20px;
      }
    </style>
  </head>
  <body>
    <p>Estimado,</p>
    <p>Junto con saludarle y esperando que se encuentre muy bien, adjunto PDFs actualizados.</p>
    <p>Detalle de documentos:</p>
    <ul>
"""

            def format_filename(filename: str) -> str:
                filename_lower = filename.lower()
                if filename_lower.startswith('reso'):
                    match = re.search(r'reso(\d+)', filename_lower)
                    if match:
                        num = match.group(1)
                        return f"Resolución SII N°{num}"
                    return "Resolución SII"
                elif filename_lower.startswith('circu'):
                    match = re.search(r'circu(\d+)', filename_lower)
                    if match:
                        num = match.group(1)
                        return f"Circular SII N°{num}"
                    return "Circular SII"
                elif filename_lower.startswith('bcn'):
                    return "Biblioteca del Congreso Nacional (bcn.cl)"
                elif filename_lower.startswith('ventas'):
                    return "Jurisprudencia Ventas y Servicios SII"
                elif filename_lower.startswith('renta'):
                    return "Jurisprudencia Renta SII"
                else:
                    return "Otras Normas SII"

            for file_path, meta in metadata.items():
                materia_limpia = meta.get('materia', 'No disponible')
                if materia_limpia and isinstance(materia_limpia, str):
                    materia_limpia = FileUtils.clean_text(materia_limpia)
                    materia_limpia = materia_limpia.lower().capitalize()
                    materia_limpia = f"<strong>{materia_limpia}</strong>"
                else:
                    materia_limpia = "<strong>No disponible</strong>"

                file_name = format_filename(meta['file_name'])
                fecha = meta.get('fecha', 'No disponible').lower()
                modification_date = meta.get('modification_date', 'No disponible')
                
                file_info = f"<li>{file_name} de {fecha}, {materia_limpia}"
                if 'file_size' in meta:
                    file_size = meta['file_size'].lower()
                    file_info += f", con tamaño {file_size} y {meta['page_count']} páginas."
                file_info += f"<br>Última modificación registrada: {modification_date}</li>"
                
                html_content += file_info

            html_content += """\
    </ul>
    <p>Saludos cordiales,</p>
  </body>
</html>
"""

            subject = "Nuevos documentos disponibles en SII.cl y BCN.cl"
            
            msg = MIMEMultipart('alternative')
            msg['From'] = EMAIL_SENDER
            msg['To'] = EMAIL_RECIPIENTS
            msg['Subject'] = subject
            
            part = MIMEText(html_content, 'html')
            msg.attach(part)

            for file_path in files_to_send:
                try:
                    with open(file_path, "rb") as attachment:
                        part = MIMEApplication(attachment.read(), _subtype="pdf")
                        part.add_header(
                            "Content-Disposition",
                            f"attachment; filename= {os.path.basename(file_path)}",
                        )
                        msg.attach(part)
                except Exception as e:
                    logging.error(f"No se pudo adjuntar {file_path}: {str(e)}")
                    continue
            try:
                with smtplib.SMTP('smtp.gmail.com', 587) as server:
                    server.starttls()
                    server.login(EMAIL_SENDER, EMAIL_PASSWORD)
                    server.send_message(msg)
                    logging.info("Correo enviado exitosamente con formato HTML")
            except Exception as e:
                logging.error(f"Error al enviar el correo: {str(e)}")

        else:
            logging.info("\nNo valid files selected to send.")
            subject = "Document selection error"
            body = "Test code - Files were downloaded but the most recent ones could not be selected to send."
            EmailSender.send_email(subject, body)

    else:
        logging.info("\nNo new files downloaded.")
        subject = "No hay nuevos documentos disponibles en SII.cl y BCN.cl"
        body = "Estimado, se le notifica que no existen actualizaciones en la página del SII.cl ni BCN.cl."
        EmailSender.send_email(subject, body)

    logging.info(f"\nTotal execution time: {time.time() - start_time:.2f} seconds")


if __name__ == "__main__":
    main()


