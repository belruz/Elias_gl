import time
import random
import os
import re
import smtplib
import logging
import datetime
import json
import uuid
import base64
from playwright.sync_api import sync_playwright
from dotenv import load_dotenv
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from email.mime.image import MIMEImage
from pathlib import Path
from pdf2image import convert_from_path
import PyPDF2
from PIL import Image
import openai

#  Configuración inicial
dotenv_path = Path(__file__).parent / '.env'
load_dotenv(dotenv_path=dotenv_path, override=True)

# Configuración de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('email_sender.log'),
        logging.StreamHandler()
    ]
)

# Variables globales
EMAIL_SENDER = os.getenv("EMAIL_SENDER_TEST")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD_TEST")
EMAIL_RECIPIENTS = os.getenv("EMAIL_RECIPIENTS_TEST", "").split(",")
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
BASE_URL_PJUD = "https://oficinajudicialvirtual.pjud.cl/home/"
USERNAME = os.getenv("RUT")
PASSWORD = os.getenv("CLAVE")

# Lista global para almacenar todos los movimientos nuevos
MOVIMIENTOS_GLOBALES = []

# Lista actualizada de pestañas
MIS_CAUSAS_TABS = [
    "Corte Suprema", 
    "Corte Apelaciones", 
    "Civil",
    "Laboral", 
    "Penal", 
    "Cobranza",
    "Familia",
    "Disciplinario"
]

# Clase MovimientoPJUD 
class MovimientoPJUD:
    def __init__(self, folio, seccion, caratulado, fecha, tribunal=None, corte=None, libro=None, rit=None, rol=None, pdf_path=None, cuaderno=None, archivos_apelaciones=None, historia_causa_cuaderno=None):
        self.folio = folio
        self.seccion = seccion
        self.caratulado = caratulado
        self.tribunal = tribunal
        self.corte = corte
        self.fecha = fecha
        self.libro = libro
        self.rit = rit
        self.rol = rol
        self.pdf_path = pdf_path 
        self.cuaderno = cuaderno
        self.archivos_apelaciones = archivos_apelaciones or []
        self.historia_causa_cuaderno = historia_causa_cuaderno 
    
    def tiene_pdf(self):
        return self.pdf_path is not None and os.path.exists(self.pdf_path)
    
    def tiene_archivos_apelaciones(self):
        return len(self.archivos_apelaciones) > 0
    
    def to_dict(self):
        return {
            'folio': self.folio,
            'seccion': self.seccion,
            'caratulado': self.caratulado,
            'fecha': self.fecha,
            'libro': self.libro,
            'rit': self.rit,
            'rol': self.rol,
            'tribunal': self.tribunal,
            'corte': self.corte,
            'pdf_path': self.pdf_path,
            'cuaderno': self.cuaderno,
            'archivos_apelaciones': self.archivos_apelaciones,
            'historia_causa_cuaderno': self.historia_causa_cuaderno
        }
    
    def __eq__(self, other):
        if not isinstance(other, MovimientoPJUD):
            return False
        return (self.folio == other.folio and 
                self.seccion == other.seccion and 
                self.caratulado == other.caratulado and 
                self.fecha == other.fecha and
                self.libro == other.libro and
                self.rit == other.rit and
                self.rol == other.rol and
                self.cuaderno == other.cuaderno and
                self.tribunal == other.tribunal and
                self.corte == other.corte and
                os.path.basename(self.pdf_path or "") == os.path.basename(other.pdf_path or "")
                )

    @property
    def identificador_causa(self):
        return self.rol or self.rit or self.libro

#Funciones utilitarias 
def obtener_fecha_actual_str():
    return datetime.datetime.now().strftime("%d/%m/%Y")

def random_sleep(min_seconds=1, max_seconds=3):
    time.sleep(random.uniform(min_seconds, max_seconds))

def limpiar_nombre_archivo(nombre):
    return re.sub(r'[<>:"/\\|?*\n\r\t]', '', nombre)

def limpiar_identificador(texto):
    if not texto:
        return ""
    return re.sub(r'^(Libro\s*:|RIT\s*:|ROL\s*:)\s*', '', texto, flags=re.IGNORECASE).strip()

def agregar_movimiento_sin_duplicar(movimiento):
    if not any(m == movimiento for m in MOVIMIENTOS_GLOBALES):
        MOVIMIENTOS_GLOBALES.append(movimiento)
        return True
    return False

#Configuración de navegador
def setup_browser():
    playwright = sync_playwright().start()
    selected_user_agent = random.choice([
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.6367.78 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.6367.78 Safari/537.36",
        "Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
        "Mozilla/5.0 (Linux; Android 12; SM-G991B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.6367.78 Mobile Safari/537.36"
    ])
    
    browser = playwright.chromium.launch(
        headless=False,
        args=[
            '--disable-blink-features=AutomationControlled',
            '--disable-dev-shm-usage',
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--disable-gpu',
            '--disable-infobars',
            '--window-size=1366,768',
            '--start-maximized',
            '--disable-web-security',
            '--allow-running-insecure-content',
            '--disable-extensions',
            '--disable-notifications',
            '--disable-popup-blocking',
            '--lang=es-ES',
            '--timezone=America/Santiago'
        ]
    )
    
    context = browser.new_context(
        viewport={'width': 1366, 'height': 768},
        user_agent=selected_user_agent,
        locale='es-ES',
        timezone_id='America/Santiago',
        geolocation={'latitude': -33.4489, 'longitude': -70.6693},
        permissions=['geolocation'],
        extra_http_headers={
            'Accept-Language': 'es-ES,es;q=0.9',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1'
        }
    )
    
    context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined
        });
        Object.defineProperty(navigator, 'plugins', {
            get: () => [1, 2, 3, 4, 5]
        });
        Object.defineProperty(navigator, 'languages', {
            get: () => ['es-ES', 'es']
        });
    """)
    
    page = context.new_page()
    page.set_default_timeout(30000)
    page.set_default_navigation_timeout(30000)
    
    return playwright, browser, page

# Simulación de comportamiento humano 
def simulate_human_behavior(page):
    if random.random() < 0.3:
        page.mouse.wheel(0, random.randint(100, 500))
        random_sleep(0.5, 1.5)
    if random.random() < 0.2:
        x = random.randint(100, 800)
        y = random.randint(100, 600)
        page.mouse.move(x, y)
        random_sleep(0.5, 1.5)

# Funciones de navegación
def login(page, username, password):
    try:
        print("Esperando página de Clave Única...")
        random_sleep(2, 4)
        simulate_human_behavior(page)

        print("Ingresando usuario...")
        page.fill('#uname', username)
        random_sleep(1, 2)
        
        print("Ingresando contraseña...")
        page.fill('#pword', password)
        random_sleep(1, 2)
        
        page.keyboard.press('Enter')
        page.keyboard.press('Enter')
        random_sleep(2, 4)
        
        page.wait_for_selector('text=Oficina Judicial Virtual', timeout=30000)
        print("Inicio de sesión exitoso!")
        return True
        
    except Exception as e:
        print(f"Error durante el proceso de login: {str(e)}") 
        return False

def navigate_to_mis_causas(page):
    try:
        print("Navegando a 'Mis Causas'...")
        page.evaluate("misCausas();")
        print("Navegación a 'Mis Causas' mediante JS exitosa!")
        random_sleep(1, 4)
        return True
    except Exception as e:
        print(f"Error al navegar a 'Mis Causas': {str(e)}")
        return False

# Funciones de procesamiento de PDFs
def descargar_pdf_directo(pdf_url, pdf_filename, page):
    try:
        if os.path.exists(pdf_filename):
            print(f"[INFO] El archivo {pdf_filename} ya existe.")
            return True

        cookies_list = page.context.cookies()
        cookie_header = '; '.join([f"{c['name']}={c['value']}" for c in cookies_list])
        headers = {
            'Accept': 'application/pdf,application/x-pdf,application/octet-stream',
            'Accept-Language': 'es-ES,es;q=0.9',
            'Connection': 'keep-alive',
            'User-Agent': page.evaluate('navigator.userAgent'),
            'Cookie': cookie_header
        }
        response = page.context.request.get(pdf_url, headers=headers)
        
        if response.status == 200:
            with open(pdf_filename, 'wb') as f:
                f.write(response.body())
            print(f"[INFO] PDF descargado exitosamente: {pdf_filename}")
            return True
        else:
            print(f"[ERROR] Error al descargar PDF: Status code {response.status}")
            return False
    except Exception as e:
        print(f"[ERROR] Error general al descargar el PDF: {str(e)}")
        return False

def extraer_resumen_pdf(pdf_path):
    try:
        with open(pdf_path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            if len(reader.pages) > 0:
                text = reader.pages[0].extract_text()
                if text:
                    lineas = text.strip().splitlines()
                    lineas_utiles = []
                    for linea in lineas:
                        if ("firma electrónica" in linea.lower() or
                            "verificadoc.pjud.cl" in linea.lower() or
                            "horaoficial.cl" in linea.lower() or
                            "puede ser validado" in linea.lower() or
                            "establecido en chile" in linea.lower() or
                            "para más información" in linea.lower()):
                            continue
                        if linea.strip():
                            lineas_utiles.append(linea.strip())
                    resumen = " ".join(" ".join(lineas_utiles).split()[:15])
                    return resumen if resumen else "sin_resumen"
        return "sin_resumen"
    except Exception as e:
        print(f"[ERROR] No se pudo extraer resumen del PDF: {e}")
        return "sin_resumen"

def generar_preview_pdf(pdf_path, preview_path, width=400):
    try:
        images = convert_from_path(pdf_path, first_page=1, last_page=1)
        if images:
            img = images[0]
            w, h = img.size
            crop_height = int(h * 0.5 * 0.7)
            upper_part = img.crop((0, 0, w, crop_height))
            aspect_ratio = crop_height / w
            new_height = int(width * aspect_ratio)
            resized = upper_part.resize((width, new_height), Image.LANCZOS)
            resized.save(preview_path, 'PNG')
            print(f"[INFO] Vista previa guardada en: {preview_path}")
        else:
            print(f"[WARN] No se pudo generar la vista previa para {pdf_path}")
    except Exception as e:
        print(f"[ERROR] Error generando preview: {e}")

# Funciones de OpenAI
def procesar_html_con_openai(html, tab_name):
    """Envía HTML a OpenAI para extracción estructurada de datos"""
    try:
        client = openai.OpenAI(api_key=OPENAI_API_KEY)
        fecha_actual = obtener_fecha_actual_str()
        
        prompt = f"""
        Eres un asistente experto en extraer datos judiciales de PJUD.cl. Analiza este HTML de la pestaña '{tab_name}' 
        y extrae todas las causas con movimientos nuevos (fecha: {fecha_actual}).
        
        Para cada causa, extrae:
        1. Texto completo del caratulado
        2. Identificador único (RIT, ROL o Libro)
        3. Fecha del movimiento (debe ser {fecha_actual})
        4. Selector CSS exacto del botón/lupa para ver detalles
        5. Texto de la corte o tribunal (si está disponible)
        
        Devuelve SOLO JSON válido con este formato:
        {{
            "causas": [
                {{
                    "caratulado": "Texto completo del caratulado",
                    "identificador": "RIT-12345 o similar",
                    "fecha_movimiento": "{fecha_actual}",
                    "selector_lupa": "a[href='#detalle_123']",
                    "corte_tribunal": "Corte de Apelaciones de Santiago"
                }},
                ... más causas
            ]
        }}
        """
        
        response = client.chat.completions.create(
            model="gpt-4o",
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": "Eres un experto en extracción de datos judiciales. Devuelve solo JSON válido."
                },
                {
                    "role": "user",
                    "content": prompt + "\n\nHTML:\n" + html[:30000]
                }
            ],
            max_tokens=2000
        )
        
        json_str = response.choices[0].message.content
        return json.loads(json_str)
        
    except Exception as e:
        logging.error(f"Error procesando HTML con OpenAI: {str(e)}")
        return {"causas": []}

def procesar_modal_generico_con_openai(html, caratulado, cuaderno, tab_name):
    """Procesa cualquier modal con OpenAI"""
    try:
        client = openai.OpenAI(api_key=OPENAI_API_KEY)
        fecha_actual = obtener_fecha_actual_str()
        
        prompt = f"""
        Eres un experto en extraer datos judiciales. Analiza este HTML del modal de {tab_name} (Cuaderno: {cuaderno})
        y extrae los movimientos con fecha {fecha_actual}.
        
        Para cada movimiento, extrae:
        1. Folio
        2. Fecha del trámite
        3. Texto del trámite
        4. Token del formulario PDF (buscar inputs ocultos con valores)
        
        Devuelve SOLO JSON válido con este formato:
        {{
            "movimientos": [
                {{
                    "folio": "12345",
                    "fecha": "{fecha_actual}",
                    "tramite": "Presentación de demanda",
                    "token_pdf": "ABC123XYZ456"
                }}
            ]
        }}
        """
        
        response = client.chat.completions.create(
            model="gpt-4o",
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": "Extrae solo movimientos con la fecha especificada."
                },
                {
                    "role": "user",
                    "content": prompt + "\n\nHTML:\n" + html[:30000]
                }
            ],
            max_tokens=2000
        )
        
        json_str = response.choices[0].message.content
        return json.loads(json_str)
        
    except Exception as e:
        logging.error(f"Error procesando modal {tab_name} con OpenAI: {str(e)}")
        return {"movimientos": []}

# Manejo de paginación 
def manejar_paginacion(page, tab_name):
    """Maneja la paginación en la tabla de causas"""
    try:
        print(f"  Iniciando paginación para {tab_name}...")
        
        # Detectar selector de total de registros según pestaña
        total_selectors = {
            "Corte Apelaciones": '.loadTotalApe b',
            "Corte Suprema": '.loadTotalSup b',
            "Civil": '.loadTotalCiv b',
            "Laboral": '.loadTotalLab b',
            "Penal": '.loadTotalPen b',
            "Cobranza": '.loadTotalCob b',
            "Familia": '.loadTotalFam b',
            "Disciplinario": '.loadTotalDis b'
        }
        
        total_selector = total_selectors.get(tab_name, '.loadTotalApe b')
        
        # Obtener el número total de registros
        total_registros = page.evaluate(f'''() => {{
            const el = document.querySelector('{total_selector}');
            return el ? parseInt(el.textContent.replace(/\\D/g, '')) : 0;
        }}''')
        
        if not total_registros or total_registros <= 15:
            print("  Menos de 15 registros, no se requiere paginación")
            yield 1
            return
            
        # Calcular número de páginas (15 registros por página)
        total_paginas = (total_registros + 14) // 15
        print(f"  Total de registros: {total_registros} | Páginas: {total_paginas}")
        
        # Procesar cada página
        for pagina in range(1, total_paginas + 1):
            print(f"  Procesando página {pagina}/{total_paginas}")
            
            # Si no es la primera página, cambiar de página
            if pagina > 1:
                # Intentar hacer clic en el número de página específico
                pagina_selector = f'.pagination .page-item:not(.active):has-text("{pagina}")'
                if page.is_visible(pagina_selector):
                    page.click(pagina_selector)
                else:
                    # Usar navegación programática
                    page.evaluate(f'''() => {{
                        if (typeof pagina === 'function') {{
                            pagina({pagina}, 2);
                        }}
                    }}''')
                
                # Esperar a que cargue la nueva página
                random_sleep(2, 3)
                page.wait_for_load_state("networkidle")
            
            yield pagina
            
        print("  Paginación completada")
        
    except Exception as e:
        print(f"  Error en paginación: {str(e)}")
        yield 1

#  Funciones de procesamiento principal 
def procesar_pestana_con_openai(page, tab_name):
    """Procesa una pestaña usando OpenAI para detección de causas"""
    try:
        print(f"\nProcesando pestaña '{tab_name}' con OpenAI...")
        
        # Manejar paginación
        for pagina in manejar_paginacion(page, tab_name):
            # Obtener HTML de la página actual
            html_content = page.content()
            
            # Enviar a OpenAI para procesamiento
            resultado = procesar_html_con_openai(html_content, tab_name)
            
            if not resultado.get("causas"):
                print(f"  OpenAI no encontró causas nuevas en página {pagina}")
            else:
                print(f"  OpenAI encontró {len(resultado['causas'])} causas nuevas")
                procesar_causas_detectadas(page, resultado["causas"], tab_name)
        
        return True
        
    except Exception as e:
        logging.error(f"Error procesando pestaña {tab_name} con OpenAI: {str(e)}")
        return False

def determinar_tipo_procesamiento(page, tab_name):
    """Determina automáticamente si la pestaña usa cuadernos"""
    # Verificar si existe el selector de cuadernos
    if page.query_selector('#selCuaderno'):
        return "con_cuadernos"
    
    # Verificar si hay elementos típicos de modales simples
    if page.query_selector('form[name="frmPdf"], form[name="frmDoc"]'):
        return "simple"
    
    # Por defecto usar procesamiento simple
    return "simple"

def procesar_causas_detectadas(page, causas, tab_name):
    """Procesa cada causa detectada por OpenAI"""
    for idx, causa in enumerate(causas, 1):
        try:
            print(f"  [{idx}/{len(causas)}] Procesando: {causa['caratulado']}")
            
            # Hacer clic en la lupa
            page.click(causa["selector_lupa"])
            random_sleep(1.5, 2.5)
            
            # Crear carpeta base
            carpeta_general = tab_name.replace(' ', '_')
            caratulado_limpio = limpiar_nombre_archivo(causa['caratulado'])[:50]
            carpeta_caratulado = f"{carpeta_general}/{caratulado_limpio}"
            os.makedirs(carpeta_caratulado, exist_ok=True)
            
            # Tomar captura del panel de información
            panel = page.query_selector(".panel.panel-default, .table-titulos")
            if panel:
                panel_path = f"{carpeta_caratulado}/Detalle_causa.png"
                panel.screenshot(path=panel_path)
            
            # Determinar tipo de procesamiento según la pestaña
            tipo_procesamiento = determinar_tipo_procesamiento(page, tab_name)
            
            if tipo_procesamiento == "con_cuadernos":
                procesar_cuadernos_modal(page, carpeta_caratulado, causa, tab_name)
            else:
                procesar_modal_simple(page, carpeta_caratulado, causa, tab_name)
                
            # Cerrar modal
            page.evaluate('''() => {
                const closeBtn = document.querySelector('.modal .close, .modal [data-dismiss="modal"]');
                if (closeBtn) closeBtn.click();
            }''')
            random_sleep(1, 2)
            
        except Exception as e:
            print(f"    ✗ Error procesando causa: {str(e)}")
            continue

def procesar_cuadernos_modal(page, carpeta_caratulado, causa, tab_name):
    """Procesa cuadernos en modales de forma genérica"""
    try:
        # Obtener opciones de cuadernos
        opciones = page.evaluate('''() => {
            const select = document.querySelector('#selCuaderno');
            if (!select) return [];
            
            return Array.from(select.options)
                .map(opt => ({ 
                    value: opt.value, 
                    text: opt.textContent.trim(),
                    selected: opt.selected
                }))
                .filter(opt => opt.value);
        }''')
        
        if not opciones:
            print("No se encontraron cuadernos, procesando como modal simple")
            procesar_modal_simple(page, carpeta_caratulado, causa, tab_name)
            return
            
        for opcion in opciones:
            try:
                if not opcion['value']: 
                    continue
                
                print(f"    Procesando cuaderno: {opcion['text']}")
                
                # Seleccionar cuaderno solo si no está seleccionado
                if not opcion['selected']:
                    page.select_option('#selCuaderno', value=opcion['value'])
                    random_sleep(1, 2)
                
                # Crear carpeta para cuaderno
                cuaderno_limpio = limpiar_nombre_archivo(opcion['text'])[:30]
                carpeta_cuaderno = f"{carpeta_caratulado}/Cuaderno_{cuaderno_limpio}"
                os.makedirs(carpeta_cuaderno, exist_ok=True)
                
                # Procesar movimientos con OpenAI
                html_modal = page.content()
                resultado = procesar_modal_generico_con_openai(html_modal, causa['caratulado'], opcion['text'], tab_name)
                
                for movimiento in resultado.get("movimientos", []):
                    procesar_movimiento_generico(page, carpeta_cuaderno, causa, movimiento, tab_name)
                    
            except Exception as e:
                print(f"      ✗ Error procesando cuaderno: {str(e)}")
                continue
                
    except Exception as e:
        print(f"    ✗ Error general en cuadernos: {str(e)}")

def procesar_movimiento_generico(page, carpeta_cuaderno, causa, movimiento, tab_name):
    """Procesa movimientos en cualquier pestaña"""
    try:
        print(f"      Movimiento: {movimiento['tramite']}")
        
        # Determinar URL base según pestaña
        base_urls = {
            "Civil": "https://oficinajudicialvirtual.pjud.cl/misCausas/civil/documentos/docuS.php?dtaDoc=",
            "Cobranza": "https://oficinajudicialvirtual.pjud.cl/misCausas/cobranza/documentos/docuCobranza.php?dtaDoc=",
            "Laboral": "https://oficinajudicialvirtual.pjud.cl/misCausas/laboral/documentos/docuLaboral.php?dtaDoc=",
            "Penal": "https://oficinajudicialvirtual.pjud.cl/misCausas/penal/documentos/docuPenal.php?dtaDoc=",
            "Familia": "https://oficinajudicialvirtual.pjud.cl/misCausas/familia/documentos/docuFamilia.php?dtaDoc=",
            "Disciplinario": "https://oficinajudicialvirtual.pjud.cl/misCausas/disciplinario/documentos/docuDisciplinario.php?dtaDoc="
        }
        
        # URL por defecto si no está en el diccionario
        base_url = base_urls.get(tab_name, "https://oficinajudicialvirtual.pjud.cl/misCausas/generico/documentos/docuGenerico.php?dtaDoc=")
            
        pdf_url = base_url + movimiento['token_pdf']
        fecha_limpia = movimiento['fecha'].replace('/', '')
        folio_limpio = limpiar_nombre_archivo(movimiento['folio'])[:10]
        pdf_filename = f"{carpeta_cuaderno}/{fecha_limpia}_{folio_limpio}.pdf"
        
        if descargar_pdf_directo(pdf_url, pdf_filename, page):
            # Generar preview
            preview_path = pdf_filename.replace('.pdf', '_preview.png')
            generar_preview_pdf(pdf_filename, preview_path)
            
            # Crear objeto movimiento
            mov_pjud = MovimientoPJUD(
                folio=movimiento['folio'],
                seccion=tab_name,
                caratulado=causa['caratulado'],
                fecha=movimiento['fecha'],
                pdf_path=pdf_filename,
                cuaderno=causa.get('cuaderno', None),
                historia_causa_cuaderno=causa.get('cuaderno', None)
            )
            
            if agregar_movimiento_sin_duplicar(mov_pjud):
                print(f"      ✓ Movimiento registrado")
    
    except Exception as e:
        print(f"        ✗ Error procesando movimiento: {str(e)}")

def procesar_modal_simple(page, carpeta_caratulado, causa, tab_name):
    """Procesa modales simples de forma genérica"""
    try:
        # Enfoque generalizado para buscar formularios PDF
        pdf_url = page.evaluate('''() => {
            // Buscar cualquier formulario que pueda contener PDF
            const forms = document.querySelectorAll('form');
            
            for (const form of forms) {
                // Buscar inputs ocultos que podrían contener tokens
                const tokenInputs = form.querySelectorAll('input[type="hidden"][name][value]');
                
                for (const input of tokenInputs) {
                    // Considerar solo inputs con nombres que suenan a token
                    if (input.name.toLowerCase().includes('token') || 
                        input.name.toLowerCase().includes('file') || 
                        input.name.toLowerCase().includes('doc') || 
                        input.name.toLowerCase().includes('valor')) {
                        
                        // Construir URL
                        const separator = form.action.includes('?') ? '&' : '?';
                        return `${form.action}${separator}${input.name}=${input.value}`;
                    }
                }
            }
            return null;
        }''')
        
        if not pdf_url:
            print("    ✗ No se encontró formulario PDF")
            return
            
        # Descargar PDF
        fecha_limpia = causa['fecha_movimiento'].replace('/', '')
        identificador_limpio = limpiar_nombre_archivo(causa['identificador'])[:20]
        pdf_filename = f"{carpeta_caratulado}/{fecha_limpia}_{identificador_limpio}.pdf"
        
        if descargar_pdf_directo(pdf_url, pdf_filename, page):
            # Generar preview
            preview_path = pdf_filename.replace('.pdf', '_preview.png')
            generar_preview_pdf(pdf_filename, preview_path)
            
            # Crear objeto movimiento
            mov_pjud = MovimientoPJUD(
                folio=str(uuid.uuid4())[:8],
                seccion=tab_name,
                caratulado=causa['caratulado'],
                corte=causa.get('corte_tribunal', None),
                tribunal=causa.get('corte_tribunal', None),
                libro=causa['identificador'] if "libro" in causa['identificador'].lower() else None,
                rit=causa['identificador'] if "rit" in causa['identificador'].lower() else None,
                rol=causa['identificador'] if "rol" in causa['identificador'].lower() else None,
                fecha=causa['fecha_movimiento'],
                pdf_path=pdf_filename
            )
            
            if agregar_movimiento_sin_duplicar(mov_pjud):
                print(f"    ✓ Movimiento registrado")
                
    except Exception as e:
        print(f"    ✗ Error procesando modal simple: {str(e)}")

# Navegación por pestañas 
def navigate_mis_causas_tabs(page):
    """Navega por pestañas usando OpenAI para detección de causas"""
    print("\n--- Navegando por pestañas con OpenAI ---")
    
    for tab_name in MIS_CAUSAS_TABS:
        try:
            print(f"\n> Navegando a pestaña '{tab_name}'")
            
            # Cambiar a pestaña
            page.click(f"a:has-text('{tab_name}')")
            random_sleep(2, 3)
            
            # Procesar con OpenAI
            procesar_pestana_con_openai(page, tab_name)
            
        except Exception as e:
            print(f"  Error en pestaña '{tab_name}': {str(e)}")
            continue
    
    print("\n--- Procesamiento con OpenAI completado ---")

#  Funciones de correo electrónico 
def construir_cuerpo_html(movimientos, imagenes_cid=None):
    if not movimientos:
        return """
            <html>
            <head><style>body { font-family: Arial, sans-serif; }</style></head>
            <body>
                <p>Estimado,</p>
                <p>No se encontraron nuevos movimientos para reportar en el Poder Judicial.</p>
                <p>Saludos cordiales</p>
            </body>
            </html>
            """
    else:
        html = """
        <html>
        <head>
            <style>
                body { font-family: Arial, sans-serif; }
                .container { max-width: 800px; margin: 0 auto; padding: 20px; }
                .movimiento { margin-bottom: 30px; border-bottom: 1px solid #eee; padding-bottom: 20px; }
                .movimiento h3 { color: #333; margin-top: 0; }
                .movimiento ul { list-style-type: none; padding-left: 0; }
                .movimiento li { margin-bottom: 10px; }
                .movimiento strong { color: #555; display: inline-block; width: 150px; }
            </style>
        </head>
        <body>
            <div class="container">
                <p>Estimado,</p>
                <p>Se encontraron nuevos movimientos en el Poder Judicial:</p>
        """
        
        for mov in movimientos:
            identificador_limpio = limpiar_identificador(mov.rol) or limpiar_identificador(mov.rit) or limpiar_identificador(mov.libro) or "N/A"
            
            html += f"""
                <div class="movimiento">
                    <h3>{mov.caratulado}</h3>
                    <ul>
                        <li><strong>Instancia:</strong> {mov.seccion}</li>
                        <li><strong>Identificador:</strong> {identificador_limpio}</li>
            """
            
            if mov.corte:
                html += f"<li><strong>Corte:</strong> {mov.corte}</li>"
            elif mov.tribunal:
                html += f"<li><strong>Tribunal:</strong> {mov.tribunal}</li>"
                
            html += f"""
                        <li><strong>Fecha:</strong> {mov.fecha}</li>
                        <li><strong>Documento:</strong> {os.path.basename(mov.pdf_path)}</li>
            """
            
            if mov.cuaderno:
                html += f"<li><strong>Cuaderno:</strong> {mov.cuaderno}</li>"
                
            html += """
                    </ul>
            """
            
            # Vista previa de PDF
            if mov.tiene_pdf():
                preview_path = mov.pdf_path.replace('.pdf', '_preview.png')
                if preview_path in imagenes_cid:
                    html += f'<img src="cid:{imagenes_cid[preview_path]}" style="max-width:600px; margin:10px 0;"><br>'
            
            html += "</div>"
        
        html += """
            </div>
        </body>
        </html>
        """
        return html

def enviar_correo(movimientos=None, asunto="Notificación de Sistema de Poder Judicial"):
    try:
        if not all([EMAIL_SENDER, EMAIL_PASSWORD, EMAIL_RECIPIENTS]):
            logging.error("Faltan credenciales de correo electrónico")
            return False

        msg = MIMEMultipart()
        msg['From'] = EMAIL_SENDER
        msg['To'] = ", ".join(EMAIL_RECIPIENTS)
        msg['Subject'] = asunto

        # Adjuntar imágenes preview
        imagenes_cid = {}
        if movimientos:
            for movimiento in movimientos:
                if movimiento.tiene_pdf():
                    preview_path = movimiento.pdf_path.replace('.pdf', '_preview.png')
                    if os.path.exists(preview_path):
                        cid = str(uuid.uuid4())
                        imagenes_cid[preview_path] = cid
                        with open(preview_path, 'rb') as img:
                            img_part = MIMEImage(img.read(), _subtype="png")
                            img_part.add_header('Content-ID', f'<{cid}>')
                            img_part.add_header('Content-Disposition', 'inline', filename=os.path.basename(preview_path))
                            msg.attach(img_part)
        
        # Construir cuerpo HTML
        html_cuerpo = construir_cuerpo_html(movimientos, imagenes_cid)
        msg.attach(MIMEText(html_cuerpo, 'html'))
        
        # Adjuntar PDFs
        if movimientos:
            for movimiento in movimientos:
                if movimiento.tiene_pdf():
                    with open(movimiento.pdf_path, 'rb') as f:
                        part = MIMEApplication(f.read(), Name=os.path.basename(movimiento.pdf_path))
                        part['Content-Disposition'] = f'attachment; filename="{os.path.basename(movimiento.pdf_path)}"'
                        msg.attach(part)

        # Enviar correo
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.send_message(msg)
        
        logging.info("Correo enviado exitosamente")
        return True
        
    except Exception as e:
        logging.error(f"Error enviando correo: {str(e)}")
        return False

#  Función principal 
def automatizar_poder_judicial(page, username, password):
    try:
        print("\n=== AUTOMATIZACIÓN DEL PODER JUDICIAL ===")
        MOVIMIENTOS_GLOBALES.clear()
        
        # Abrir PJUD y login
        page.goto(BASE_URL_PJUD)
        page.click("button:has-text('Todos los servicios')")
        page.click("a:has-text('Clave Única')")
        
        if login(page, username, password):
            navigate_to_mis_causas(page)
            navigate_mis_causas_tabs(page)
            
            # Mostrar resumen
            print("\nResumen de movimientos encontrados:")
            for mov in MOVIMIENTOS_GLOBALES:
                print(f" - {mov.caratulado} ({mov.identificador_causa})")
            
            # Enviar correo
            if MOVIMIENTOS_GLOBALES:
                asunto = f"{len(MOVIMIENTOS_GLOBALES)} nuevos movimientos en PJUD"
                enviar_correo(MOVIMIENTOS_GLOBALES, asunto)
            else:
                enviar_correo(asunto="Sin movimientos nuevos en PJUD")
            
            return True
        return False
        
    except Exception as e:
        print(f"Error principal: {str(e)}")
        return False

#  Ejecución principal 
def main():
    # Verificar si es fin de semana
    if datetime.datetime.now().weekday() >= 5:
        logging.info("Hoy es fin de semana. No se realizan tareas.")
        return

    # Verificar credenciales
    if not all([USERNAME, PASSWORD, OPENAI_API_KEY]):
        logging.error("Faltan credenciales en .env")
        return
    
    playwright, browser, page = None, None, None
    try:
        # Configurar navegador
        playwright, browser, page = setup_browser()
        
        # Ejecutar automatización
        automatizar_poder_judicial(page, USERNAME, PASSWORD)
        
    except Exception as e:
        logging.error(f"Error en ejecución principal: {str(e)}")
    finally:
        # Cerrar navegador
        if browser: 
            browser.close()
        if playwright: 
            playwright.stop()

if __name__ == "__main__":
    main()