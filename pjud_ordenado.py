import time
import random
import os
import re
import smtplib
import logging
import datetime
from playwright.sync_api import sync_playwright
from dotenv import load_dotenv
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from pathlib import Path
from pdf2image import convert_from_path
import PyPDF2
import uuid
from email.mime.image import MIMEImage
from PIL import Image

# ---------------------------
# Configuración inicial
# ---------------------------
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

# Constantes globales
EMAIL_SENDER = os.getenv("EMAIL_SENDER_TEST")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD_TEST")
EMAIL_RECIPIENTS = os.getenv("EMAIL_RECIPIENTS_TEST", "").split(",")
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
BASE_URL_PJUD = "https://oficinajudicialvirtual.pjud.cl/home/"

# Listas y diccionarios para la navegación en PJUD
MIS_CAUSAS_TABS = ["Corte Suprema", "Corte Apelaciones", 
                   "Civil", 
                   #"Laboral", "Penal", 
                   "Cobranza", 
                   #"Familia", "Disciplinario"
                   ]
USER_AGENTS = [
    # Navegadores de escritorio
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.6367.78 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.6367.78 Safari/537.36",
    # Navegadores móviles
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 12; SM-G991B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.6367.78 Mobile Safari/537.36"
]

# Diccionario de funciones JavaScript por pestaña
TAB_FUNCTIONS = {
    "Corte Suprema": "buscSup",
    "Corte Apelaciones": "buscApe",
    "Civil": "buscCiv",
    #"Laboral": "buscLab",
    "Penal": "buscPen",
    #"Cobranza": "buscCob",
    #"Familia": "buscFam"
}

# Mapeo de pestañas a tipo de lupa
TIPO_LUPA_MAP = {
    "Corte Suprema": "suprema",
    "Corte Apelaciones": "apelaciones_principal",
    "Civil": "civil",
    "Cobranza": "cobranza"
}

# ---------------------------
# Clases y estructuras de datos
# ---------------------------
class MovimientoPJUD:
    def __init__(self, **kwargs):
        self.folio = kwargs.get('folio')
        self.seccion = kwargs.get('seccion')
        self.caratulado = kwargs.get('caratulado')
        self.tribunal = kwargs.get('tribunal')
        self.corte = kwargs.get('corte')
        self.fecha = kwargs.get('fecha')
        self.libro = kwargs.get('libro')
        self.rit = kwargs.get('rit')
        self.rol = kwargs.get('rol')
        self.pdf_path = kwargs.get('pdf_path')
        self.cuaderno = kwargs.get('cuaderno')
        self.archivos_apelaciones = kwargs.get('archivos_apelaciones', [])
        self.historia_causa_cuaderno = kwargs.get('historia_causa_cuaderno')
    
    def tiene_pdf(self):
        return self.pdf_path and os.path.exists(self.pdf_path)
    
    def tiene_archivos_apelaciones(self):
        return len(self.archivos_apelaciones) > 0
    
    def to_dict(self):
        return {attr: getattr(self, attr) for attr in [
            'folio', 'seccion', 'caratulado', 'fecha', 'libro', 
            'rit', 'rol', 'tribunal', 'corte', 'pdf_path', 'cuaderno',
            'archivos_apelaciones', 'historia_causa_cuaderno'
        ]}
    
    def __eq__(self, other):
        if not isinstance(other, MovimientoPJUD):
            return False
        return all([
            self.folio == other.folio,
            self.seccion == other.seccion,
            self.caratulado == other.caratulado,
            self.fecha == other.fecha,
            self.libro == other.libro,
            self.rit == other.rit,
            self.rol == other.rol,
            self.cuaderno == other.cuaderno,
            self.tribunal == other.tribunal,
            self.corte == other.corte,
            os.path.basename(self.pdf_path or "") == os.path.basename(other.pdf_path or "")
        ])
    
    @property
    def identificador_causa(self):
        return self.rol or self.rit or self.libro

# Lista global para movimientos
MOVIMIENTOS_GLOBALES = []

# ---------------------------
# Funciones utilitarias
# ---------------------------
def random_sleep(min_seconds=1, max_seconds=3):
    time.sleep(random.uniform(min_seconds, max_seconds))

def simulate_human_behavior(page):
    if random.random() < 0.3:
        page.mouse.wheel(0, random.randint(100, 500))
        random_sleep(0.5, 1.5)
    
    if random.random() < 0.2:
        x = random.randint(100, 800)
        y = random.randint(100, 600)
        page.mouse.move(x, y)
        random_sleep(0.5, 1.5)

def limpiar_nombre_archivo(nombre):
    return re.sub(r'[<>:"/\\|?*\n\r\t]', '', nombre)

def limpiar_identificador(texto):
    """Limpia identificadores judiciales removiendo etiquetas"""
    if not texto:
        return ""
    return re.sub(r'^(Libro\s*:|RIT\s*:|ROL\s*:)\s*', '', texto, flags=re.IGNORECASE).strip()

def agregar_movimiento_sin_duplicar(movimiento):
    if not any(m == movimiento for m in MOVIMIENTOS_GLOBALES):
        MOVIMIENTOS_GLOBALES.append(movimiento)
        return True
    return False

# ---------------------------
# Funciones de PDF
# ---------------------------

def descargar_pdf_directo(pdf_url, pdf_filename, page):
    if os.path.exists(pdf_filename):
        logging.info(f"El archivo {pdf_filename} ya existe")
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
        logging.info(f"PDF descargado: {pdf_filename}")
        return True
    else:
        logging.error(f"Error al descargar PDF: Status {response.status}")
        return False

def extraer_resumen_pdf(pdf_path):
    try:
        with open(pdf_path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            if reader.pages:
                text = reader.pages[0].extract_text()
                if text:
                    lineas = text.strip().splitlines()
                    lineas_utiles = [
                        linea.strip() for linea in lineas
                        if not any(patron in linea.lower() for patron in [
                            "firma electrónica", "verificadoc.pjud.cl", 
                            "horaoficial.cl", "puede ser validado",
                            "establecido en chile", "para más información"
                        ]) and linea.strip()
                    ]
                    return " ".join(" ".join(lineas_utiles).split()[:15])
        return "sin_resumen"
    except Exception as e:
        logging.error(f"No se pudo extraer resumen del PDF: {e}")
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
            logging.info(f"Vista previa guardada: {preview_path}")
    except Exception as e:
        logging.error(f"Error generando preview: {e}")

# ---------------------------
# Manejo de navegador
# ---------------------------
def setup_browser():
    playwright = sync_playwright().start()
    selected_user_agent = random.choice(USER_AGENTS)
    logging.info(f"User-Agent seleccionado: {selected_user_agent}")
    
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
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
        Object.defineProperty(navigator, 'languages', { get: () => ['es-ES', 'es'] });
    """)
    
    page = context.new_page()
    page.set_default_timeout(30000)
    page.set_default_navigation_timeout(30000)
    
    return playwright, browser, page

# ---------------------------
# Funciones de navegación
# ---------------------------
def login(page, username, password):
    try:
        logging.info("Esperando página de Clave Única...")
        random_sleep(2, 4)
        simulate_human_behavior(page)

        logging.info("Ingresando usuario...")
        page.fill('#uname', username)
        random_sleep(1, 2)
        
        logging.info("Ingresando contraseña...")
        page.fill('#pword', password)
        random_sleep(1, 2)
        
        page.keyboard.press('Enter')
        page.keyboard.press('Enter')
        random_sleep(2, 4)
        simulate_human_behavior(page)
        
        page.wait_for_selector('text=Oficina Judicial Virtual', timeout=30000)
        logging.info("Inicio de sesión exitoso!")
        return True
    except Exception as e:
        logging.error(f"Error durante login: {str(e)}")
        return False

def navigate_to_mis_causas(page):
    try:
        logging.info("Navegando a 'Mis Causas'...")
        page.evaluate("misCausas();")
        logging.info("Navegación a 'Mis Causas' mediante JS exitosa!")
        random_sleep(1, 4)
        return True
    except Exception as js_error:
        logging.error(f"Error JS: {str(js_error)}")
        try:
            page.click("a:has-text('Mis Causas')")
            logging.info("Navegación mediante clic directo exitosa!")
            return True
        except Exception as click_error:
            logging.error(f"Error clic directo: {str(click_error)}")
            return False

def cerrar_modales_abiertos(page):
    try:
        page.evaluate("""
            document.querySelectorAll('.modal.in, .modal[style*="display: block"]').forEach(modal => {
                modal.style.display = 'none';
                modal.classList.remove('in');
            });
            document.body.classList.remove('modal-open');
            document.querySelectorAll('.modal-backdrop').forEach(backdrop => {
                backdrop.parentNode.removeChild(backdrop);
            });
        """)
        random_sleep(1, 2)
        return True
    except Exception as e:
        logging.error(f"Error cerrando modales: {str(e)}")
        return False

# ---------------------------
# Controladores de lupa (Base)
# ---------------------------
class ControladorLupaBase:
    CONFIG = {
        'modal_selector': "",
        'modal_title': "",
        'table_selector': "",
        'expected_headers': [],
        'lupa_selector': ""
    }
    
    def __init__(self, page):
        self.page = page
        self.config = self.obtener_config()
    
    def obtener_config(self):
        return self.CONFIG
    
    def _obtener_lupas(self):
        return self.page.query_selector_all(self.config['lupa_selector'])
    
    def _manejar_error(self, e):
        print(f"  Error: {str(e)}")
        try:
            self._cerrar_ambos_modales()
        except Exception as close_error:
            print(f"  Error adicional: {str(close_error)}")
    
    def _cerrar_modal(self):
        try:
            close_button = self.page.query_selector(
                f"{self.config['modal_selector']} .close, "
                f"{self.config['modal_selector']} button[data-dismiss='modal']"
            )
            if close_button:
                close_button.click()
                self.page.wait_for_selector(self.config['modal_selector'], state='hidden', timeout=5000)
            else:
                self._cerrar_ambos_modales()
        except Exception as e:
            print(f"  Error al cerrar modal: {str(e)}")
    
    def _verificar_modal(self):
        # Espera a que el modal esté presente en el DOM (no necesariamente visible)
        self.page.wait_for_selector(self.config['modal_selector'], timeout=10000)
        random_sleep(1, 2)
        # Evalúa visibilidad y título, usando función flecha para evitar errores de return
        js_code = f"""
            () => {{
                const modal = document.querySelector('{self.config['modal_selector']}');
                if (!modal) return false;
                const style = window.getComputedStyle(modal);
                if (style.display === 'none' || style.visibility === 'hidden') return false;
                const title = modal.querySelector('.modal-title');
                return title && title.textContent.includes('{self.config['modal_title']}');
            }}
        """
        return self.page.evaluate(js_code)
    
    def _verificar_tabla(self):
        try:
            self.page.wait_for_selector(self.config['table_selector'], timeout=10000)
            if self.config.get('expected_headers'):
                js_code = f"""
                    () => {{
                        const table = document.querySelector('{self.config['table_selector']}');
                        if (!table) return false;
                        const headers = Array.from(table.querySelectorAll('th')).map(th => th.textContent.trim());
                        const expectedHeaders = {self.config['expected_headers']};
                        const rows = table.querySelectorAll('tbody tr');
                        return headers.length > 0 && rows.length > 0;
                    }}
                """
                return self.page.evaluate(js_code)
            return True
        except Exception as table_error:
            print(f"  Error esperando la tabla: {str(table_error)}")
            return False
    
    def _cerrar_ambos_modales(self):
        self.page.evaluate("""
            document.querySelectorAll('.modal.in, .modal[style*="display: block"]').forEach(modal => {
                modal.style.display = 'none';
                modal.classList.remove('in');
            });
            document.body.classList.remove('modal-open');
            document.querySelectorAll('.modal-backdrop').forEach(backdrop => {
                if (backdrop.parentNode) backdrop.parentNode.removeChild(backdrop);
            });
        """)
    
    def manejar(self, tab_name):
        try:
            lupas = self._obtener_lupas()
            if not lupas:
                return False
            
            for lupa_link in lupas:
                try:
                    fila = lupa_link.evaluate_handle('el => el.closest("tr")')
                    tds = fila.query_selector_all('td')
                    if len(tds) < 4:
                        continue
                    
                    caratulado = tds[3].inner_text().strip()
                    corte = tds[2].inner_text().replace("Corte:", "").strip() if len(tds) > 5 else None
                    
                    lupa_link.scroll_into_view_if_needed()
                    random_sleep(0.5, 1)
                    lupa_link.click()
                    random_sleep(1, 2)
                    
                    if self._verificar_modal():
                        self._procesar_contenido(tab_name, caratulado, corte)
                    
                    self._cerrar_modal()
                    break  # Procesar solo primera lupa
                except Exception as e:
                    self._manejar_error(e)
            return True
        except Exception as e:
            self._manejar_error(e)
            return False
    
    def _procesar_contenido(self, tab_name, caratulado, corte):
        raise NotImplementedError("Método debe ser implementado en subclases")

class ControladorLupaSuprema(ControladorLupaBase):
    def obtener_config(self):
        return {
            'lupa_selector': "#dtaTableDetalleMisCauSup tbody tr td a[href*='modalDetalleMisCauSuprema']",
            'modal_selector': "#modalDetalleMisCauSuprema",
            'modal_title': "Detalle Causa",
            'table_selector': ".modal-content table.table-bordered",
            'expected_headers': ['Folio', 'Tipo', 'Descripción', 'Fecha', 'Documento']
        }

    def _procesar_contenido(self, tab_name, caratulado, corte):
        try:
            return self._procesar_movimientos_suprema(tab_name, caratulado, corte)
        except Exception as e:
            print(f"[ERROR] Error en procesamiento Suprema: {str(e)}")
            return False

    def _procesar_movimientos_suprema(self, tab_name, caratulado, corte):
        print(f"[INFO] Verificando movimientos nuevos en pestaña '{tab_name}'...")
        panel = self.page.query_selector("#modalDetalleMisCauSuprema .modal-body .panel.panel-default")
        libro_text = self._extraer_libro_text(panel)
        
        # Validar que tenemos la tabla de movimientos
        if not self._verificar_tabla():
            print("[ERROR] No se pudo verificar la tabla de movimientos")
            return False
            
        movimientos = self.page.query_selector_all(f"{self.config['table_selector']} tbody tr")
        print(f"[INFO] Se encontraron {len(movimientos)} movimientos")
        movimientos_nuevos = False

        fecha_objetivo = "01/12/2022"  # Fecha específica para Corte Suprema

        for movimiento in movimientos:
            try:
                tds = movimiento.query_selector_all('td')
                if len(tds) < 5:
                    continue
                    
                folio = tds[0].inner_text().strip()
                fecha_tramite_str = tds[4].inner_text().strip()
                
                # Solo procesar movimientos de la fecha objetivo
                if fecha_tramite_str != fecha_objetivo:
                    print(f"[INFO] Movimiento ignorado - Folio: {folio}, Fecha: {fecha_tramite_str} (no coincide con fecha objetivo)")
                    continue
                    
                print(f"[INFO] Movimiento encontrado - Folio: {folio}, Fecha: {fecha_tramite_str}")
                movimientos_nuevos = True
                
                # Limpiar caratulado para usar en rutas de archivos
                caratulado_limpio = limpiar_nombre_archivo(caratulado)
                carpeta_caratulado = self._crear_carpeta_caratulado(tab_name, caratulado_limpio)
                self._guardar_panel_info(panel, carpeta_caratulado)
                
                pdf_path = self._descargar_y_procesar_pdf(movimiento, fecha_tramite_str, libro_text, carpeta_caratulado)
                
                movimiento_pjud = MovimientoPJUD(
                    folio=folio,
                    seccion=tab_name,
                    caratulado=caratulado,  # Usar el original para el objeto
                    libro=libro_text,
                    fecha=fecha_tramite_str,
                    pdf_path=pdf_path,
                    corte=corte
                )
                
                if agregar_movimiento_sin_duplicar(movimiento_pjud):
                    print(f"[INFO] Movimiento agregado exitosamente al diccionario global")
                else:
                    print(f"[INFO] El movimiento ya existía en el diccionario global")
                    
            except Exception as e:
                print(f"[ERROR] Error procesando movimiento: {str(e)}")
                continue
                
        return movimientos_nuevos

    def _extraer_libro_text(self, panel):
        libro_text = ""
        if panel:
            try:
                panel.scroll_into_view_if_needed()
                random_sleep(1, 2)
                libro_td = panel.query_selector("td:has-text('libro')")
                if libro_td:
                    libro_text = libro_td.inner_text()
                    print(f"[INFO] Texto completo del libro extraído: {libro_text}")
            except Exception as e:
                print(f"[WARN] No se pudo extraer el número de causa: {str(e)}")
        else:
            print("[WARN] No se encontró el panel de información")
            
        return libro_text

    def _crear_carpeta_caratulado(self, tab_name, caratulado):
        carpeta_general = tab_name.replace(' ', '_')
        carpeta_caratulado = f"{carpeta_general}/{caratulado}"
        
        if not os.path.exists(carpeta_caratulado):
            print(f"[INFO] Creando carpeta: {carpeta_caratulado}")
            os.makedirs(carpeta_caratulado)
        else:
            print(f"[INFO] La carpeta {carpeta_caratulado} ya existe.")
            
        return carpeta_caratulado

    def _guardar_panel_info(self, panel, carpeta_caratulado):
        if not panel:
            return
            
        detalle_panel_path = f"{carpeta_caratulado}/Detalle_causa.png"
        
        if os.path.exists(detalle_panel_path):
            print(f"[INFO] El archivo {detalle_panel_path} ya existe. No se generará nuevamente.")
            return
            
        try:
            # Hacer scroll al panel para asegurar visibilidad
            self.page.evaluate("""
                (element) => {
                    element.scrollIntoView({ behavior: 'smooth', block: 'center' });
                }
            """, panel)
            random_sleep(1, 2)
            
            # Tomar captura del panel
            panel.screenshot(path=detalle_panel_path)
            print(f"[INFO] Captura del panel de información guardada: {detalle_panel_path}")
        except Exception as e:
            print(f"[WARN] No se pudo tomar la captura del panel: {str(e)}")

    def _descargar_y_procesar_pdf(self, movimiento, fecha_tramite_str, libro_text, carpeta_caratulado):
        pdf_form = movimiento.query_selector("form[name='frmPdf']")
        
        if not pdf_form:
            print(f"[WARN] No hay PDF disponible para el movimiento")
            return None
            
        token_input = pdf_form.query_selector("input[name='valorFile']")
        
        if not token_input:
            print(f"[WARN] No se encontró el token para descargar PDF")
            return None
            
        token = token_input.get_attribute("value")
        
        if not token:
            print(f"[WARN] Token vacío para descargar PDF")
            return None
            
        # Crear nombres de archivo
        fecha_tramite_pdf = fecha_tramite_str[6:10] + fecha_tramite_str[3:5] + fecha_tramite_str[0:2]  # Formato AAAAMMDD
        libro_limpio = libro_text.replace("Libro :", "").strip().replace("/", "").replace("-", "") if libro_text else ""
        pdf_filename_tmp = f"{carpeta_caratulado}/{fecha_tramite_pdf}_{libro_limpio}_temp.pdf"
        pdf_filename_final = None
        
        try:
            # Descargar PDF
            base_url = "https://oficinajudicialvirtual.pjud.cl/misCausas/suprema/documentos/docCausaSuprema.php?valorFile="
            original_url = base_url + token
            
            if not descargar_pdf_directo(original_url, pdf_filename_tmp, self.page):
                print(f"[ERROR] No se pudo descargar el PDF")
                return None
                
            # Extraer resumen para nombre final
            resumen_pdf = extraer_resumen_pdf(pdf_filename_tmp)
            resumen_pdf_limpio = limpiar_nombre_archivo(resumen_pdf)[:50]  # Limitar longitud
            
            # Construir nombre final
            nombre_base = f"{fecha_tramite_pdf}_{libro_limpio}_{resumen_pdf_limpio}"
            nombre_base = nombre_base.strip('_')  # Eliminar _ extras al final
            pdf_filename_final = f"{carpeta_caratulado}/{nombre_base}.pdf"
            
            # Renombrar archivo temporal
            try:
                os.rename(pdf_filename_tmp, pdf_filename_final)
            except Exception as e:
                print(f"[WARN] No se pudo renombrar el archivo temporal: {e}")
                # Si no se pudo renombrar, usar el temporal como final
                pdf_filename_final = pdf_filename_tmp
            finally:
                # Eliminar temporal si aún existe
                if os.path.exists(pdf_filename_tmp) and pdf_filename_final != pdf_filename_tmp:
                    try:
                        os.remove(pdf_filename_tmp)
                    except Exception as e:
                        print(f"[WARN] No se pudo eliminar archivo temporal: {e}")
            
            # Generar preview
            preview_path = pdf_filename_final.replace('.pdf', '_preview.png')
            if not os.path.exists(preview_path):
                print(f"[INFO] Generando vista previa del PDF para {pdf_filename_final}...")
                generar_preview_pdf(pdf_filename_final, preview_path)
                
            return pdf_filename_final
            
        except Exception as e:
            print(f"[ERROR] Error al procesar PDF: {e}")
            # Limpiar archivo temporal si hubo error
            if os.path.exists(pdf_filename_tmp):
                try:
                    os.remove(pdf_filename_tmp)
                except Exception:
                    pass
            return None

class ControladorLupaApelacionesPrincipal(ControladorLupaBase):
    def obtener_config(self):
        return {
            'lupa_selector': "#dtaTableDetalleMisCauApe a[href*='modalDetalleMisCauApelaciones']",
            'modal_selector': "#modalDetalleMisCauApelaciones",
            'modal_title': "Detalle Causa",
            'table_selector': ".modal-content table.table-bordered",
            'expected_headers': ['Folio', 'Doc.', 'Anexo', 'Trámite', 'Descripción', 'Fecha', 'Sala', 'Estado', 'Georeferencia']
        }
    
    def _procesar_contenido(self, tab_name, caratulado, corte):
        try:
            return self._procesar_movimientos_apelaciones(tab_name, caratulado, corte)
        except Exception as e:
            print(f"[ERROR] Error en procesamiento Apelaciones: {str(e)}")
            return False

    def _procesar_movimientos_apelaciones(self, tab_name, caratulado, corte):
        print(f"[INFO] Verificando movimientos nuevos en pestaña '{tab_name}'...")
        panel = self.page.query_selector("#modalDetalleMisCauApelaciones .modal-body .panel.panel-default")
        libro_text = self._extraer_libro_text(panel)
        
        # Validar que tenemos la tabla de movimientos
        if not self._verificar_tabla():
            print("[ERROR] No se pudo verificar la tabla de movimientos")
            return False
            
        movimientos = self.page.query_selector_all(f"{self.config['table_selector']} tbody tr")
        print(f"[INFO] Se encontraron {len(movimientos)} movimientos")
        movimientos_nuevos = False

        fecha_objetivo = "01/12/2022"  # Fecha específica para Apelaciones

        for movimiento in movimientos:
            try:
                tds = movimiento.query_selector_all('td')
                # Verificar que tenemos suficientes columnas (al menos 6 para la fecha en índice 5)
                if len(tds) < 6:
                    continue
                    
                folio = tds[0].inner_text().strip()
                fecha_tramite_str = tds[5].inner_text().strip()
                
                if fecha_tramite_str != fecha_objetivo:
                    print(f"[INFO] Movimiento ignorado - Folio: {folio}, Fecha: {fecha_tramite_str} (no coincide con fecha objetivo)")
                    continue
                    
                print(f"[INFO] Movimiento encontrado - Folio: {folio}, Fecha: {fecha_tramite_str}")
                movimientos_nuevos = True
                
                # Limpiar caratulado para usar en rutas de archivos
                caratulado_limpio = limpiar_nombre_archivo(caratulado)
                carpeta_caratulado = self._crear_carpeta_caratulado(tab_name, caratulado_limpio)
                self._guardar_panel_info(panel, carpeta_caratulado)
                
                pdf_path = self._descargar_y_procesar_pdf(movimiento, fecha_tramite_str, libro_text, carpeta_caratulado)
                
                movimiento_pjud = MovimientoPJUD(
                    folio=folio,
                    seccion=tab_name,
                    caratulado=caratulado,  # Original, sin limpiar
                    libro=libro_text,
                    fecha=fecha_tramite_str,
                    pdf_path=pdf_path,
                    corte=corte
                )
                
                if agregar_movimiento_sin_duplicar(movimiento_pjud):
                    print(f"[INFO] Movimiento agregado exitosamente al diccionario global")
                else:
                    print(f"[INFO] El movimiento ya existía en el diccionario global")
                    
            except Exception as e:
                print(f"[ERROR] Error procesando movimiento: {str(e)}")
                continue
                
        return movimientos_nuevos

    def _extraer_libro_text(self, panel):
        libro_text = ""
        if panel:
            try:
                panel.scroll_into_view_if_needed()
                random_sleep(1, 2)
                libro_td = panel.query_selector("td:has-text('libro')")
                if libro_td:
                    libro_text = libro_td.inner_text()
                    print(f"[INFO] Texto completo del libro extraído: {libro_text}")
            except Exception as e:
                print(f"[WARN] No se pudo extraer el número de causa: {str(e)}")
        else:
            print("[WARN] No se encontró el panel de información")
        return libro_text

    def _crear_carpeta_caratulado(self, tab_name, caratulado):
        carpeta_general = tab_name.replace(' ', '_')
        carpeta_caratulado = f"{carpeta_general}/{caratulado}"
        
        if not os.path.exists(carpeta_caratulado):
            print(f"[INFO] Creando carpeta: {carpeta_caratulado}")
            os.makedirs(carpeta_caratulado)
        else:
            print(f"[INFO] La carpeta {carpeta_caratulado} ya existe.")
            
        return carpeta_caratulado

    def _guardar_panel_info(self, panel, carpeta_caratulado):
        if not panel:
            return
            
        detalle_panel_path = f"{carpeta_caratulado}/Detalle_causa.png"
        
        if os.path.exists(detalle_panel_path):
            print(f"[INFO] El archivo {detalle_panel_path} ya existe. No se generará nuevamente.")
            return
            
        try:
            # Hacer scroll al panel para asegurar visibilidad
            self.page.evaluate("""
                (element) => {
                    element.scrollIntoView({ behavior: 'smooth', block: 'center' });
                }
            """, panel)
            random_sleep(1, 2)
            
            # Tomar captura del panel
            panel.screenshot(path=detalle_panel_path)
            print(f"[INFO] Captura del panel de información guardada: {detalle_panel_path}")
        except Exception as e:
            print(f"[WARN] No se pudo tomar la captura del panel: {str(e)}")

    def _descargar_y_procesar_pdf(self, movimiento, fecha_tramite_str, libro_text, carpeta_caratulado):
        # En Apelaciones el formulario se llama 'frmDoc' no 'frmPdf'
        pdf_form = movimiento.query_selector("form[name='frmDoc']")
        
        if not pdf_form:
            print(f"[WARN] No hay PDF disponible para el movimiento")
            return None
            
        token_input = pdf_form.query_selector("input[name='valorDoc']")  # Input es 'valorDoc' en Apelaciones
        
        if not token_input:
            print(f"[WARN] No se encontró el token para descargar PDF")
            return None
            
        token = token_input.get_attribute("value")
        
        if not token:
            print(f"[WARN] Token vacío para descargar PDF")
            return None
            
        # Formatear fecha para el nombre del archivo: AAAAMMDD
        fecha_tramite_pdf = fecha_tramite_str[6:10] + fecha_tramite_str[3:5] + fecha_tramite_str[0:2]
        
        # Limpiar el texto del libro
        libro_limpio = libro_text.replace("Libro :", "").strip().replace("/", "").replace("-", "") if libro_text else ""
        pdf_filename_tmp = f"{carpeta_caratulado}/{fecha_tramite_pdf}_{libro_limpio}_temp.pdf"
        pdf_filename_final = None
        
        try:
            # URL base para descarga en Apelaciones
            base_url = "https://oficinajudicialvirtual.pjud.cl/misCausas/apelaciones/documentos/docCausaApelaciones.php?valorDoc="
            original_url = base_url + token
            
            if not descargar_pdf_directo(original_url, pdf_filename_tmp, self.page):
                print(f"[ERROR] No se pudo descargar el PDF")
                return None
                
            # Extraer resumen para nombre final
            resumen_pdf = extraer_resumen_pdf(pdf_filename_tmp)
            resumen_pdf_limpio = limpiar_nombre_archivo(resumen_pdf)[:50]  # Limitar longitud
            
            # Construir nombre final
            nombre_base = f"{fecha_tramite_pdf}_{libro_limpio}_{resumen_pdf_limpio}"
            nombre_base = nombre_base.strip('_')  # Eliminar _ extras al final
            pdf_filename_final = f"{carpeta_caratulado}/{nombre_base}.pdf"
            
            # Renombrar archivo temporal
            try:
                os.rename(pdf_filename_tmp, pdf_filename_final)
            except Exception as e:
                print(f"[WARN] No se pudo renombrar el archivo temporal: {e}")
                pdf_filename_final = pdf_filename_tmp  # Usar el temporal como final
            finally:
                # Eliminar temporal si aún existe y es diferente del final
                if os.path.exists(pdf_filename_tmp) and pdf_filename_final != pdf_filename_tmp:
                    try:
                        os.remove(pdf_filename_tmp)
                    except Exception as e:
                        print(f"[WARN] No se pudo eliminar archivo temporal: {e}")
            
            # Generar vista previa
            preview_path = pdf_filename_final.replace('.pdf', '_preview.png')
            if not os.path.exists(preview_path):
                print(f"[INFO] Generando vista previa del PDF para {pdf_filename_final}...")
                generar_preview_pdf(pdf_filename_final, preview_path)
                
            return pdf_filename_final
            
        except Exception as e:
            print(f"[ERROR] Error al procesar PDF: {e}")
            # Limpiar archivo temporal si existe
            if os.path.exists(pdf_filename_tmp):
                try:
                    os.remove(pdf_filename_tmp)
                except Exception as e:
                    print(f"[WARN] No se pudo eliminar archivo temporal: {e}")
            return None

class ControladorLupaCivil(ControladorLupaBase):
    def obtener_config(self):
        return {
            'lupa_selector': "#dtaTableDetalleMisCauCiv a[href*='modalAnexoCausaCivil']",
            'modal_selector': "#modalDetalleMisCauCivil",
            'modal_title': "Detalle Causa",
            'table_selector': "#historiaCiv table.table-bordered",
            'expected_headers': ['Folio', 'Doc.', 'Anexo', 'Etapa', 'Trámite', 'Desc. Trámite', 'Fec. Trámite', 'Foja', 'Georeferencia']
        }
    
    def _procesar_contenido(self, tab_name, caratulado, corte):
        try:
            return self._procesar_movimientos_civil(tab_name, caratulado, corte)
        except Exception as e:
            print(f"[ERROR] Error en procesamiento Civil: {str(e)}")
            return False

    def _procesar_movimientos_civil(self, tab_name, caratulado, corte):
        print(f"[INFO] Verificando movimientos nuevos en pestaña '{tab_name}'...")
        panel = self.page.query_selector("#modalDetalleMisCauCivil .modal-body .panel.panel-default")
        
        # Extraer ROL y tribunal además del libro
        libro_text = self._extraer_libro_text(panel)
        rol_text = self._extraer_rol_text(panel)
        tribunal_text = self._extraer_tribunal_text(panel)
        
        if not self._verificar_tabla():
            print("[ERROR] No se pudo verificar la tabla de movimientos")
            return False
            
        movimientos = self.page.query_selector_all(f"{self.config['table_selector']} tbody tr")
        print(f"[INFO] Se encontraron {len(movimientos)} movimientos")
        movimientos_nuevos = False

        fecha_objetivo = "01/12/2022"  # Fecha específica para Civil

        for movimiento in movimientos:
            try:
                tds = movimiento.query_selector_all('td')
                # Verificar que tenemos suficientes columnas (al menos 7 para la fecha en índice 6)
                if len(tds) < 7:
                    continue
                    
                folio = tds[0].inner_text().strip()
                fecha_tramite_str = tds[6].inner_text().strip()
                
                # Manejar fechas con paréntesis (si aplica)
                if '(' in fecha_tramite_str:
                    fecha_tramite_str = fecha_tramite_str.split('(')[0].strip()
                
                if fecha_tramite_str != fecha_objetivo:
                    print(f"[INFO] Movimiento ignorado - Folio: {folio}, Fecha: {fecha_tramite_str} (no coincide con fecha objetivo)")
                    continue
                    
                print(f"[INFO] Movimiento encontrado - Folio: {folio}, Fecha: {fecha_tramite_str}")
                movimientos_nuevos = True
                
                # Limpiar caratulado para usar en rutas de archivos
                caratulado_limpio = limpiar_nombre_archivo(caratulado)
                carpeta_caratulado = self._crear_carpeta_caratulado(tab_name, caratulado_limpio)
                self._guardar_panel_info(panel, carpeta_caratulado)
                
                pdf_path = self._descargar_y_procesar_pdf(
                    movimiento, 
                    fecha_tramite_str, 
                    rol_text,  # Usamos ROL en lugar de libro para Civil
                    carpeta_caratulado
                )
                
                movimiento_pjud = MovimientoPJUD(
                    folio=folio,
                    seccion=tab_name,
                    caratulado=caratulado,
                    libro=libro_text,
                    rol=rol_text,  # Específico para Civil
                    tribunal=tribunal_text,  # Específico para Civil
                    fecha=fecha_tramite_str,
                    pdf_path=pdf_path
                )
                
                if agregar_movimiento_sin_duplicar(movimiento_pjud):
                    print(f"[INFO] Movimiento agregado exitosamente al diccionario global")
                else:
                    print(f"[INFO] El movimiento ya existía en el diccionario global")
                    
            except Exception as e:
                print(f"[ERROR] Error procesando movimiento: {str(e)}")
                continue
                
        return movimientos_nuevos

    def _extraer_libro_text(self, panel):
        libro_text = ""
        if panel:
            try:
                libro_td = panel.query_selector("td:has-text('libro')")
                if libro_td:
                    libro_text = libro_td.inner_text()
                    print(f"[INFO] Texto completo del libro extraído: {libro_text}")
            except Exception as e:
                print(f"[WARN] No se pudo extraer libro: {str(e)}")
        return libro_text

    def _extraer_rol_text(self, panel):
        rol_text = ""
        if panel:
            try:
                rol_td = panel.query_selector("td:has-text('ROL:')")
                if rol_td:
                    rol_text = rol_td.inner_text().replace("ROL:", "").strip()
                    print(f"[INFO] ROL extraído: {rol_text}")
            except Exception as e:
                print(f"[WARN] No se pudo extraer ROL: {str(e)}")
        return rol_text

    def _extraer_tribunal_text(self, panel):
        tribunal_text = ""
        if panel:
            try:
                tribunal_td = panel.query_selector("td:has-text('Tribunal:')")
                if tribunal_td:
                    tribunal_text = tribunal_td.inner_text().replace("Tribunal:", "").strip()
                    print(f"[INFO] Tribunal extraído: {tribunal_text}")
            except Exception as e:
                print(f"[WARN] No se pudo extraer tribunal: {str(e)}")
        return tribunal_text

    def _crear_carpeta_caratulado(self, tab_name, caratulado):
        carpeta_general = tab_name.replace(' ', '_')
        carpeta_caratulado = f"{carpeta_general}/{caratulado}"
        
        if not os.path.exists(carpeta_caratulado):
            print(f"[INFO] Creando carpeta: {carpeta_caratulado}")
            os.makedirs(carpeta_caratulado)
        else:
            print(f"[INFO] La carpeta {carpeta_caratulado} ya existe.")
            
        return carpeta_caratulado

    def _guardar_panel_info(self, panel, carpeta_caratulado):
        if not panel:
            return
            
        detalle_panel_path = f"{carpeta_caratulado}/Detalle_causa.png"
        
        if os.path.exists(detalle_panel_path):
            print(f"[INFO] El archivo {detalle_panel_path} ya existe. No se generará nuevamente.")
            return
            
        try:
            # Hacer scroll al panel para asegurar visibilidad
            self.page.evaluate("""
                (element) => {
                    element.scrollIntoView({ behavior: 'smooth', block: 'center' });
                }
            """, panel)
            random_sleep(1, 2)
            
            # Tomar captura del panel
            panel.screenshot(path=detalle_panel_path)
            print(f"[INFO] Captura del panel de información guardada: {detalle_panel_path}")
        except Exception as e:
            print(f"[WARN] No se pudo tomar la captura del panel: {str(e)}")

    def _descargar_y_procesar_pdf(self, movimiento, fecha_tramite_str, rol_text, carpeta_caratulado):
        # En Civil el formulario puede tener diferentes nombres
        pdf_form = movimiento.query_selector("form[name='frmPdf'], form[name='form']")
        
        if not pdf_form:
            print(f"[WARN] No hay PDF disponible para el movimiento")
            return None
            
        # En Civil el token puede estar en diferentes inputs
        token_input = pdf_form.query_selector("input[name='dtaDoc'], input[name='valorFile']")
        
        if not token_input:
            print(f"[WARN] No se encontró el token para descargar PDF")
            return None
            
        token = token_input.get_attribute("value")
        
        if not token:
            print(f"[WARN] Token vacío para descargar PDF")
            return None
            
        # Formatear fecha para el nombre del archivo: AAAAMMDD
        fecha_tramite_pdf = fecha_tramite_str[6:10] + fecha_tramite_str[3:5] + fecha_tramite_str[0:2]
        
        # Limpiar el texto del ROL
        rol_limpio = limpiar_nombre_archivo(rol_text).replace(" ", "_")[:30] if rol_text else ""
        pdf_filename_tmp = f"{carpeta_caratulado}/{fecha_tramite_pdf}_{rol_limpio}_temp.pdf"
        pdf_filename_final = None
        
        try:
            # Determinar URL base según el formulario (Civil tiene diferentes endpoints)
            action = pdf_form.get_attribute("action")
            if action and "docuS.php" in action:
                base_url = "https://oficinajudicialvirtual.pjud.cl/misCausas/civil/documentos/docuS.php?dtaDoc="
            elif action and "docuN.php" in action:
                base_url = "https://oficinajudicialvirtual.pjud.cl/misCausas/civil/documentos/docuN.php?dtaDoc="
            else:
                # URL por defecto
                base_url = "https://oficinajudicialvirtual.pjud.cl/misCausas/civil/documentos/docuN.php?dtaDoc="
                
            original_url = base_url + token
            
            if not descargar_pdf_directo(original_url, pdf_filename_tmp, self.page):
                print(f"[ERROR] No se pudo descargar el PDF")
                return None
                
            # Extraer resumen para nombre final
            resumen_pdf = extraer_resumen_pdf(pdf_filename_tmp)
            resumen_pdf_limpio = limpiar_nombre_archivo(resumen_pdf)[:40]  # Limitar longitud
            
            # Construir nombre final
            nombre_base = f"{fecha_tramite_pdf}_{rol_limpio}_{resumen_pdf_limpio}"
            nombre_base = nombre_base.strip('_')  # Eliminar _ extras al final
            pdf_filename_final = f"{carpeta_caratulado}/{nombre_base}.pdf"
            
            # Renombrar archivo temporal
            try:
                os.rename(pdf_filename_tmp, pdf_filename_final)
            except Exception as e:
                print(f"[WARN] No se pudo renombrar el archivo temporal: {e}")
                pdf_filename_final = pdf_filename_tmp  # Usar el temporal como final
            finally:
                # Eliminar temporal si aún existe y es diferente del final
                if os.path.exists(pdf_filename_tmp) and pdf_filename_final != pdf_filename_tmp:
                    try:
                        os.remove(pdf_filename_tmp)
                    except Exception as e:
                        print(f"[WARN] No se pudo eliminar archivo temporal: {e}")
            
            # Generar vista previa
            preview_path = pdf_filename_final.replace('.pdf', '_preview.png')
            if not os.path.exists(preview_path):
                print(f"[INFO] Generando vista previa del PDF para {pdf_filename_final}...")
                generar_preview_pdf(pdf_filename_final, preview_path)
                
            return pdf_filename_final
            
        except Exception as e:
            print(f"[ERROR] Error al procesar PDF: {e}")
            # Limpiar archivo temporal si existe
            if os.path.exists(pdf_filename_tmp):
                try:
                    os.remove(pdf_filename_tmp)
                except Exception as e:
                    print(f"[WARN] No se pudo eliminar archivo temporal: {e}")
            return None

class ControladorLupaCobranza(ControladorLupaBase):
    def obtener_config(self):
        return {
            'lupa_selector': "#dtaTableDetalleMisCauCob a[href*='modalAnexoCausaCobranza']",
            'modal_selector': "#modalDetalleMisCauCobranza",
            'modal_title': "Detalle Causa",
            'table_selector': "#historiaCob table.table-bordered",
            'expected_headers': ['Folio', 'Doc.', 'Anexo', 'Etapa', 'Trámite', 'Desc. Trámite', 'Estado Firma', 'Fec. Trámite', 'Georeferencia']
        }
    
    def _procesar_contenido(self, tab_name, caratulado, corte):
        try:
            return self._procesar_movimientos_cobranza(tab_name, caratulado, corte)
        except Exception as e:
            print(f"[ERROR] Error en procesamiento Cobranza: {str(e)}")
            return False

    def _procesar_movimientos_cobranza(self, tab_name, caratulado, corte):
        print(f"[INFO] Verificando movimientos nuevos en pestaña '{tab_name}'...")
        panel = self.page.query_selector("#modalDetalleMisCauCobranza .modal-body .panel.panel-default")
        
        # Extraer RIT y tribunal en lugar de libro
        rit_text = self._extraer_rit_text(panel)
        tribunal_text = self._extraer_tribunal_text(panel)
        
        if not self._verificar_tabla():
            print("[ERROR] No se pudo verificar la tabla de movimientos")
            return False
            
        movimientos = self.page.query_selector_all(f"{self.config['table_selector']} tbody tr")
        print(f"[INFO] Se encontraron {len(movimientos)} movimientos")
        movimientos_nuevos = False

        fecha_objetivo = "01/12/2022"  # Fecha específica para Cobranza

        for movimiento in movimientos:
            try:
                tds = movimiento.query_selector_all('td')
                # Verificar que tenemos suficientes columnas (al menos 8 para la fecha en índice 7)
                if len(tds) < 8:
                    continue
                    
                folio = tds[0].inner_text().strip()
                fecha_tramite_str = tds[7].inner_text().strip()
                
                if fecha_tramite_str != fecha_objetivo:
                    print(f"[INFO] Movimiento ignorado - Folio: {folio}, Fecha: {fecha_tramite_str} (no coincide con fecha objetivo)")
                    continue
                    
                print(f"[INFO] Movimiento encontrado - Folio: {folio}, Fecha: {fecha_tramite_str}")
                movimientos_nuevos = True
                
                # Limpiar caratulado para usar en rutas de archivos
                caratulado_limpio = limpiar_nombre_archivo(caratulado)
                carpeta_caratulado = self._crear_carpeta_caratulado(tab_name, caratulado_limpio)
                self._guardar_panel_info(panel, carpeta_caratulado)
                
                pdf_path = self._descargar_y_procesar_pdf(
                    movimiento, 
                    fecha_tramite_str, 
                    rit_text,  # Usamos RIT en lugar de libro
                    carpeta_caratulado
                )
                
                movimiento_pjud = MovimientoPJUD(
                    folio=folio,
                    seccion=tab_name,
                    caratulado=caratulado,
                    rit=rit_text,  # Específico para Cobranza
                    tribunal=tribunal_text,  # Específico para Cobranza
                    fecha=fecha_tramite_str,
                    pdf_path=pdf_path
                )
                
                if agregar_movimiento_sin_duplicar(movimiento_pjud):
                    print(f"[INFO] Movimiento agregado exitosamente al diccionario global")
                else:
                    print(f"[INFO] El movimiento ya existía en el diccionario global")
                    
            except Exception as e:
                print(f"[ERROR] Error procesando movimiento: {str(e)}")
                continue
                
        return movimientos_nuevos

    def _extraer_rit_text(self, panel):
        rit_text = ""
        if panel:
            try:
                rit_td = panel.query_selector("td:has-text('RIT:')")
                if rit_td:
                    rit_text = rit_td.inner_text().replace("RIT:", "").strip()
                    print(f"[INFO] RIT extraído: {rit_text}")
            except Exception as e:
                print(f"[WARN] No se pudo extraer RIT: {str(e)}")
        return rit_text

    def _extraer_tribunal_text(self, panel):
        tribunal_text = ""
        if panel:
            try:
                tribunal_td = panel.query_selector("td:has-text('Tribunal:')")
                if tribunal_td:
                    tribunal_text = tribunal_td.inner_text().replace("Tribunal:", "").strip()
                    print(f"[INFO] Tribunal extraído: {tribunal_text}")
            except Exception as e:
                print(f"[WARN] No se pudo extraer tribunal: {str(e)}")
        return tribunal_text

    def _crear_carpeta_caratulado(self, tab_name, caratulado):
        carpeta_general = tab_name.replace(' ', '_')
        carpeta_caratulado = f"{carpeta_general}/{caratulado}"
        
        if not os.path.exists(carpeta_caratulado):
            print(f"[INFO] Creando carpeta: {carpeta_caratulado}")
            os.makedirs(carpeta_caratulado)
        else:
            print(f"[INFO] La carpeta {carpeta_caratulado} ya existe.")
            
        return carpeta_caratulado

    def _guardar_panel_info(self, panel, carpeta_caratulado):
        if not panel:
            return
            
        detalle_panel_path = f"{carpeta_caratulado}/Detalle_causa.png"
        
        if os.path.exists(detalle_panel_path):
            print(f"[INFO] El archivo {detalle_panel_path} ya existe. No se generará nuevamente.")
            return
            
        try:
            # Hacer scroll al panel para asegurar visibilidad
            self.page.evaluate("""
                (element) => {
                    element.scrollIntoView({ behavior: 'smooth', block: 'center' });
                }
            """, panel)
            random_sleep(1, 2)
            
            # Tomar captura del panel
            panel.screenshot(path=detalle_panel_path)
            print(f"[INFO] Captura del panel de información guardada: {detalle_panel_path}")
        except Exception as e:
            print(f"[WARN] No se pudo tomar la captura del panel: {str(e)}")

    def _descargar_y_procesar_pdf(self, movimiento, fecha_tramite_str, rit_text, carpeta_caratulado):
        # En Cobranza el formulario se llama 'frmDocH'
        pdf_form = movimiento.query_selector("form[name='frmDocH']")
        
        if not pdf_form:
            print(f"[WARN] No hay PDF disponible para el movimiento")
            return None
            
        # En Cobranza el input se llama 'dtaDoc'
        token_input = pdf_form.query_selector("input[name='dtaDoc']")
        
        if not token_input:
            print(f"[WARN] No se encontró el token para descargar PDF")
            return None
            
        token = token_input.get_attribute("value")
        
        if not token:
            print(f"[WARN] Token vacío para descargar PDF")
            return None
            
        # Formatear fecha para el nombre del archivo: AAAAMMDD
        fecha_tramite_pdf = fecha_tramite_str[6:10] + fecha_tramite_str[3:5] + fecha_tramite_str[0:2]
        
        # Limpiar el texto del RIT
        rit_limpio = limpiar_nombre_archivo(rit_text).replace(" ", "_")[:30] if rit_text else ""
        pdf_filename_tmp = f"{carpeta_caratulado}/{fecha_tramite_pdf}_{rit_limpio}_temp.pdf"
        pdf_filename_final = None
        
        try:
            # URL específica para Cobranza
            base_url = "https://oficinajudicialvirtual.pjud.cl/misCausas/cobranza/documentos/docuCobranza.php?dtaDoc="
            original_url = base_url + token
            
            if not descargar_pdf_directo(original_url, pdf_filename_tmp, self.page):
                print(f"[ERROR] No se pudo descargar el PDF")
                return None
                
            # Extraer resumen para nombre final
            resumen_pdf = extraer_resumen_pdf(pdf_filename_tmp)
            resumen_pdf_limpio = limpiar_nombre_archivo(resumen_pdf)[:40]  # Limitar longitud
            
            # Construir nombre final
            nombre_base = f"{fecha_tramite_pdf}_{rit_limpio}_{resumen_pdf_limpio}"
            nombre_base = nombre_base.strip('_')  # Eliminar _ extras al final
            pdf_filename_final = f"{carpeta_caratulado}/{nombre_base}.pdf"
            
            # Renombrar archivo temporal
            try:
                os.rename(pdf_filename_tmp, pdf_filename_final)
            except Exception as e:
                print(f"[WARN] No se pudo renombrar el archivo temporal: {e}")
                pdf_filename_final = pdf_filename_tmp  # Usar el temporal como final
            finally:
                # Eliminar temporal si aún existe y es diferente del final
                if os.path.exists(pdf_filename_tmp) and pdf_filename_final != pdf_filename_tmp:
                    try:
                        os.remove(pdf_filename_tmp)
                    except Exception as e:
                        print(f"[WARN] No se pudo eliminar archivo temporal: {e}")
            
            # Generar vista previa
            preview_path = pdf_filename_final.replace('.pdf', '_preview.png')
            if not os.path.exists(preview_path):
                print(f"[INFO] Generando vista previa del PDF para {pdf_filename_final}...")
                generar_preview_pdf(pdf_filename_final, preview_path)
                
            return pdf_filename_final
            
        except Exception as e:
            print(f"[ERROR] Error al procesar PDF: {e}")
            # Limpiar archivo temporal si existe
            if os.path.exists(pdf_filename_tmp):
                try:
                    os.remove(pdf_filename_tmp)
                except Exception as e:
                    print(f"[WARN] No se pudo eliminar archivo temporal: {e}")
            return None

# ---------------------------
# Funciones de flujo principal
# ---------------------------
def obtener_controlador_lupa(tipo, page):
    controladores = {
        'suprema': ControladorLupaSuprema,
        'apelaciones': ControladorLupaApelacionesPrincipal,
        'apelaciones_principal': ControladorLupaApelacionesPrincipal,
        'civil': ControladorLupaCivil,
        'cobranza': ControladorLupaCobranza
    }
    controlador_clase = controladores.get(tipo)
    if not controlador_clase:
        raise ValueError(f"Tipo de lupa '{tipo}' no reconocido")
    return controlador_clase(page)

def lupa(page, config):
    controlador = obtener_controlador_lupa(config['tipo'], page)
    return controlador.manejar(config['tab_name'])

def navigate_mis_causas_tabs(page):
    visited_tabs = set()
    
    for tab_name in MIS_CAUSAS_TABS:
        if tab_name in visited_tabs:
            continue
            
        try:
            if tab_name == "Corte Apelaciones":
                page.reload()
                random_sleep(3, 5)
                navigate_to_mis_causas(page)
            
            cerrar_modales_abiertos(page)
            random_sleep(3, 5)
            
            page.click(f"a:has-text('{tab_name}')")
            visited_tabs.add(tab_name)
            random_sleep(2, 4)
            
            tipo_lupa = TIPO_LUPA_MAP.get(tab_name)
            if tipo_lupa:
                lupa(page, {'tipo': tipo_lupa, 'tab_name': tab_name})
                random_sleep(3, 5)
                cerrar_modales_abiertos(page)
                
        except Exception as e:
            logging.error(f"Error en pestaña '{tab_name}': {str(e)}")
    
    logging.info("Finalizada navegación por pestañas")

def automatizar_poder_judicial(page, username, password):
    MOVIMIENTOS_GLOBALES.clear()
    
    try:
        page.goto(BASE_URL_PJUD)
        page.click("button:has-text('Todos los servicios')")
        page.click("a:has-text('Clave Única')")
        
        if login(page, username, password) and navigate_to_mis_causas(page):
            navigate_mis_causas_tabs(page)
            
            # Envío de correo
            if MOVIMIENTOS_GLOBALES:
                asunto = f"Nuevos movimientos en el Poder Judicial"
                enviar_correo(MOVIMIENTOS_GLOBALES, asunto)
            else:
                enviar_correo(asunto="Sin movimientos nuevos")
                
            return True
        return False
    except Exception as e:
        logging.error(f"Error en automatización: {str(e)}")
        return False

# ---------------------------
# Funciones de correo
# ---------------------------

def construir_cuerpo_html(movimientos, imagenes_cid=None):
    # Versión simplificada y corregida
    if not movimientos:
        return """<html><body><p>No se encontraron movimientos nuevos.</p></body></html>"""

    html = """
    <html>
    <head>
        <style>
            body { font-family: Arial, sans-serif; }
            .movimiento { border: 1px solid #ddd; padding: 15px; margin-bottom: 20px; border-radius: 5px; }
            .movimiento h3 { color: #2c3e50; border-bottom: 1px solid #eee; padding-bottom: 10px; }
            .info-item { margin: 5px 0; }
        </style>
    </head>
    <body>
        <p>Se han detectado nuevos movimientos:</p>
    """

    for mov in movimientos:
        # Obtener identificador limpio
        identificador = limpiar_identificador(mov.rol or mov.rit or mov.libro or "")
        
        html += f"""
        <div class="movimiento">
            <h3>{mov.caratulado}</h3>
            <div class="info-item"><strong>Causa:</strong> {identificador}</div>
            <div class="info-item"><strong>Tribunal:</strong> {mov.tribunal or 'No disponible'}</div>
            <div class="info-item"><strong>Fecha:</strong> {mov.fecha}</div>
            <div class="info-item"><strong>Documento:</strong> {os.path.basename(mov.pdf_path) if mov.pdf_path else 'Sin PDF'}</div>
        """

        # Añadir preview si existe
        if mov.pdf_path and imagenes_cid:
            preview_path = mov.pdf_path.replace('.pdf', '_preview.png')
            cid = imagenes_cid.get(preview_path)
            if cid:
                html += f'<div style="margin-top:10px;"><img src="cid:{cid}" style="max-width:100%;"></div>'
        
        html += "</div>"
    
    html += "</body></html>"
    return html

def enviar_correo(movimientos=None, asunto="Notificación de Sistema de Poder Judicial"):
    try:
        if not all([EMAIL_SENDER, EMAIL_PASSWORD, EMAIL_RECIPIENTS]):
            logging.error("Credenciales de correo incompletas")
            return False

        msg = MIMEMultipart()
        msg['From'] = EMAIL_SENDER
        msg['To'] = ", ".join(EMAIL_RECIPIENTS)
        msg['Subject'] = asunto

        # Manejo de CID para imágenes
        imagenes_cid = {}
        
        # Adjuntar archivos y generar CID para previews
        if movimientos:
            for movimiento in movimientos:
                # Adjuntar PDF principal
                if movimiento.pdf_path and os.path.exists(movimiento.pdf_path):
                    with open(movimiento.pdf_path, 'rb') as f:
                        part = MIMEApplication(f.read(), Name=os.path.basename(movimiento.pdf_path))
                        part['Content-Disposition'] = f'attachment; filename="{os.path.basename(movimiento.pdf_path)}"'
                        msg.attach(part)
                    
                    # Generar y adjuntar preview
                    preview_path = movimiento.pdf_path.replace('.pdf', '_preview.png')
                    if os.path.exists(preview_path):
                        cid = str(uuid.uuid4())
                        imagenes_cid[preview_path] = cid
                        with open(preview_path, 'rb') as img:
                            img_part = MIMEImage(img.read())
                            img_part.add_header('Content-ID', f'<{cid}>')
                            msg.attach(img_part)

        # Construir cuerpo HTML
        html_cuerpo = construir_cuerpo_html(movimientos, imagenes_cid)
        msg.attach(MIMEText(html_cuerpo, 'html'))

        # Envío con reintentos
        for intento in range(3):
            try:
                with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
                    server.starttls()
                    server.login(EMAIL_SENDER, EMAIL_PASSWORD)
                    server.send_message(msg)
                logging.info("Correo enviado exitosamente")
                return True
            except Exception as e:
                logging.warning(f"Error enviando correo (intento {intento+1}): {str(e)}")
                time.sleep(5)
        
        logging.error("Fallo al enviar correo después de 3 intentos")
        return False

    except Exception as e:
        logging.error(f"Error crítico en envío de correo: {str(e)}")
        return False
# ---------------------------
# Función principal
# ---------------------------
def main():
    if datetime.datetime.now().weekday() >= 5:
        logging.info("Fin de semana - sin ejecución")
        return

    USERNAME = os.getenv("RUT")
    PASSWORD = os.getenv("CLAVE")
    
    if not all([USERNAME, PASSWORD]):
        logging.error("Faltan credenciales en .env")
        return

    playwright, browser, page = None, None, None
    try:
        playwright, browser, page = setup_browser()
        automatizar_poder_judicial(page, USERNAME, PASSWORD)
    except Exception as e:
        logging.error(f"Error principal: {str(e)}")
    finally:
        if browser:
            browser.close()
        if playwright:
            playwright.stop()

if __name__ == "__main__":
    main()