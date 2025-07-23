import time, random, os, re, smtplib, logging, datetime
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

#----------------------------------------------------
#Script sin breaks, con fecha dinamica, headless True
#----------------------------------------------------

#Carga del env  
dotenv_path = Path(__file__).parent / '.env'
load_dotenv(dotenv_path=dotenv_path, override=True)

# Configuración del logging de errores
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('email_sender.log'),
        logging.StreamHandler()
    ]
)

# Variables globales para correo
EMAIL_SENDER = os.getenv("EMAIL_SENDER_TEST")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD_TEST")
EMAIL_RECIPIENTS = os.getenv("EMAIL_RECIPIENTS_TEST", "").split(",")
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587

# URL base de PJUD
BASE_URL_PJUD = os.getenv("BASE_URL_PJUD")

# Lista global para almacenar todos los movimientos nuevos
MOVIMIENTOS_GLOBALES = []

# Listas y diccionarios para la navegación en PJUD
MIS_CAUSAS_TABS = ["Corte Suprema", "Corte Apelaciones", 
                   "Civil", 
                   #"Laboral", "Penal", 
                   "Cobranza", 
                   #"Familia", "Disciplinario"
                   ]

# Diccionario de funciones JavaScript por pestaña
TAB_FUNCTIONS = {
    "Corte Suprema": "buscSup",
    "Corte Apelaciones": "buscApe",
    "Civil": "buscCiv",
    #"Laboral": "buscLab",
    #"Penal": "buscPen",
    "Cobranza": "buscCob",
    #"Familia": "buscFam"
}

# Lista de user agents
USER_AGENTS = [
    # Navegadores de escritorio
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.6367.78 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.6367.78 Safari/537.36",
    # Navegadores móviles
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 12; SM-G991B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.6367.78 Mobile Safari/537.36"
]

#Devuelve la fecha actual en formato dd/mm/yyyy
def obtener_fecha_actual_str():
    return datetime.datetime.now().strftime("%d/%m/%Y")

class MovimientoPJUD:
    def __init__(self, folio, seccion, caratulado, fecha, tribunal=None, corte=None, libro=None, rit=None, rol=None, pdf_path=None, pdf_paths=None, cuaderno=None, archivos_apelaciones=None, historia_causa_cuaderno=None):
        self.folio = folio
        self.seccion = seccion
        self.caratulado = caratulado
        self.tribunal = tribunal
        self.corte = corte
        self.fecha = fecha
        self.libro = libro
        self.rit = rit
        self.rol = rol
        # Mantener compatibilidad con pdf_path para casos antiguos, pero priorizar pdf_paths
        if pdf_paths:
            self.pdf_paths = pdf_paths
        elif pdf_path:
            self.pdf_paths = [pdf_path]
        else:
            self.pdf_paths = []
        self.cuaderno = cuaderno
        self.archivos_apelaciones = archivos_apelaciones or []  # Lista de archivos de apelaciones para corte suprema
        self.historia_causa_cuaderno = historia_causa_cuaderno 
    
    @property
    def pdf_path(self):
        """Mantener compatibilidad con código existente - devuelve el primer PDF"""
        return self.pdf_paths[0] if self.pdf_paths else None
    
    def tiene_pdf(self):
        return len(self.pdf_paths) > 0 and all(os.path.exists(path) for path in self.pdf_paths)
    
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
            'pdf_path': self.pdf_path,  # Mantener compatibilidad
            'pdf_paths': self.pdf_paths,
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
        # Devuelve el primer identificador disponible
        return self.rol or self.rit or self.libro

# Función para agregar un movimiento sin duplicar
def agregar_movimiento_sin_duplicar(movimiento):
    if not any(m == movimiento for m in MOVIMIENTOS_GLOBALES):
        MOVIMIENTOS_GLOBALES.append(movimiento)
        return True
    return False

#Configura y retorna un navegador con Playwright
def setup_browser():

    playwright = sync_playwright().start()
    
    # Seleccionar un user agent aleatorio
    selected_user_agent = random.choice(USER_AGENTS)
    print(f"User-Agent seleccionado: {selected_user_agent}")
    
    browser = playwright.chromium.launch(
        headless=True,  # True = sin interfaz gráfica
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
    
    # Crear el contexto con las configuraciones básicas
    context = browser.new_context(
        viewport={'width': 1366, 'height': 768},
        user_agent=selected_user_agent,
        locale='es-ES',
        timezone_id='America/Santiago',
        geolocation={'latitude': -33.4489, 'longitude': -70.6693},  # Santiago, Chile
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
    
    # Configurar el contexto para evitar la detección de automatización
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
    
    # Crear la página
    page = context.new_page()
    
    # Configurar timeouts
    page.set_default_timeout(30000)  # 30 segundos
    page.set_default_navigation_timeout(30000)
    
    return playwright, browser, page

#Espera un tiempo aleatorio entre min_seconds y max_seconds
def random_sleep(min_seconds=1, max_seconds=3):
    time.sleep(random.uniform(min_seconds, max_seconds))

#Simula varios comportamientos humanos aleatorios
def simulate_human_behavior(page):
    # Scroll aleatorio
    if random.random() < 0.3:  # 30% de probabilidad
        page.mouse.wheel(0, random.randint(100, 500))
        random_sleep(0.5, 1.5)
    
    # Movimiento del mouse aleatorio
    if random.random() < 0.2:  # 20% de probabilidad
        x = random.randint(100, 800)
        y = random.randint(100, 600)
        page.mouse.move(x, y)
        random_sleep(0.5, 1.5)

#Realiza el proceso de login
def login(page, username, password):
    try:
        print("Esperando página de Clave Única...")
        random_sleep(2, 4)
        
        # Simular comportamiento humano antes de interactuar
        simulate_human_behavior(page)

        print("Ingresando usuario...")
        page.fill('#uname', username)
        
        random_sleep(1, 2)
        
        print("Ingresando contraseña...")
        page.fill('#pword', password)
        
        random_sleep(1, 2)
        
        # Simular la pulsación de Enter para enviar el formulario
        page.keyboard.press('Enter')
        page.keyboard.press('Enter')
        
        # Simular comportamiento humano después del login
        random_sleep(2, 4)
        simulate_human_behavior(page)
        
        # Verificar que el login fue exitoso
        print("Verificando inicio de sesión...")
        page.wait_for_selector('text=Oficina Judicial Virtual', timeout=30000)
        
        print("Inicio de sesión exitoso!")
        return True
        
    except Exception as e:
        print(f"Error durante el proceso de login: {str(e)}") 
        return False

#Navega a la sección Mis Causas
def navigate_to_mis_causas(page):
    try:
        print("Navegando a 'Mis Causas'...")
        
        # Intentar hacer clic mediante JavaScript
        try:
            page.evaluate("misCausas();")
            print("Navegación a 'Mis Causas' mediante JS exitosa!")
        except Exception as js_error:
            print(f"Error al ejecutar JavaScript: {str(js_error)}")
            
            # Intento alternativo haciendo clic directamente en el elemento
            try:
                page.click("a:has-text('Mis Causas')")
                print("Navegación a 'Mis Causas' mediante clic directo exitosa!")
            except Exception as click_error:
                print(f"Error al hacer clic directo: {str(click_error)}")
                return False
        
        # Dar tiempo para que cargue la página
        random_sleep(1, 4)
        
        return True
        
    except Exception as e:
        print(f"Error al navegar a 'Mis Causas': {str(e)}")
        return False

#Descarga un PDF desde una URL directa usando las cookies de sesión
def descargar_pdf_directo(pdf_url, pdf_filename, page):
    try:
        # Verificar si el archivo ya existe
        if os.path.exists(pdf_filename):
            print(f"[INFO] El archivo {pdf_filename} ya existe. No se descargará nuevamente.")
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
        response = page.context.request.get(
            pdf_url,
            headers=headers
        )
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
    
#Elimina caracteres no válidos para nombres de archivo en Windows
def limpiar_nombre_archivo(nombre):
    """Elimina caracteres no válidos para nombres de archivo en Windows."""
    return re.sub(r'[<>:"/\\|?*\n\r\t]', '', nombre)

#Extrae un resumen del PDF (primeras 15 palabras del primer texto encontrado)
def extraer_resumen_pdf(pdf_path):
    try:
        with open(pdf_path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            if len(reader.pages) > 0:
                text = reader.pages[0].extract_text()
                if text:
                    # Elimina advertencias de firma electrónica y URLs
                    lineas = text.strip().splitlines()
                    lineas_utiles = []
                    for linea in lineas:
                        if (
                            "firma electrónica" in linea.lower()
                            or "verificadoc.pjud.cl" in linea.lower()
                            or "horaoficial.cl" in linea.lower()
                            or "puede ser validado" in linea.lower()
                            or "establecido en chile" in linea.lower()
                            or "para más información" in linea.lower()
                        ):
                            continue
                        if linea.strip():
                            lineas_utiles.append(linea.strip())
                    # Toma las primeras 15 palabras de las primeras líneas útiles
                    resumen = " ".join(" ".join(lineas_utiles).split()[:15])
                    return resumen if resumen else "sin_resumen"
        return "sin_resumen"
    except Exception as e:
        print(f"[ERROR] No se pudo extraer resumen del PDF: {e}")
        return "sin_resumen"
    
#genera un screenshot de la primera página del PDF  
def generar_preview_pdf(pdf_path, preview_path, width=400):
    try:
        images = convert_from_path(pdf_path, first_page=1, last_page=1)
        if images:
            img = images[0]
            w, h = img.size
            # Recorta
            crop_height = int(h * 0.5 * 0.7)
            upper_part = img.crop((0, 0, w, crop_height))
            # Redimensiona manteniendo el aspecto correcto
            aspect_ratio = crop_height / w
            new_height = int(width * aspect_ratio)
            resized = upper_part.resize((width, new_height), Image.LANCZOS)
            resized.save(preview_path, 'PNG')
            print(f"[INFO] Vista previa guardada en: {preview_path}")
        else:
            print(f"[WARN] No se pudo generar la vista previa para {pdf_path}")
    except Exception as e:
        print(f"[ERROR] Error generando preview: {e}")
        
        
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
                pagina_selector = f'.pagination .page-link[onclick^="pagina({pagina},"]'
                print(f"  Buscando selector de paginación: {pagina_selector}")
                try:
                    paginadores = page.query_selector_all(pagina_selector)
                    clicked = False
                    for pag in paginadores:
                        try:
                            classes = pag.get_attribute("class") or ""
                            # Verifica visibilidad real y que no sea el actual ni deshabilitado
                            style = pag.evaluate("el => window.getComputedStyle(el).display")
                            if pag.is_visible() and style != "none" and "disabled" not in classes and "active" not in classes:
                                pag.click()
                                clicked = True
                                print(f"  Click en paginador: {pagina_selector}")
                                random_sleep(1, 2)
                                page.wait_for_load_state("networkidle")
                                break
                        except Exception:
                            continue
                    if not clicked:
                        print(f"  No se encontró un paginador visible y habilitado para la página {pagina}")
                        continue
                except Exception as e:
                    print(f"  No se pudo hacer click en paginador: {e}")
                    continue
            random_sleep(0.5, 1.5)  # Pequeña pausa para asegurar carga
            yield pagina

        print("  Paginación completada")

    except Exception as e:
        print(f"  Error en paginación: {str(e)}")
        yield 1

#Lupa se refiere a el icon de lupa para abrir cada causa 
#esta es la clase base o general para los controladores de lupas
class ControladorLupa:
    def __init__(self, page):
        self.page = page
        self.config = self.obtener_config()
    
    def obtener_config(self):
        raise NotImplementedError

    def _obtener_lupas(self):
        print("  Buscando todas las lupas en la tabla...")
        lupas = self.page.query_selector_all(self.config['lupa_selector'])
        print(f"  Se encontraron {len(lupas)} lupas.")
        return lupas

    def manejar(self, tab_name):
        try:
            print(f"  Procesando lupa tipo '{self.__class__.__name__}' en pestaña '{tab_name}'...")
            for pagina in manejar_paginacion(self.page, tab_name):
                
                lupas = self._obtener_lupas()
                if not lupas:
                    print("  No se encontraron lupas en la pestaña.")
                    return False
                
                for idx, lupa_link in enumerate(lupas):
                    try:
                        fila = lupa_link.evaluate_handle('el => el.closest("tr")')
                        tds = fila.query_selector_all('td')
                        if len(tds) < 4:
                            continue
                        # Usar la columna 4 (índice 3) para el caratulado
                        caratulado = tds[3].inner_text().strip()
                        print(f"  Procesando lupa {idx+1} de {len(lupas)} (caratulado: {caratulado})")
                        
                        lupa_link.scroll_into_view_if_needed()
                        random_sleep(0.5, 1)
                        lupa_link.click()
                        random_sleep(1, 2)
                        self._verificar_modal()
                        self._verificar_tabla()
                        movimientos_nuevos = self._procesar_contenido(tab_name, caratulado)
                        self._cambiar_pestana_modal(caratulado, tab_name)
                        self._cerrar_modal()
                        
                        #break para procesar solo la primera lupa 
                        #break
                        
                    except Exception as e:
                        print(f"  Error procesando la lupa {idx+1}: {str(e)}")
                        self._manejar_error(e)
                        self._cerrar_modal()
                        continue
            return True
        except Exception as e:
            self._manejar_error(e)
            return False
    
    def _manejar_error(self, e):
        """Maneja errores durante el procesamiento"""
        print(f"  Error: {str(e)}")
        # Asegurarse de cerrar los modales si hay un error
        try:
            self._cerrar_ambos_modales()
        except Exception as close_error:
            print(f"  Error adicional al intentar cerrar modales: {str(close_error)}")
    
    def _cerrar_modal(self):
        try:
            print("  Cerrando modal principal...")
            # Intentar cerrar usando el botón de cerrar del modal
            close_button = self.page.query_selector(f"{self.config['modal_selector']} .close, {self.config['modal_selector']} button[data-dismiss='modal']")
            if close_button:
                close_button.click()
                # Esperar a que el modal desaparezca realmente
                self.page.wait_for_selector(self.config['modal_selector'], state='hidden', timeout=5000)
            else:
                # Si no hay botón, usar el método antiguo como fallback
                self._cerrar_ambos_modales()
                self.page.wait_for_selector(self.config['modal_selector'], state='hidden', timeout=5000)
        except Exception as e:
            print(f"  Error al cerrar modal: {str(e)}")
    
    def _verificar_modal(self):
        print(f"  Esperando que el modal esté visible...")
        self.page.wait_for_selector(self.config['modal_selector'], timeout=10000)
        random_sleep(1, 2)
        
        modal_visible = self.page.evaluate(f"""
            () => {{
                const modal = document.querySelector('{self.config['modal_selector']}');
                if (!modal) return false;
                
                const style = window.getComputedStyle(modal);
                if (style.display === 'none' || style.visibility === 'hidden') return false;
                
                const title = modal.querySelector('.modal-title');
                return title && title.textContent.includes('{self.config['modal_title']}');
            }}
        """)
        
        if not modal_visible:
            print(f"  Modal no está visible o no tiene el título esperado")
            return False
            
        print(f"  Modal encontrado y verificado")
        return True
    
    def _verificar_tabla(self):
        if not self.config.get('table_selector'):
            return True
            
        try:
            self.page.wait_for_selector(self.config['table_selector'], timeout=10000)
            
            if self.config.get('expected_headers'):
                table_structure = self.page.evaluate(f"""
                    () => {{
                        const table = document.querySelector('{self.config['table_selector']}');
                        if (!table) return false;
                        
                        const headers = Array.from(table.querySelectorAll('th')).map(th => th.textContent.trim());
                        const expectedHeaders = {self.config['expected_headers']};
                        
                        const rows = table.querySelectorAll('tbody tr');
                        return headers.length > 0 && rows.length > 0;
                    }}
                """)
                
                if not table_structure:
                    print(f"  Tabla encontrada pero no tiene la estructura esperada")
                    return False
                    
                print(f"  Tabla encontrada y verificada")
            return True
        except Exception as table_error:
            print(f"  Error esperando la tabla: {str(table_error)}")
            return False
    
    def _procesar_contenido(self, tab_name, caratulado):
        try:
            print(f"[INFO] Verificando movimientos nuevos en pestaña '{tab_name}'...")
            self.page.wait_for_selector("table.table-titulos", timeout=10000)
            panel = self.page.query_selector("table.table-titulos")
            numero_causa = None
            if panel:
                panel.scroll_into_view_if_needed()
                random_sleep(1, 2)
                try:
                    libro_td = panel.query_selector("td:has-text('libro')")
                    if libro_td:
                        libro_text = libro_td.inner_text()
                        print(f"[INFO] Texto completo del libro extraído: {libro_text}")
                        
                        #Modificacion para nombre pdf
                        libro_pdf = libro_text.replace(f"Libro :", "").strip().replace("/", "").replace("-", "") 

                        #modificacion para titulo correo
                        libro_titulo = libro_text.replace(f"Libro :", "").strip().replace("/", "-")

                    fecha_causa = panel.query_selector("td:has-text('Fecha')").inner_text().split(":")[1].strip()
                except Exception as e:
                    print(f"[WARN] No se pudo extraer toda la información del panel: {str(e)}")
            else:
                print("[WARN] No se encontró el panel de información")
            self.page.wait_for_selector("table.table-bordered", timeout=10000)
            movimientos = self.page.query_selector_all("table.table-bordered tbody tr")
            print(f"[INFO] Se encontraron {len(movimientos)} movimientos")
            movimientos_nuevos = False
            for movimiento in movimientos:
                try:
                    folio = movimiento.query_selector("td:nth-child(1)").inner_text().strip()
                    fecha_tramite_str = movimiento.query_selector("td:nth-child(5)").inner_text().strip()
                    fecha_tramite_pdf = fecha_tramite_str[6:10] + fecha_tramite_str[3:5] + fecha_tramite_str[0:2]
                    
                    if fecha_tramite_str == obtener_fecha_actual_str():
                        movimientos_nuevos = True
                        carpeta_general = tab_name.replace(' ', '_')
                        carpeta_caratulado = f"{carpeta_general}/{caratulado}"
                        if not os.path.exists(carpeta_caratulado):
                            print(f"[INFO] Creando carpeta: {carpeta_caratulado}")
                            os.makedirs(carpeta_caratulado)
                        else:
                            print(f"[INFO] La carpeta {carpeta_caratulado} ya existe.")
                        detalle_panel_path = f"{carpeta_caratulado}/Detalle_causa.png"
                        if panel:
                            # Verificar si el archivo ya existe
                            if os.path.exists(detalle_panel_path):
                                print(f"[INFO] El archivo {detalle_panel_path} ya existe. No se generará nuevamente.")
                            else:
                                panel.screenshot(path=detalle_panel_path)
                                print(f"[INFO] Captura del panel de información guardada: {detalle_panel_path}")
                        pdf_forms = movimiento.query_selector_all("form[name='frmPdf']")
                        pdf_paths = []
                        if pdf_forms:
                            print(f"[INFO] Se encontraron {len(pdf_forms)} documentos para el folio {folio}")
                            for doc_idx, pdf_form in enumerate(pdf_forms):
                                token = pdf_form.query_selector("input[name='valorFile']").get_attribute("value")
                                causa_str = f"Causa_{numero_causa}_" if numero_causa else ""
                                
                                # Agregar sufijo para múltiples documentos
                                doc_suffix = f"_doc{doc_idx + 1}" if len(pdf_forms) > 1 else ""
                                # Nombre temporal antes de tener el resumen
                                pdf_filename_tmp = f"{carpeta_caratulado}/{fecha_tramite_pdf} {libro_pdf} temp.pdf"
                                preview_path = pdf_filename_tmp.replace('.pdf', '_preview.png')

                                if token:
                                    base_url = "https://oficinajudicialvirtual.pjud.cl/misCausas/suprema/documentos/docCausaSuprema.php?valorFile="
                                    original_url = base_url + token
                                    try:
                                        pdf_descargado = descargar_pdf_directo(original_url, pdf_filename_tmp, self.page)
                                        if pdf_descargado:                                        
                                            resumen_pdf = extraer_resumen_pdf(pdf_filename_tmp)
                                            resumen_pdf_limpio = limpiar_nombre_archivo(resumen_pdf)
                                            # Nombre final
                                            pdf_filename = f"{carpeta_caratulado}/{fecha_tramite_pdf} {libro_pdf}{doc_suffix} {resumen_pdf_limpio}.pdf"
                                            # Renombrar el archivo temporal al nombre final
                                            try:
                                                os.rename(pdf_filename_tmp, pdf_filename)
                                            except Exception as e:
                                                print(f"[WARN] No se pudo renombrar el archivo temporal: {pdf_filename_tmp} -> {pdf_filename} - {e}")
                                            finally:
                                                if os.path.exists(pdf_filename_tmp):
                                                    try:
                                                        os.remove(pdf_filename_tmp)
                                                        print(f"[INFO] Archivo temporal eliminado: {pdf_filename_tmp}")
                                                    except Exception as e:
                                                        print(f"[WARN] No se pudo eliminar el archivo temporal: {pdf_filename_tmp} - {e}")                                        
                                            pdf_paths.append(pdf_filename)
                                            preview_path = pdf_filename.replace('.pdf', '_preview.png')

                                            # Generar preview si no existe
                                            if not os.path.exists(preview_path):
                                                print(f"[INFO] Generando vista previa del PDF para {pdf_filename}...")
                                                generar_preview_pdf(pdf_filename, preview_path)
                                        else:
                                            print(f"[ERROR] No se pudo descargar el PDF {doc_idx + 1} para folio {folio}")
                                    except Exception as e:
                                        print(f"[ERROR] Error descargando PDF {doc_idx + 1} para folio {folio}, causa {numero_causa}: {e}")
                        else:
                            print(f"[WARN] No hay PDF disponible para el movimiento {folio}")
                        
                        # Usar el primer PDF como referencia principal para compatibilidad
                        pdf_path = pdf_paths[0] if pdf_paths else None
                                                
                        # Crear y agregar el movimiento a la lista global usando la nueva función
                        movimiento_pjud = MovimientoPJUD(
                            folio=folio,
                            seccion=tab_name,
                            caratulado=caratulado,
                            libro=libro_td,
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
        except Exception as e:
            print(f"[ERROR] Error al verificar movimientos nuevos: {str(e)}")
            return False

    #Expediente Corte Apelaciones, pestaña dentro de corte suprema
    def _cambiar_pestana_modal(self, caratulado, tab_name):
        # Por defecto, no hace nada. Las subclases pueden sobrescribir si lo necesitan.
        pass

    #Cierra correctamente ambos modales: Detalle Causa Apelaciones y Detalle Causa Suprema
    def _cerrar_ambos_modales(self):
        try:
            print("  Cerrando todos los modales abiertos...")
            
            #Cierre directo de todos los modales mediante manipulación del DOM
            self.page.evaluate("""
                () => {
                    // Asegurar que no queden modales visibles
                    document.querySelectorAll('.modal.in, .modal[style*="display: block"]').forEach(modal => {
                        modal.style.display = 'none';
                        modal.classList.remove('in');
                    });
                    
                    // Asegurar que el body no tenga la clase modal-open
                    document.body.classList.remove('modal-open');
                    
                    // Eliminar todos los backdrops
                    document.querySelectorAll('.modal-backdrop').forEach(backdrop => {
                        if (backdrop.parentNode) {
                            backdrop.parentNode.removeChild(backdrop);
                        }
                    });
                    
                    return true;
                }
            """)
            
            # Verificar el estado de los modales después de la limpieza
            any_modal_open = self.page.evaluate("""
                () => {
                    return !!document.querySelector('.modal.in, .modal[style*="display: block"]') || 
                           !!document.querySelector('.modal-backdrop') ||
                           document.body.classList.contains('modal-open');
                }
            """)
            
            if not any_modal_open:
                print("  Todos los modales cerrados correctamente")
            else:
                print("  ALERTA: Puede que algunos modales sigan abiertos")
                
            random_sleep(1, 2)
                
        except Exception as e:
            print(f"  Error al cerrar los modales: {str(e)}")

    #Verifica los movimientos en el modal de Apelaciones y guarda los resultados
    def _verificar_movimientos_apelaciones(self, subcarpeta):        
        try:
            print(f"  Verificando movimientos en modal de Apelaciones...")
            
            # Obtener el número de causa
            numero_causa = None
            try:
                panel_titulos = self.page.query_selector("#modalDetalleApelaciones table.table-titulos")
                if panel_titulos:
                    libro_td = panel_titulos.query_selector("td:has-text('libro')")
                    if libro_td:
                        libro_text = libro_td.inner_text()
                        print(f"  Texto completo del libro extraído: {libro_text}")
            except Exception as e:
                print(f"  No se pudo extraer el número de causa: {str(e)}")
            
            # Tomar captura de la sección de información de la causa
            archivos_apelaciones = []
            try:
                # Identificar la sección superior del modal con la información general de la causa
                info_panel = self.page.query_selector("#modalDetalleApelaciones .modal-body > div:first-child")
                
                # Si no se encuentra con ese selector, intentar con otro selector más específico
                if not info_panel:
                    info_panel = self.page.query_selector("#modalDetalleApelaciones table.table-titulos")
                
                if info_panel:
                    # Asegurar que exista la carpeta
                    if not os.path.exists(subcarpeta):
                        os.makedirs(subcarpeta)
                    
                    # Hacer scroll para asegurar que el elemento es visible
                    info_panel.scroll_into_view_if_needed()
                    random_sleep(0.5, 1)
                    
                    # Guardar la captura de la sección de información
                    panel_screenshot_path = f"{subcarpeta}/Detalle_Causa_Apelaciones.png"
                    info_panel.screenshot(path=panel_screenshot_path)
                    archivos_apelaciones.append(panel_screenshot_path)
                    print(f"  Captura de la información de la causa guardada en: {panel_screenshot_path}")
                else:
                    print("  No se pudo encontrar la sección de información para capturar")
            except Exception as capture_error:
                print(f"  Error al capturar la sección de información: {str(capture_error)}")

            # Asegurarse de que el tab "movimientosApe" esté activo
            print("  Activando la pestaña de movimientos...")
            try:
                # Verificar si ya hay alguna pestaña activa
                active_tab = self.page.query_selector("#modalDetalleApelaciones .tab-pane.active")
                if active_tab:
                    active_id = self.page.evaluate("el => el.id", active_tab)
                    print(f"  Pestaña activa actualmente: {active_id}")
                
                # Hacer clic en la pestaña de movimientos para activarla
                self.page.evaluate("""
                    () => {
                        // Buscar el enlace que apunta al tab movimientosApe
                        const tabLink = document.querySelector('#modalDetalleApelaciones .nav-tabs a[href="#movimientosApe"]');
                        if (tabLink) {
                            console.log('Enlace a pestaña encontrado, haciendo clic...');
                            tabLink.click();
                            return true;
                        } else {
                            console.log('No se encontró el enlace a la pestaña');
                            return false;
                        }
                    }
                """)
                
                # Esperar a que la pestaña esté activa
                self.page.wait_for_selector("#modalDetalleApelaciones #movimientosApe.active", timeout=5000)
                print("  Pestaña de movimientos activada correctamente")
                
                # Pequeña pausa para asegurar que todo cargue correctamente
                random_sleep(1, 2)
            except Exception as tab_error:
                print(f"  Error al activar la pestaña de movimientos: {str(tab_error)}")
                # Si hay un error, intentamos continuar 
            
            # Esperar a que la tabla de movimientos esté visible usando el nuevo selector
            print("  Esperando por la tabla de movimientos en el tab activo...")
            self.page.wait_for_selector("#movimientosApe table.table-bordered", timeout=10000)
            
            # Fecha específica para la verificación de movimientos de apelaciones
            fecha_actual_str = obtener_fecha_actual_str()
            
            print(f"  Verificando movimientos del día: {fecha_actual_str}")
            
            # Obtener todos los movimientos usando el selector correcto para la pestaña activa
            movimientos = self.page.query_selector_all("#movimientosApe table.table-bordered tbody tr")
            print(f"  Se encontraron {len(movimientos)} movimientos")
            
            # Revisar cada movimiento
            for movimiento in movimientos:
                try:
                    folio = movimiento.query_selector("td:nth-child(1)").inner_text().strip()
                    fecha_tramite_str = movimiento.query_selector("td:nth-child(6)").inner_text().strip()  
                    
                    # Verificar si el movimiento es de la fecha especificada
                    if fecha_tramite_str == fecha_actual_str:
                        print(f"  Movimiento nuevo encontrado - Folio: {folio}, Fecha: {fecha_tramite_str}")
                        
                        # Verificar si hay PDFs disponibles
                        pdf_forms = movimiento.query_selector_all("form[name='frmDoc']")
                        if pdf_forms:
                            print(f"  Se encontraron {len(pdf_forms)} documentos para el folio {folio}")
                            # Procesar cada formulario/documento
                            for doc_idx, pdf_form in enumerate(pdf_forms):
                                # Obtener el token para descargar el PDF 
                                token = pdf_form.query_selector("input[name='valorDoc']").get_attribute("value")
                                causa_str = f"Causa_{numero_causa}_" if numero_causa else ""
                                
                                # Agregar sufijo para múltiples documentos
                                doc_suffix = f"_doc{doc_idx + 1}" if len(pdf_forms) > 1 else ""
                                pdf_filename = f"{subcarpeta}/{causa_str}folio_{folio}_fecha_{fecha_tramite_str.replace('/', '_')}.pdf"
                                if len(pdf_forms) > 1:
                                    base_name, ext = os.path.splitext(pdf_filename)
                                    pdf_filename = f"{base_name}{doc_suffix}{ext}"
                                
                                preview_path = pdf_filename.replace('.pdf', '_preview.png')

                                # Construir la URL para descargar el PDF
                                if token:
                                    # URL para la descarga de PDF en Corte Apelaciones
                                    base_url = "https://oficinajudicialvirtual.pjud.cl/misCausas/apelaciones/documentos/docCausaApelaciones.php?valorDoc="
                                    original_url = base_url + token
                                    
                                    # Descargar el PDF
                                    print(f"  Descargando PDF de Apelaciones {doc_idx + 1}...")
                                    pdf_descargado = descargar_pdf_directo(original_url, pdf_filename, self.page)
                                    
                                    if pdf_descargado:
                                        archivos_apelaciones.append(pdf_filename)
                                        # Generar una vista previa del PDF (mitad superior, redimensionada)
                                        try:
                                            print(f"  Generando vista previa del PDF para {pdf_filename}...")
                                            generar_preview_pdf(pdf_filename, preview_path)
                                            if os.path.exists(preview_path):
                                                archivos_apelaciones.append(preview_path)
                                                print(f"  Vista previa guardada en: {preview_path}")
                                            else:
                                                print(f"  No se pudo generar la vista previa para {pdf_filename}")
                                        except Exception as prev_error:
                                            print(f"  Error al generar la vista previa del PDF: {str(prev_error)}")
                        else:
                            print(f"  No hay PDF disponible para el movimiento {folio}")
                except Exception as e:
                    print(f"  Error procesando movimiento de Apelaciones: {str(e)}")
                    continue
            
            return archivos_apelaciones
            
        except Exception as e:
            print(f"  Error al verificar movimientos en modal de Apelaciones: {str(e)}")
            return []

#Aqui se maneja la navegacion en la pestaña Corte Suprema de Mis Causas
class ControladorLupaSuprema(ControladorLupa):
    def obtener_config(self):
        return {
            'lupa_selector': "#dtaTableDetalleMisCauSup tbody tr td a[href*='modalDetalleMisCauSuprema']",
            'modal_selector': "#modalDetalleMisCauSuprema",
            'modal_title': "Detalle Causa",
            'table_selector': ".modal-content table.table-bordered",
            'expected_headers': ['Folio', 'Tipo', 'Descripción', 'Fecha', 'Documento'],
            'process_content': True
        }

# Controlador de lupas corte Suprema 
    def manejar(self, tab_name):
        try:
            print(f"  Procesando lupa tipo '{self.__class__.__name__}' en pestaña '{tab_name}'...")
            for pagina in manejar_paginacion(self.page, tab_name):
                lupas = self._obtener_lupas()
                if not lupas:
                    print("  No se encontraron lupas en la pestaña.")
                    return False
                
                for idx, lupa_link in enumerate(lupas):
                    try:
                        fila = lupa_link.evaluate_handle('el => el.closest("tr")')
                        tds = fila.query_selector_all('td')
                        if len(tds) < 3:
                            continue
                        caratulado = tds[2].inner_text().strip()
                        corte_text = tds[5].inner_text().strip() 
                        print(f"  Procesando lupa {idx+1} de {len(lupas)} (caratulado: {caratulado})")
                        
                        lupa_link.scroll_into_view_if_needed()
                        random_sleep(0.5, 1)
                        lupa_link.click()
                        random_sleep(1, 2)
                        self._verificar_modal()
                        self._verificar_tabla()
                        movimientos_nuevos = self._procesar_contenido_suprema(tab_name, caratulado, corte_text)
                        self._cerrar_modal()
                        
                        #break para procesar solo la primera lupa
                        #break
                        
                    except Exception as e:
                        print(f"  Error procesando la lupa {idx+1}: {str(e)}")
                        self._manejar_error(e)
                        self._cerrar_modal()
                        continue
            return True
        except Exception as e:
            self._manejar_error(e)
            return False

    def _procesar_contenido_suprema(self, tab_name, caratulado, corte=None):
        try:
            print(f"[INFO] Verificando movimientos nuevos en pestaña '{tab_name}'...")
            # Selector para obtener el panel completo de detalles de causas
            panel = self.page.query_selector("#modalDetalleMisCauSuprema .modal-body .panel.panel-default")
            numero_causa = None
            if panel:
                panel.scroll_into_view_if_needed()
                random_sleep(1, 2)
                try:
                    # Buscar el número de causa en el panel completo
                    libro_td = panel.query_selector("td:has-text('libro')")
                    if libro_td:
                        libro_text = libro_td.inner_text()
                        print(f"[INFO] Texto completo del libro extraído: {libro_text}")
                except Exception as e:
                    print(f"[WARN] No se pudo extraer el número de causa: {str(e)}")
            else:
                print("[WARN] No se encontró el panel de información")
            self.page.wait_for_selector("table.table-bordered", timeout=10000)
            movimientos = self.page.query_selector_all("table.table-bordered tbody tr")
            print(f"[INFO] Se encontraron {len(movimientos)} movimientos")
            movimientos_nuevos = False
            
            # Fecha específica para Corte Suprema
            fecha_objetivo = obtener_fecha_actual_str()
            print(f"[INFO] Buscando movimientos de la fecha: {fecha_objetivo}")
            
            for movimiento in movimientos:
                try:
                    tds = movimiento.query_selector_all('td')
                    if len(tds) < 5:
                        continue
                    folio_text = tds[0].inner_text().strip()
                    if not folio_text.isdigit():
                        continue
                    folio = folio_text
                    fecha_tramite_str = tds[4].inner_text().strip()
                    
                    # Solo procesar movimientos de la fecha objetivo
                    if fecha_tramite_str == fecha_objetivo:
                        print(f"[INFO] Movimiento encontrado - Folio: {folio}, Fecha: {fecha_tramite_str}")
                        movimientos_nuevos = True
                        carpeta_general = tab_name.replace(' ', '_')
                        carpeta_caratulado = f"{carpeta_general}/{caratulado}"
                        if not os.path.exists(carpeta_caratulado):
                            print(f"[INFO] Creando carpeta: {carpeta_caratulado}")
                            os.makedirs(carpeta_caratulado)
                        else:
                            print(f"[INFO] La carpeta {carpeta_caratulado} ya existe.")
                        # Modificar el formato del nombre del archivo para incluir el número de causa
                        detalle_panel_path = f"{carpeta_caratulado}/Detalle_causa_{numero_causa}.png" if numero_causa else f"{carpeta_caratulado}/Detalle_causa.png"
                        if panel:
                            # Verificar si el archivo ya existe
                            if os.path.exists(detalle_panel_path):
                                print(f"[INFO] El archivo {detalle_panel_path} ya existe. No se generará nuevamente.")
                            else:
                                try:
                                    # Hacer scroll al panel
                                    self.page.evaluate("""
                                        (element) => {
                                            element.scrollIntoView({ behavior: 'smooth', block: 'center' });
                                        }
                                    """, panel)
                                    random_sleep(1, 2)
                                    # Tomar la captura del panel completo
                                    panel.screenshot(path=detalle_panel_path)
                                    print(f"[INFO] Captura del panel de información guardada: {detalle_panel_path}")
                                except Exception as e:
                                    print(f"[WARN] No se pudo tomar la captura del panel: {str(e)}")
                        pdf_forms = movimiento.query_selector_all("form[name='frmPdf']")
                        pdf_paths = []
                        if pdf_forms:
                            print(f"[INFO] Se encontraron {len(pdf_forms)} documentos para el folio {folio}")
                            for doc_idx, pdf_form in enumerate(pdf_forms):
                                token = pdf_form.query_selector("input[name='valorFile']").get_attribute("value")
                                # Construir nombre base del archivo usando fecha y libro
                                fecha_tramite_pdf = fecha_tramite_str[6:10] + fecha_tramite_str[3:5] + fecha_tramite_str[0:2]
                                libro_pdf = libro_text.replace("Libro :", "").strip().replace("/", "").replace("-", "")
                                
                                # Agregar sufijo para múltiples documentos
                                doc_suffix = f"_doc{doc_idx + 1}" if len(pdf_forms) > 1 else ""
                                # Nombre temporal antes de tener el resumen
                                pdf_filename_tmp = f"{carpeta_caratulado}/{fecha_tramite_pdf} {libro_pdf}_temp.pdf"
                                preview_path = pdf_filename_tmp.replace('.pdf', '_preview.png')

                                if token:
                                    base_url = "https://oficinajudicialvirtual.pjud.cl/misCausas/suprema/documentos/docCausaSuprema.php?valorFile="
                                    original_url = base_url + token
                                    try:
                                        pdf_descargado = descargar_pdf_directo(original_url, pdf_filename_tmp, self.page)
                                        if pdf_descargado:
                                            resumen_pdf = extraer_resumen_pdf(pdf_filename_tmp)
                                            resumen_pdf_limpio = limpiar_nombre_archivo(resumen_pdf)
                                            pdf_filename = f"{carpeta_caratulado}/{fecha_tramite_pdf} {libro_pdf} {resumen_pdf_limpio}.pdf"
                                            # Si hay múltiples documentos, agregar sufijo al nombre final
                                            if len(pdf_forms) > 1:
                                                base_name, ext = os.path.splitext(pdf_filename)
                                                pdf_filename = f"{base_name}{doc_suffix}{ext}"
                                            try:
                                                os.rename(pdf_filename_tmp, pdf_filename)
                                            except Exception as e:
                                                print(f"[WARN] No se pudo renombrar el archivo temporal: {pdf_filename_tmp} -> {pdf_filename} - {e}")
                                            finally:
                                                if os.path.exists(pdf_filename_tmp):
                                                    try:
                                                        os.remove(pdf_filename_tmp)
                                                        print(f"[INFO] Archivo temporal eliminado: {pdf_filename_tmp}")
                                                    except Exception as e:
                                                        print(f"[WARN] No se pudo eliminar el archivo temporal: {pdf_filename_tmp} - {e}")
                                            pdf_paths.append(pdf_filename)
                                            preview_path = pdf_filename.replace('.pdf', '_preview.png')
                                            # Generar preview si no existe
                                            if not os.path.exists(preview_path):
                                                print(f"[INFO] Generando vista previa del PDF para {pdf_filename}...")
                                                generar_preview_pdf(pdf_filename, preview_path)
                                        else:
                                            print(f"[ERROR] No se pudo descargar el PDF {doc_idx + 1} para folio {folio}")
                                    except Exception as e:
                                        print(f"[ERROR] Error descargando PDF {doc_idx + 1} para folio {folio}, causa {numero_causa}: {e}")
                        else:
                            print(f"[WARN] No hay PDF disponible para el movimiento {folio}")
                        
                        # Usar el primer PDF como referencia principal para compatibilidad
                        pdf_path = pdf_paths[0] if pdf_paths else None
                        
                        # Crear y agregar el movimiento a la lista global
                        movimiento_pjud = MovimientoPJUD(
                            folio=folio,
                            seccion=tab_name,
                            caratulado=caratulado,
                            libro=libro_text,
                            fecha=fecha_tramite_str,
                            pdf_path=pdf_path,
                            corte=corte
                        )
                        if agregar_movimiento_sin_duplicar(movimiento_pjud):
                            print(f"[INFO] Movimiento agregado exitosamente al diccionario global")
                        else:
                            print(f"[INFO] El movimiento ya existía en el diccionario global")
                    else:
                        print(f"[INFO] Movimiento ignorado - Folio: {folio}, Fecha: {fecha_tramite_str} (no coincide con fecha objetivo)")
                except Exception as e:
                    print(f"[ERROR] Error procesando movimiento {folio if 'folio' in locals() else ''}: {str(e)}")
                    continue
            
            # Cambiar a la pestaña de Apelaciones
            #self._cambiar_pestana_modal(caratulado, tab_name)
            
            return movimientos_nuevos
        except Exception as e:
            print(f"[ERROR] Error al verificar movimientos nuevos: {str(e)}")
            return False

#Aqui se maneja la navegacion en la pestaña Corte Apelaciones de Mis Causas
class ControladorLupaApelacionesPrincipal(ControladorLupa):
    def obtener_config(self):
        return {
            'lupa_selector': "#dtaTableDetalleMisCauApe a[href*='modalDetalleMisCauApelaciones']",
            'modal_selector': "#modalDetalleMisCauApelaciones",
            'modal_title': "Detalle Causa",
            'table_selector': ".modal-content table.table-bordered",
            'expected_headers': ['Folio', 'Doc.', 'Anexo', 'Trámite', 'Descripción', 'Fecha', 'Sala', 'Estado', 'Georeferencia'],
            'process_content': True
        }

    def manejar(self, tab_name):
        try:
            print(f"  Procesando lupa tipo '{self.__class__.__name__}' en pestaña '{tab_name}'...")
            for pagina in manejar_paginacion(self.page, tab_name):
                lupas = self._obtener_lupas()
                if not lupas:
                    print("  No se encontraron lupas en la pestaña.")
                    return False
                
                for idx, lupa_link in enumerate(lupas):
                    try:
                        fila = lupa_link.evaluate_handle('el => el.closest("tr")')
                        tds = fila.query_selector_all('td')
                        if len(tds) < 4:
                            continue
                        # Usar la columna 4 (índice 3) para el caratulado
                        caratulado = tds[3].inner_text().strip()
                        #extraer corte
                        corte_text = tds[2].inner_text().replace("Corte:", "").strip()
                        print(f" Corte: {corte_text} ")
                        print(f"  Procesando lupa {idx+1} de {len(lupas)} (caratulado: {caratulado})")
                        
                        lupa_link.scroll_into_view_if_needed()
                        random_sleep(0.5, 1)
                        lupa_link.click()
                        random_sleep(1, 2)
                        self._verificar_modal()
                        self._verificar_tabla()
                        movimientos_nuevos = self._procesar_contenido(tab_name, caratulado,corte_text)
                        self._cerrar_modal()
                        
                        #break para procesar solo la primera lupa
                        #break
                        
                    except Exception as e:
                        print(f"  Error procesando la lupa {idx+1}: {str(e)}")
                        self._manejar_error(e)
                        self._cerrar_modal()
                        continue
            return True
        except Exception as e:
            self._manejar_error(e)
            return False

    def _procesar_contenido(self, tab_name, caratulado, corte=None):
        try:
            print(f"[INFO] Procesando movimientos en Corte Apelaciones (principal)...")
            
            modal_usable = self.page.evaluate(f"""
                () => {{
                    const modal = document.querySelector('{self.config["modal_selector"]}');
                    if (!modal) return false;
                    
                    // Verificar si hay contenido visible
                    const tables = modal.querySelectorAll('table');
                    if (!tables || tables.length === 0) return false;
                    
                    return true;
                }}
            """)
            
            if not modal_usable:
                print("[WARN] El modal parece estar en estado bloqueado o incompleto. Intentando recuperarlo...")
                return False
            
            # Asegurarse de que el tab-pane "movimientosApe" está activo
            print("[INFO] Verificando y activando el tab-pane de movimientos...")
            tab_activo = self.page.evaluate("""
                () => {
                    // Verificar si el tab movimientosApe ya está activo
                    const tabMovimientos = document.querySelector('#movimientosApe');
                    if (tabMovimientos && tabMovimientos.classList.contains('active')) {
                        return true;
                    }
                    
                    // Si no está activo, intentar activarlo
                    const tabLink = document.querySelector('a[href="#movimientosApe"]');
                    if (tabLink) {
                        tabLink.click();
                        return true;
                    }
                    
                    return false;
                }
            """)
            
            if not tab_activo:
                print("[WARN] No se pudo activar el tab-pane de movimientos")
                return False
            
            # Esperar  para asegurar que el tab-pane esté visible
            random_sleep(1, 2)
            
            # Selector para obtener el panel completo de detalles de causas
            panel = self.page.query_selector("#modalDetalleMisCauApelaciones .modal-body .panel.panel-default")
            numero_causa = None
            if panel:
                try:
                    panel.scroll_into_view_if_needed()
                    random_sleep(1, 2)
                                            # Extraer el número de causa del Libro
                    try:
                        libro_td = panel.query_selector("td:has-text('libro')")
                        if libro_td:
                            libro_text = libro_td.inner_text()
                            print(f"  Texto completo del libro extraído: {libro_text}")
                    except Exception as e:
                            print(f"  No se pudo extraer el número de causa: {str(e)}")
                except Exception as scroll_error:
                    print(f"[WARN] No se pudo hacer scroll al panel: {str(scroll_error)}")
                    return False
            else:
                print("[WARN] No se encontró el panel de información")
                
            try:
                self.page.wait_for_selector("#modalDetalleMisCauApelaciones #movimientosApe table.table-bordered", timeout=5000)
                movimientos = self.page.query_selector_all("#modalDetalleMisCauApelaciones #movimientosApe table.table-bordered tbody tr")
                print(f"[INFO] Se encontraron {len(movimientos)} movimientos")
            except Exception as table_error:
                print(f"[WARN] No se pudo encontrar la tabla de movimientos: {str(table_error)}")
                return False
                
            movimientos_nuevos = False
            for movimiento in movimientos:
                try:
                    folio = movimiento.query_selector("td:nth-child(1)").inner_text().strip()
                    fecha_tramite_str = movimiento.query_selector("td:nth-child(6)").inner_text().strip() 
                    if fecha_tramite_str == obtener_fecha_actual_str():
                        movimientos_nuevos = True
                        carpeta_general = tab_name.replace(' ', '_')
                        carpeta_caratulado = f"{carpeta_general}/{caratulado}"
                        if not os.path.exists(carpeta_caratulado):
                            print(f"[INFO] Creando carpeta: {carpeta_caratulado}")
                            os.makedirs(carpeta_caratulado)
                        else:
                            print(f"[INFO] La carpeta {carpeta_caratulado} ya existe.")
                        # Modificar el formato del nombre del archivo para incluir el número de causa
                        detalle_panel_path = f"{carpeta_caratulado}/Detalle_causa_{numero_causa}.png" if numero_causa else f"{carpeta_caratulado}/Detalle_causa.png"
                        if panel:
                            # Verificar si el archivo ya existe
                            if os.path.exists(detalle_panel_path):
                                print(f"[INFO] El archivo {detalle_panel_path} ya existe. No se generará nuevamente.")
                            else:
                                try:
                                    # Hacer scroll al panel
                                    self.page.evaluate("""
                                        (element) => {
                                            element.scrollIntoView({ behavior: 'smooth', block: 'center' });
                                        }
                                    """, panel)
                                    random_sleep(1, 2)
                                    # Tomar la captura del panel completo
                                    panel.screenshot(path=detalle_panel_path)
                                    print(f"[INFO] Captura del panel de información guardada: {detalle_panel_path}")
                                except Exception as e:
                                    print(f"[WARN] No se pudo tomar la captura del panel: {str(e)}")
                        pdf_forms = movimiento.query_selector_all("form[name='frmDoc']")
                        pdf_paths = []
                        if pdf_forms:
                            print(f"[INFO] Se encontraron {len(pdf_forms)} documentos para el folio {folio}")
                            for doc_idx, pdf_form in enumerate(pdf_forms):
                                token = pdf_form.query_selector("input[name='valorDoc']").get_attribute("value")
                                # Construir nombre base del archivo usando fecha y libro
                                fecha_tramite_pdf = fecha_tramite_str[6:10] + fecha_tramite_str[3:5] + fecha_tramite_str[0:2]
                                libro_pdf = libro_text.replace("Libro :", "").strip().replace("/", "").replace("-", "")
                                
                                # Agregar sufijo para múltiples documentos
                                doc_suffix = f"_doc{doc_idx + 1}" if len(pdf_forms) > 1 else ""
                                # Nombre temporal antes de tener el resumen
                                pdf_filename_tmp = f"{carpeta_caratulado}/{fecha_tramite_pdf} {libro_pdf}_temp.pdf"
                                preview_path = pdf_filename_tmp.replace('.pdf', '_preview.png')

                                if token:
                                    base_url = "https://oficinajudicialvirtual.pjud.cl/misCausas/apelaciones/documentos/docCausaApelaciones.php?valorDoc="
                                    original_url = base_url + token
                                    pdf_descargado = descargar_pdf_directo(original_url, pdf_filename_tmp, self.page)
                                    if pdf_descargado:
                                        resumen_pdf = extraer_resumen_pdf(pdf_filename_tmp)
                                        resumen_pdf_limpio = limpiar_nombre_archivo(resumen_pdf)
                                        pdf_filename = f"{carpeta_caratulado}/{fecha_tramite_pdf} {libro_pdf} {resumen_pdf_limpio}.pdf"
                                        # Si hay múltiples documentos, agregar sufijo al nombre final
                                        if len(pdf_forms) > 1:
                                            base_name, ext = os.path.splitext(pdf_filename)
                                            pdf_filename = f"{base_name}{doc_suffix}{ext}"
                                        try:
                                            os.rename(pdf_filename_tmp, pdf_filename)
                                        except Exception as e:
                                            print(f"[WARN] No se pudo renombrar el archivo temporal: {pdf_filename_tmp} -> {pdf_filename} - {e}")
                                        finally:
                                            if os.path.exists(pdf_filename_tmp):
                                                try:
                                                    os.remove(pdf_filename_tmp)
                                                    print(f"[INFO] Archivo temporal eliminado: {pdf_filename_tmp}")
                                                except Exception as e:
                                                    print(f"[WARN] No se pudo eliminar el archivo temporal: {pdf_filename_tmp} - {e}")
                                        pdf_paths.append(pdf_filename)
                                        preview_path = pdf_filename.replace('.pdf', '_preview.png')
                                        # Generar vista previa si no existe
                                        if not os.path.exists(preview_path):
                                            print(f"[INFO] Generando vista previa del PDF para {pdf_filename}...")
                                            generar_preview_pdf(pdf_filename, preview_path)
                                    else:
                                        print(f"[ERROR] No se pudo descargar el PDF {doc_idx + 1} para folio {folio}")
                        else:
                            print(f"[WARN] No hay PDF disponible para el movimiento {folio}")
                        
                        # Usar el primer PDF como referencia principal para compatibilidad
                        pdf_path = pdf_paths[0] if pdf_paths else None
                        
                        # Crear y agregar el movimiento a la lista global
                        movimiento_pjud = MovimientoPJUD(
                            folio=folio,
                            seccion=tab_name,
                            caratulado=caratulado,
                            libro=libro_text,
                            fecha=fecha_tramite_str,
                            pdf_path=pdf_path,
                            corte=corte
                        )
                        if agregar_movimiento_sin_duplicar(movimiento_pjud):
                            print(f"[INFO] Movimiento agregado exitosamente al diccionario global")
                        else:
                            print(f"[INFO] El movimiento ya existía en el diccionario global")
                    else:
                        print(f"[INFO] Movimiento ignorado - Folio: {folio}, Fecha: {fecha_tramite_str} (no coincide con fecha objetivo)")
                                
                except Exception as e:
                    print(f"[ERROR] Error procesando movimiento: {str(e)}")
                    continue
            return movimientos_nuevos
        except Exception as e:
            print(f"[ERROR] Error al verificar movimientos nuevos: {str(e)}")
            return False

#Aqui se maneja la navegacion en la pestaña Civil de Mis Causas
class ControladorLupaCivil(ControladorLupa):
    def obtener_config(self):
        return {
            'lupa_selector': "#dtaTableDetalleMisCauCiv a[href*='modalAnexoCausaCivil']",
            'modal_selector': "#modalDetalleMisCauCivil",
            'modal_title': "Detalle Causa",
            'table_selector': ".modal-content table.table-bordered",
            'expected_headers': ['Folio', 'Doc.', 'Anexo', 'Etapa', 'Trámite', 'Desc. Trámite', 'Fec. Trámite', 'Foja', 'Georeferencia'],
            'process_content': True
        }

    def _procesar_contenido(self, tab_name, caratulado):
        try:
            print(f"[INFO] Procesando movimientos en Civil...")
            
            # Obtener opciones del dropdown
            opciones_cuaderno = self._obtener_opciones_cuaderno()
            if not opciones_cuaderno:
                print("[WARN] No se pudieron obtener las opciones del cuaderno")
                return False
                
            movimientos_nuevos = False
            carpeta_general = tab_name.replace(' ', '_')
            
            # Procesar cada opción del dropdown
            for opcion in opciones_cuaderno:
                try:
                    numero = opcion['numero']
                    texto = opcion['texto']
                    
                    print(f"  Procesando cuaderno: {texto}")
                    
                    # Limpiar el texto para usarlo como nombre de carpeta
                    texto_limpio = re.sub(r'[<>:"/\\|?*]', '_', texto)
                    texto_limpio = texto_limpio[:50]                     
                    
                    # Intentar seleccionar la opción en el dropdown con retry
                    max_retries = 3
                    for attempt in range(max_retries):
                        try:
                            # Esperar a que el dropdown esté visible y habilitado
                            dropdown = self.page.wait_for_selector('#selCuaderno:not([disabled])', timeout=5000)
                            if not dropdown:
                                raise Exception("No se encontró el dropdown")
                            
                            # Hacer clic en el dropdown para abrirlo
                            dropdown.click()
                            random_sleep(0.5, 1)
                            
                            # Intentar seleccionar la opción usando el texto
                            success = self.page.evaluate(f"""
                                () => {{
                                    const select = document.querySelector('#selCuaderno');
                                    if (!select) return false;
                                    
                                    // Buscar la opción por texto
                                    const options = Array.from(select.options);
                                    const targetOption = options.find(opt => opt.textContent.trim() === '{texto}');
                                    
                                    if (!targetOption) {{
                                        console.log('No se encontró la opción:', '{texto}');
                                        return false;
                                    }}
                                    
                                    // Cambiar el valor
                                    select.value = targetOption.value;
                                    
                                    // Verificar si el cambio fue exitoso
                                    if (select.value !== targetOption.value) {{
                                        console.log('El cambio de valor falló');
                                        return false;
                                    }}
                                    
                                    // Disparar el evento change
                                    select.dispatchEvent(new Event('change', {{ bubbles: true }}));
                                    return true;
                                }}
                            """)
                            
                            if not success:
                                raise Exception("No se pudo cambiar el valor del dropdown")
                            
                            # Esperar a que la tabla se actualice
                            try:
                                # Esperar a que la tabla tenga filas
                                self.page.wait_for_selector("#historiaCiv table.table-bordered tbody tr", timeout=5000)
                                
                                # Verificar que la tabla tenga contenido
                                rows = self.page.query_selector_all("#historiaCiv table.table-bordered tbody tr")
                                if len(rows) > 0:
                                    print(f"  Tabla actualizada con {len(rows)} filas")
                                    break
                                else:
                                    raise Exception("La tabla está vacía")
                            except Exception as e:
                                if attempt == max_retries - 1:
                                    raise e
                                print(f"[WARN] Intento {attempt + 1} fallido al esperar la tabla: {str(e)}")
                                random_sleep(1, 2)
                                continue
                                
                        except Exception as e:
                            if attempt == max_retries - 1:
                                print(f"[ERROR] No se pudo seleccionar la opción después de {max_retries} intentos: {str(e)}")
                                raise e
                            print(f"[WARN] Intento {attempt + 1} fallido: {str(e)}")
                            random_sleep(1, 2)                    
                    
                    # Obtener movimientos de la tabla
                    movimientos = self.page.query_selector_all("#historiaCiv table.table-bordered tbody tr")
                    print(f"[INFO] Se encontraron {len(movimientos)} movimientos en el cuaderno {texto}")
                    
                    # Fecha específica según el cuaderno
                    fecha_objetivo = obtener_fecha_actual_str()
                    
                    #crear carpeta para el caratulado
                    carpeta_caratulado = f"{carpeta_general}/{caratulado}"                                
                    # Crear carpeta para el cuaderno con nombre limpio
                    nombre_carpeta = f"Cuaderno_{texto_limpio}"
                    carpeta_cuaderno = f"{carpeta_caratulado}/{nombre_carpeta}"
                    
                    for movimiento in movimientos:
                        try:
                            folio = movimiento.query_selector("td:nth-child(1)").inner_text().strip()
                            fecha_tramite_str = movimiento.query_selector("td:nth-child(7)").inner_text().strip()
                            # Manejar fechas con paréntesis
                            if '(' in fecha_tramite_str:
                                fecha_tramite_str = fecha_tramite_str.split('(')[0].strip()
                            if fecha_tramite_str == fecha_objetivo:
                                movimientos_nuevos = True
                                if not os.path.exists(carpeta_cuaderno):
                                    os.makedirs(carpeta_cuaderno)
                                # Capturar panel de detalles
                                try:
                                    tribunal_td = None
                                    print(f"  Intentando capturar panel de detalles para cuaderno {texto}...")
                                    # Esperar a que el panel esté visible
                                    panel = self.page.wait_for_selector("#modalDetalleMisCauCivil .modal-body .panel.panel-default", timeout=5000)
                                    numero_causa = None
                                    if panel:
                                        # Extraer el número de causa del ROL
                                        try:
                                            rol_td = panel.query_selector("td:has-text('ROL:')")
                                            if rol_td:
                                                rol_text = rol_td.inner_text()
                                                print(f"[INFO] Texto completo del ROL extraído: {rol_text}")
                                        except Exception as rol_error:
                                            print(f"[WARN] Error extrayendo el número de causa del ROL: {str(rol_error)}")

                                        #extraer el tribunal
                                        try:
                                            tribunal_td = panel.query_selector("td:has-text('Tribunal:')")
                                            if tribunal_td:
                                                tribunal_text = tribunal_td.inner_text().replace("Tribunal:", "").strip()
                                                print(f"[INFO] Texto limpio del Tribunal extraído: {tribunal_text}")
                                        except Exception as tribunal_error:
                                            print(f"[WARN] Error extrayendo el Tribunal: {str(tribunal_error)}")

                                        # Intentar hacer scroll
                                        self.page.evaluate("""
                                            (element) => {
                                                element.scrollIntoView({ behavior: 'smooth', block: 'center' });
                                            }
                                        """, panel)
                                        random_sleep(1, 2)
                                        # Intentar captura de pantalla
                                        detalle_panel_path = f"{carpeta_cuaderno}/Detalle_causa_{numero_causa}_Cuaderno_{texto_limpio}.png" if numero_causa else f"{carpeta_cuaderno}/Detalle_causa_Cuaderno_{texto_limpio}.png"
                                        try:
                                            panel.screenshot(path=detalle_panel_path, timeout=10000)
                                            print(f"[INFO] Captura del panel guardada: {detalle_panel_path}")
                                        except Exception as screenshot_error:
                                            print(f"[WARN] No se pudo tomar la captura del panel: {str(screenshot_error)}")
                                            # Intentar captura alternativa usando JavaScript
                                            try:
                                                self.page.evaluate("""
                                                    (element) => {
                                                        const canvas = document.createElement('canvas');
                                                        const context = canvas.getContext('2d');
                                                        const rect = element.getBoundingClientRect();
                                                        canvas.width = rect.width;
                                                        canvas.height = rect.height;
                                                        context.drawWindow(
                                                            window,
                                                            rect.left,
                                                            rect.top,
                                                            rect.width,
                                                            rect.height,
                                                            'rgb(255,255,255)'
                                                        );
                                                        return canvas.toDataURL();
                                                    }
                                                """, panel)
                                                print("[INFO] Captura alternativa del panel realizada")
                                            except Exception as js_error:
                                                print(f"[WARN] No se pudo realizar la captura alternativa: {str(js_error)}")
                                    else:
                                        print(f"[WARN] No se pudo procesar el panel: {str(panel_error)}")
                                except Exception as panel_error:
                                    print(f"[WARN] No se pudo procesar el panel: {str(panel_error)}")
                                
                                # Crear carpeta Historia
                                carpeta_historia = f"{carpeta_cuaderno}/Historia"
                                if not os.path.exists(carpeta_historia):
                                    os.makedirs(carpeta_historia)
                                print(f"[INFO] Movimiento nuevo encontrado - Folio: {folio}, Fecha: {fecha_tramite_str}")
                                # Buscar TODOS los formularios de PDF (form y certCivil)
                                pdf_forms = movimiento.query_selector_all("form")
                                # Filtrar solo los formularios que tienen inputs con tokens PDF
                                pdf_forms_validos = []
                                for form in pdf_forms:
                                    if form.query_selector("input[name='dtaDoc']") or form.query_selector("input[name='dtaCert']"):
                                        pdf_forms_validos.append(form)
                                pdf_forms = pdf_forms_validos
                                pdf_paths = []
                                if pdf_forms:
                                    print(f"[INFO] Se encontraron {len(pdf_forms)} documentos para el folio {folio}")
                                    for doc_idx, pdf_form in enumerate(pdf_forms):
                                        # Obtener el token según el tipo de formulario
                                        token_input = pdf_form.query_selector("input[name='dtaDoc']")
                                        if token_input:
                                            token = token_input.get_attribute("value")
                                            token_type = "dtaDoc"
                                        else:
                                            token_input = pdf_form.query_selector("input[name='dtaCert']")
                                            if token_input:
                                                token = token_input.get_attribute("value")
                                                token_type = "dtaCert"
                                            else:
                                                print(f"[WARN] No se encontró token en formulario {doc_idx + 1}")
                                                continue
                                        
                                        fecha_tramite_pdf = fecha_tramite_str[6:10] + fecha_tramite_str[3:5] + fecha_tramite_str[0:2]
                                        # Extraer el texto del rol para el nombre del PDF
                                        panel = self.page.query_selector("#modalDetalleMisCauCivil .modal-body .panel.panel-default")
                                        rol_td = panel.query_selector("td:has-text('rol')") if panel else None
                                        if rol_td:
                                            rol_text = rol_td.inner_text()
                                            rol_pdf = rol_text.replace("ROL: ", "").strip().replace("/", " ").replace("-", " ")
                                        else:
                                            rol_pdf = "sin rol"
                                        
                                        # Agregar sufijo para múltiples documentos y tipo de documento
                                        doc_suffix = f"_doc{doc_idx + 1}" if len(pdf_forms) > 1 else ""
                                        tipo_suffix = "_cert" if token_type == "dtaCert" else ""
                                        # Nombre temporal antes de tener el resumen
                                        pdf_filename_tmp = f"{carpeta_historia}/{fecha_tramite_pdf} {folio} {rol_pdf}{tipo_suffix}_temp.pdf"
                                        preview_path = pdf_filename_tmp.replace('.pdf', '_preview.png')

                                        if token:
                                            # Determinar la URL base según el tipo de documento
                                            action = pdf_form.get_attribute("action") or ""
                                            if token_type == "dtaCert":
                                                base_url = "https://oficinajudicialvirtual.pjud.cl/misCausas/civil/documentos/docCertificadoEscrito.php?dtaCert="
                                            elif "docuS.php" in action:
                                                base_url = "https://oficinajudicialvirtual.pjud.cl/misCausas/civil/documentos/docuS.php?dtaDoc="
                                            else:
                                                base_url = "https://oficinajudicialvirtual.pjud.cl/misCausas/civil/documentos/docuN.php?dtaDoc="
                                            original_url = base_url + token
                                            pdf_descargado = descargar_pdf_directo(original_url, pdf_filename_tmp, self.page)
                                            if pdf_descargado:
                                                resumen_pdf = extraer_resumen_pdf(pdf_filename_tmp)
                                                print(f"[DEBUG] Resumen antes de limpiar: {resumen_pdf!r}")
                                                resumen_pdf_limpio = limpiar_nombre_archivo(resumen_pdf)
                                                print(f"[DEBUG] Resumen después de limpiar: {resumen_pdf_limpio!r}")

                                                pdf_filename = f"{carpeta_historia}/{fecha_tramite_pdf} {folio} {rol_pdf}{tipo_suffix} {resumen_pdf_limpio}.pdf"
                                                # Si hay múltiples documentos, agregar sufijo al nombre final
                                                if len(pdf_forms) > 1:
                                                    base_name, ext = os.path.splitext(pdf_filename)
                                                    pdf_filename = f"{base_name}{doc_suffix}{ext}"
                                                # Evitar sobrescribir archivos existentes
                                                if os.path.exists(pdf_filename):
                                                    print(f"[WARN] El archivo final {pdf_filename} ya existe. Se eliminará para evitar conflicto.")
                                                    os.remove(pdf_filename)
                                                # Limitar el nombre del archivo si es demasiado largo
                                                max_filename_len = 156
                                                base, ext = os.path.splitext(pdf_filename)
                                                if len(pdf_filename) > max_filename_len:
                                                    pdf_filename = base[:max_filename_len - len(ext)] + ext
                                                #renombrar el archivo temporal al nombre final
                                                try:
                                                    os.rename(pdf_filename_tmp, pdf_filename)
                                                except Exception as e:
                                                    print(f"[WARN] No se pudo renombrar el archivo temporal: {pdf_filename_tmp} -> {pdf_filename} - {e}")
                                                finally:
                                                    if os.path.exists(pdf_filename_tmp):
                                                        try:
                                                            os.remove(pdf_filename_tmp)
                                                            print(f"[INFO] Archivo temporal eliminado: {pdf_filename_tmp}")
                                                        except Exception as e:
                                                            print(f"[WARN] No se pudo eliminar el archivo temporal: {pdf_filename_tmp} - {e}")
                                                pdf_paths.append(pdf_filename)
                                                preview_path = pdf_filename.replace('.pdf', '_preview.png')
                                                if not os.path.exists(preview_path):
                                                    print(f"[INFO] Generando vista previa del PDF para {pdf_filename}...")
                                                    generar_preview_pdf(pdf_filename, preview_path)
                                else:
                                    print(f"[WARN] No hay PDF disponible para el movimiento {folio}")

                                # Usar la lista completa de PDFs
                                # Crear y agregar el movimiento a la lista global 
                                movimiento_pjud = MovimientoPJUD(
                                    folio=folio,
                                    seccion=tab_name,
                                    caratulado=caratulado,
                                    rol=rol_text,
                                    fecha=fecha_tramite_str,
                                    pdf_paths=pdf_paths,  # Pasar la lista completa de PDFs
                                    tribunal=tribunal_text,
                                    cuaderno=texto,  # Agregamos el nombre del cuaderno
                                    historia_causa_cuaderno=texto  # Agregamos el cuaderno de historia para Civil
                                )
                                if agregar_movimiento_sin_duplicar(movimiento_pjud):
                                    print(f"[INFO] Movimiento agregado exitosamente al diccionario global")
                                else:
                                    print(f"[INFO] El movimiento ya existía en el diccionario global")
                            else:
                                print(f"[INFO] Movimiento ignorado - Folio: {folio}, Fecha: {fecha_tramite_str} (no coincide con fecha objetivo)")
                                
                        except Exception as e:
                            print(f"[ERROR] Error procesando movimiento: {str(e)}")
                            continue
                    
                    # Cambiar a la pestaña Escritos por Resolver
                    self.page.click('a[href="#escritosCiv"]')
                    random_sleep(1, 2)
                    self._procesar_escritos_por_resolver(tab_name, caratulado, carpeta_cuaderno, texto)
                    
                except Exception as e:
                    print(f"[ERROR] Error procesando cuaderno {texto}: {str(e)}")
                    continue
            
            return movimientos_nuevos
            
        except Exception as e:
            print(f"[ERROR] Error al verificar movimientos nuevos: {str(e)}")
            return False

    def _procesar_escritos_por_resolver(self, tab_name, caratulado, carpeta_cuaderno, cuaderno_nombre):
        """
        Procesa la tabla de Escritos por Resolver en Civil y agrega nuevos movimientos.
        """
        try:
            #Extraer ROL y Tribunal del panel de detalles
            rol_text = None
            tribunal_text = None
            try:
                panel = self.page.query_selector("#modalDetalleMisCauCivil .modal-body .panel.panel-default")
                if panel:
                    # Extraer ROL
                    rol_td = panel.query_selector("td:has-text('ROL:')")
                    if rol_td:
                        rol_text = rol_td.inner_text().strip() 
                    # Extraer Tribunal
                    tribunal_td = panel.query_selector("td:has-text('Tribunal:')")
                    if tribunal_td:
                        tribunal_text = tribunal_td.inner_text().replace("Tribunal:", "").strip()
            except Exception as e:
                print(f"[WARN] No se pudo extraer ROL o Tribunal: {str(e)}")

            # Asegura que la pestaña esté activa
            self.page.click('a[href="#escritosCiv"]')
            self.page.wait_for_selector('#escritosCiv.active.in', timeout=5000)
            # Espera a que la tabla esté presente (aunque esté vacía)
            self.page.wait_for_selector('#escritosCiv table.table-bordered tbody', timeout=5000, state="attached")
            escritos = self.page.query_selector_all('#escritosCiv table.table-bordered tbody tr')
            print(f"[INFO] Se encontraron {len(escritos)} escritos por resolver")
            fecha_objetivo_escrito = obtener_fecha_actual_str()
            for escrito in escritos:
                try:
                    fecha_ingreso = escrito.query_selector("td:nth-child(3)").inner_text().strip()
                    tipo_escrito = escrito.query_selector("td:nth-child(4)").inner_text().strip()
                    solicitante = escrito.query_selector("td:nth-child(5)").inner_text().strip()
                    pdf_forms = escrito.query_selector_all("form[name='formAneEsc']")
                    pdf_paths = []
                    if fecha_ingreso == fecha_objetivo_escrito:
                        carpeta_escritos = f"{carpeta_cuaderno}/EscritosPorResolver"
                        if not os.path.exists(carpeta_escritos):
                            os.makedirs(carpeta_escritos, exist_ok=True)
                        # Descargar PDFs si existen
                        if pdf_forms:
                            print(f"[INFO] Se encontraron {len(pdf_forms)} documentos para el escrito")
                            for doc_idx, pdf_form in enumerate(pdf_forms):
                                token = pdf_form.query_selector("input[name='dtaDoc']").get_attribute("value")
                                fecha_ingreso_limpia = limpiar_nombre_archivo(fecha_ingreso.replace("/", "-"))
                                tipo_escrito_limpio = limpiar_nombre_archivo(tipo_escrito)
                                
                                # Agregar sufijo para múltiples documentos
                                doc_suffix = f"_doc{doc_idx + 1}" if len(pdf_forms) > 1 else ""
                                pdf_filename_tmp = f"{carpeta_escritos}/{fecha_ingreso_limpia} {tipo_escrito_limpio}_temp.pdf"
                                
                                if token:
                                    base_url = "https://oficinajudicialvirtual.pjud.cl/misCausas/civil/documentos/docuN.php?dtaDoc="
                                    original_url = base_url + token
                                    pdf_descargado = descargar_pdf_directo(original_url, pdf_filename_tmp, self.page)
                                    if pdf_descargado:
                                        resumen_pdf = extraer_resumen_pdf(pdf_filename_tmp)
                                        resumen_pdf_limpio = limpiar_nombre_archivo(resumen_pdf)

                                        # Formato fecha: AAAAMMDD
                                        fecha_ingreso_pdf = fecha_ingreso[6:10] + fecha_ingreso[3:5] + fecha_ingreso[0:2]
                                        # Formato rol: "ROL: V-82-2025" -> "V 82 2025"
                                        rol_pdf = ""
                                        if rol_text:
                                            rol_pdf = limpiar_nombre_archivo(
                                                rol_text.replace("ROL:", "").replace("-", " ").replace("/", " ").strip()
                                            )
                                        # Nombre final
                                        pdf_filename = f"{carpeta_escritos}/{fecha_ingreso_pdf} {rol_pdf} {resumen_pdf_limpio}.pdf"
                                        # Si hay múltiples documentos, agregar sufijo al nombre final
                                        if len(pdf_forms) > 1:
                                            base_name, ext = os.path.splitext(pdf_filename)
                                            pdf_filename = f"{base_name}{doc_suffix}{ext}"

                                        if os.path.exists(pdf_filename):
                                            print(f"[WARN] El archivo final {pdf_filename} ya existe. Se eliminará para evitar conflicto.")
                                            os.remove(pdf_filename)
                                        max_filename_len = 156
                                        base, ext = os.path.splitext(pdf_filename)
                                        if len(pdf_filename) > max_filename_len:
                                            pdf_filename = base[:max_filename_len - len(ext)] + ext
                                        try:
                                            os.rename(pdf_filename_tmp, pdf_filename)
                                        except Exception as e:
                                            print(f"[WARN] No se pudo renombrar el archivo temporal: {pdf_filename_tmp} -> {pdf_filename} - {e}")
                                        finally:
                                            if os.path.exists(pdf_filename_tmp):
                                                try:
                                                    os.remove(pdf_filename_tmp)
                                                    print(f"[INFO] Archivo temporal eliminado: {pdf_filename_tmp}")
                                                except Exception as e:
                                                    print(f"[WARN] No se pudo eliminar el archivo temporal: {pdf_filename_tmp} - {e}")
                                        pdf_paths.append(pdf_filename)
                                        preview_path = pdf_filename.replace('.pdf', '_preview.png')
                                        if not os.path.exists(preview_path):
                                            print(f"[INFO] Generando vista previa del PDF para {pdf_filename}...")
                                            generar_preview_pdf(pdf_filename, preview_path)
                        
                        # Agregar movimiento a la lista global con todos los PDFs
                        movimiento_pjud = MovimientoPJUD(
                            folio=None,
                            seccion=tab_name,
                            caratulado=caratulado,
                            fecha=fecha_ingreso,
                            pdf_paths=pdf_paths,  # Pasar la lista completa de PDFs
                            historia_causa_cuaderno = cuaderno_nombre + ", Escritos por Resolver",
                            rol=rol_text,          
                            tribunal=tribunal_text 
                        )
                        if agregar_movimiento_sin_duplicar(movimiento_pjud):
                            print(f"[INFO] Escrito por resolver agregado exitosamente al diccionario global")
                        else:
                            print(f"[INFO] El escrito ya existía en el diccionario global")
                except Exception as e:
                    print(f"[ERROR] Error procesando escrito por resolver: {str(e)}")
                    continue
        except Exception as e:
            print(f"[WARN] No se pudo procesar la tabla de Escritos por Resolver: {str(e)}") 
    
    def _obtener_opciones_cuaderno(self):
        """Obtiene todas las opciones del dropdown de cuadernos"""
        try:
            print("  Obteniendo opciones del dropdown de cuadernos...")
            
            # Esperar a que el dropdown esté visible
            self.page.wait_for_selector('#selCuaderno', timeout=5000)
            
            # Obtener opciones usando JavaScript
            opciones = self.page.evaluate("""
                () => {
                    const select = document.querySelector('#selCuaderno');
                    if (!select) return [];
                    
                    return Array.from(select.options).map(option => ({
                        numero: option.value,
                        texto: option.textContent.trim(),
                        es_seleccionado: option.selected
                    }));
                }
            """)
            
            if not opciones:
                print("  No se encontraron opciones en el dropdown")
                return []
                
            print(f"  Se encontraron {len(opciones)} opciones en el dropdown")
            return opciones
            
        except Exception as e:
            print(f"  Error al obtener opciones del dropdown: {str(e)}")
            return []

#Aqui se maneja la navegacion en la pestaña Cobranza de Mis Causas
class ControladorLupaCobranza(ControladorLupa):
    def obtener_config(self):
        return {
            'lupa_selector': "#dtaTableDetalleMisCauCob a[href*='modalAnexoCausaCobranza']",
            'modal_selector': "#modalDetalleMisCauCobranza",
            'modal_title': "Detalle Causa",
            'table_selector': "#historiaCob table.table-bordered",
            'expected_headers': ['Folio', 'Doc.', 'Anexo', 'Etapa', 'Trámite', 'Desc. Trámite', 'Estado Firma', 'Fec. Trámite', 'Georeferencia'],
            'process_content': True
        }

    def _procesar_contenido(self, tab_name, caratulado):
        try:
            print(f"[INFO] Procesando movimientos en Cobranza...")
            
            # Obtener opciones del dropdown
            opciones_cuaderno = self._obtener_opciones_cuaderno()
            if not opciones_cuaderno:
                print("[WARN] No se pudieron obtener las opciones del cuaderno")
                return False
                
            movimientos_nuevos = False
            carpeta_general = tab_name.replace(' ', '_')
 
            # Procesar cada opción del dropdown
            for opcion in opciones_cuaderno:
                try:
                    numero = opcion['numero']
                    texto = opcion['texto']
                    
                    print(f"  Procesando cuaderno: {texto}")
                    
                    # Limpiar el texto para usarlo como nombre de carpeta
                    texto_limpio = re.sub(r'[<>:"/\\|?*]', '_', texto)
                    texto_limpio = texto_limpio[:50] 
                    
                    # Intentar seleccionar la opción en el dropdown con retry
                    max_retries = 3
                    for attempt in range(max_retries):
                        try:
                            # Esperar a que el dropdown esté visible y habilitado
                            dropdown = self.page.wait_for_selector('#selCuadernoCob:not([disabled])', timeout=5000)
                            if not dropdown:
                                raise Exception("No se encontró el dropdown")
                            
                            # Hacer clic en el dropdown para abrirlo
                            dropdown.click()
                            random_sleep(0.5, 1)
                            
                            # Intentar seleccionar la opción usando el texto
                            success = self.page.evaluate(f"""
                                () => {{
                                    const select = document.querySelector('#selCuadernoCob');
                                    if (!select) return false;
                                    
                                    // Buscar la opción por texto
                                    const options = Array.from(select.options);
                                    const targetOption = options.find(opt => opt.textContent.trim() === '{texto}');
                                    
                                    if (!targetOption) {{
                                        console.log('No se encontró la opción:', '{texto}');
                                        return false;
                                    }}
                                    
                                    // Seleccionar la opción
                                    select.value = targetOption.value;
                                    
                                    // Disparar evento change
                                    const event = new Event('change', {{ bubbles: true }});
                                    select.dispatchEvent(event);
                                    
                                    return true;
                                }}
                            """)
                            
                            if not success:
                                raise Exception(f"No se pudo seleccionar la opción: {texto}")
                            
                            # Esperar a que la tabla se actualice
                            try:
                                # Esperar a que la tabla tenga filas
                                self.page.wait_for_selector("#historiaCob table.table-bordered tbody tr", timeout=5000)
                                
                                # Verificar que la tabla tenga contenido
                                rows = self.page.query_selector_all("#historiaCob table.table-bordered tbody tr")
                                if len(rows) > 0:
                                    print(f"  Tabla actualizada con {len(rows)} filas")
                                    break
                                else:
                                    raise Exception("La tabla está vacía")
                            except Exception as e:
                                if attempt == max_retries - 1:
                                    raise e
                                print(f"[WARN] Intento {attempt + 1} fallido al esperar la tabla: {str(e)}")
                                random_sleep(1, 2)
                                continue
                                
                        except Exception as e:
                            if attempt == max_retries - 1:
                                print(f"[ERROR] No se pudo seleccionar la opción después de {max_retries} intentos: {str(e)}")
                                raise e
                            print(f"[WARN] Intento {attempt + 1} fallido: {str(e)}")
                            random_sleep(1, 2)                    
                    
                    # Obtener movimientos de la tabla
                    movimientos = self.page.query_selector_all("#historiaCob table.table-bordered tbody tr")
                    print(f"[INFO] Se encontraron {len(movimientos)} movimientos en el cuaderno {texto}")
                    
                    # Fecha específica según el cuaderno
                    fecha_objetivo = obtener_fecha_actual_str()
                    
                    for movimiento in movimientos:
                        try:
                            folio = movimiento.query_selector("td:nth-child(1)").inner_text().strip()
                            fecha_tramite_str = movimiento.query_selector("td:nth-child(8)").inner_text().strip()
                            # Manejar fechas con paréntesis
                            if '(' in fecha_tramite_str:
                                fecha_tramite_str = fecha_tramite_str.split('(')[0].strip()
                            if fecha_tramite_str == fecha_objetivo:
                                movimientos_nuevos = True
                                #Crear carpeta Caratulado
                                carpeta_caratulado = f"{carpeta_general}/{caratulado}"
                                # Crear carpeta para el cuaderno con nombre limpio
                                nombre_carpeta = f"Cuaderno_{texto_limpio}"
                                carpeta_cuaderno = f"{carpeta_caratulado}/{nombre_carpeta}"
                                if not os.path.exists(carpeta_cuaderno):
                                    os.makedirs(carpeta_cuaderno)
                                
                                # Capturar panel de detalles
                                try:
                                    tribunal_td = None
                                    print(f"  Intentando capturar panel de detalles para cuaderno {texto}...")
                                    # Esperar a que el panel esté visible
                                    panel = self.page.wait_for_selector("#modalDetalleMisCauCobranza .modal-body .panel.panel-default", timeout=5000)
                                    numero_causa = None
                                    if panel:
                                        # Extraer el número de causa del RIT
                                        try:
                                            rit_td = panel.query_selector("td:has-text('RIT')")
                                            if rit_td:
                                                rit_text = rit_td.inner_text()
                                                print(f"[INFO] Texto completo del RIT extraído: {rit_text}")

                                        except Exception as rit_error:
                                            print(f"[WARN] Error extrayendo el número de causa del RIT: {str(rit_error)}")
                                        
                                        #extraer el tribunal
                                        try:
                                            tribunal_td = panel.query_selector("td:has-text('Tribunal:')")
                                            if tribunal_td:
                                                tribunal_text = tribunal_td.inner_text().replace("Tribunal:", "").strip()
                                                print(f"[INFO] Texto completo del Tribunal extraído: {tribunal_text}")
                                        except Exception as tribunal_error:
                                            print(f"[WARN] Error extrayendo el Tribunal: {str(tribunal_error)}")
                                        
                                        # Intentar hacer scroll
                                        self.page.evaluate("""
                                            (element) => {
                                                element.scrollIntoView({ behavior: 'smooth', block: 'center' });
                                            }
                                        """, panel)
                                        random_sleep(1, 2)
                                        
                                        # Guardar captura del panel
                                        detalle_panel_path = f"{carpeta_cuaderno}/Detalle_causa_{numero_causa}_Cuaderno_{texto_limpio}.png" if numero_causa else f"{carpeta_cuaderno}/Detalle_causa_Cuaderno_{texto_limpio}.png"
                                        panel.screenshot(path=detalle_panel_path)
                                        print(f"[INFO] Captura del panel guardada: {detalle_panel_path}")
                                    else:
                                        print("[WARN] No se encontró el panel de información")
                                except Exception as panel_error:
                                    print(f"[WARN] No se pudo procesar el panel: {str(panel_error)}")
                                
                                # Crear carpeta Historia
                                carpeta_historia = f"{carpeta_cuaderno}/Historia"
                                if not os.path.exists(carpeta_historia):
                                    os.makedirs(carpeta_historia)                                
                                
                                print(f"[INFO] Movimiento nuevo encontrado - Folio: {folio}, Fecha: {fecha_tramite_str}")
                                # Buscar los formularios de PDF
                                pdf_forms = movimiento.query_selector_all("form[name='frmDocH']")
                                pdf_paths = []
                                if pdf_forms:
                                    print(f"[INFO] Se encontraron {len(pdf_forms)} documentos para el folio {folio}")
                                    for doc_idx, pdf_form in enumerate(pdf_forms):
                                        token = pdf_form.query_selector("input[name='dtaDoc']").get_attribute("value")
                                        fecha_tramite_pdf = fecha_tramite_str[6:10] + fecha_tramite_str[3:5] + fecha_tramite_str[0:2]
                                        # Extraer el texto del rol para el nombre del PDF
                                        panel = self.page.query_selector("#modalDetalleMisCauCobranza .modal-body .panel.panel-default")                                       
                                        rit_td = panel.query_selector("td:has-text('rit')") if panel else None
                                        if rit_td:
                                            rit_text = rit_td.inner_text()
                                            rit_pdf = rit_text.replace("RIT: ", "").strip().replace("/", " ").replace("-", " ")
                                        else:
                                            rit_pdf = "sin rit"
                                        
                                        folio_limpio = limpiar_nombre_archivo(folio)[:10]
                                        rit_pdf_limpio = limpiar_nombre_archivo(rit_pdf)[:20]
                                        
                                        # Agregar sufijo para múltiples documentos
                                        doc_suffix = f"_doc{doc_idx + 1}" if len(pdf_forms) > 1 else ""
                                        # Nombre temporal antes de tener el resumen
                                        pdf_filename_tmp = f"{carpeta_historia}/{fecha_tramite_pdf} {folio_limpio} {rit_pdf_limpio}_temp.pdf"
                                        preview_path = pdf_filename_tmp.replace('.pdf', '_preview.png')

                                        if token:
                                            base_url = "https://oficinajudicialvirtual.pjud.cl/misCausas/cobranza/documentos/docuCobranza.php?dtaDoc="
                                            original_url = base_url + token
                                            pdf_descargado = descargar_pdf_directo(original_url, pdf_filename_tmp, self.page)
                                            if pdf_descargado:
                                                resumen_pdf = extraer_resumen_pdf(pdf_filename_tmp)                                                                                
                                                print(f"[DEBUG] Resumen antes de limpiar: {resumen_pdf!r}")
                                                
                                                # Limpiar y limitar el resumen a 40 caracteres
                                                resumen_pdf_limpio = limpiar_nombre_archivo(resumen_pdf)[:40]
                                                print(f"[DEBUG] Resumen después de limpiar: {resumen_pdf_limpio!r}")
                                               
                                                pdf_filename = f"{carpeta_historia}/{fecha_tramite_pdf} {folio_limpio} {rit_pdf_limpio} {resumen_pdf_limpio}.pdf"
                                                # Si hay múltiples documentos, agregar sufijo al nombre final
                                                if len(pdf_forms) > 1:
                                                    base_name, ext = os.path.splitext(pdf_filename)
                                                    pdf_filename = f"{base_name}{doc_suffix}{ext}"
                                                # Evitar sobrescribir archivos existentes
                                                if os.path.exists(pdf_filename):
                                                    print(f"[WARN] El archivo final {pdf_filename} ya existe. Se eliminará para evitar conflicto.")
                                                    os.remove(pdf_filename)                                            
                                                # Limitar el nombre del archivo si es demasiado largo
                                                max_filename_len = 156
                                                base, ext = os.path.splitext(pdf_filename)
                                                if len(pdf_filename) > max_filename_len:
                                                    pdf_filename = base[:max_filename_len - len(ext)] + ext
                                                #renombrar el archivo temporal al nombre final
                                                try:
                                                    os.rename(pdf_filename_tmp, pdf_filename)
                                                except Exception as e:
                                                    print(f"[WARN] No se pudo renombrar el archivo temporal: {pdf_filename_tmp} -> {pdf_filename} - {e}")
                                                finally:
                                                    if os.path.exists(pdf_filename_tmp):
                                                        try:
                                                            os.remove(pdf_filename_tmp)
                                                            print(f"[INFO] Archivo temporal eliminado: {pdf_filename_tmp}")
                                                        except Exception as e:
                                                            print(f"[WARN] No se pudo eliminar el archivo temporal: {pdf_filename_tmp} - {e}")
                                                pdf_paths.append(pdf_filename)
                                                preview_path = pdf_filename.replace('.pdf', '_preview.png')

                                                if not os.path.exists(preview_path):
                                                    print(f"[INFO] Generando vista previa del PDF para {pdf_filename}...")
                                                    generar_preview_pdf(pdf_filename, preview_path)
                                else:
                                    print(f"[WARN] No hay PDF disponible para el movimiento {folio}")
                                
                                # Usar el primer PDF como referencia principal para compatibilidad
                                pdf_path = pdf_paths[0] if pdf_paths else None
                                
                                # Crear y agregar el movimiento a la lista global
                                movimiento_pjud = MovimientoPJUD(
                                    folio=folio,
                                    seccion=tab_name,
                                    caratulado=caratulado,
                                    rit=rit_text,
                                    tribunal=tribunal_text,
                                    fecha=fecha_tramite_str,
                                    pdf_path=pdf_path,
                                    cuaderno=texto,  # Agregamos el nombre del cuaderno
                                    historia_causa_cuaderno=texto  # Agregamos el cuaderno de historia para Cobranza
                                )
                                if agregar_movimiento_sin_duplicar(movimiento_pjud):
                                    print(f"[INFO] Movimiento agregado exitosamente al diccionario global")
                                else:
                                    print(f"[INFO] El movimiento ya existía en el diccionario global")
                            else:
                                print(f"[INFO] Movimiento ignorado - Folio: {folio}, Fecha: {fecha_tramite_str} (no coincide con fecha objetivo)")
                                
                        except Exception as e:
                            print(f"[ERROR] Error procesando movimiento: {str(e)}")
                            continue
                    
                except Exception as e:
                    print(f"[ERROR] Error procesando cuaderno {texto}: {str(e)}")
                    continue
            
            return movimientos_nuevos
            
        except Exception as e:
            print(f"[ERROR] Error al verificar movimientos nuevos: {str(e)}")
            return False
        
    #Obtiene todas las opciones del dropdown de cuadernos de Cobranza
    def _obtener_opciones_cuaderno(self):
        
        try:
            print("  Obteniendo opciones del dropdown de cuadernos de Cobranza...")
            
            # Esperar a que el dropdown esté visible y habilitado
            dropdown = self.page.wait_for_selector('#selCuadernoCob:not([disabled])', timeout=5000)
            if not dropdown:
                raise Exception("No se encontró el dropdown")
            
            # Obtener opciones usando JavaScript
            opciones = self.page.evaluate("""
                () => {
                    const select = document.querySelector('#selCuadernoCob');
                    if (!select) return [];
                    
                    return Array.from(select.options).map(option => ({
                        numero: option.value,
                        texto: option.textContent.trim(),
                        es_seleccionado: option.selected
                    }));
                }
            """)
            
            if not opciones:
                print("  No se encontraron opciones en el dropdown")
                return []
                
            print(f"  Se encontraron {len(opciones)} opciones en el dropdown")
            return opciones
            
        except Exception as e:
            print(f"  Error al obtener opciones del dropdown: {str(e)}")
            return []

# Función para obtener el controlador de lupa correspondiente
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
    """
    Función genérica para manejar clics en lupa y sus modales asociados
    
    Args:
        page: La página de Playwright
        config: Diccionario con la configuración específica:
            - tipo: Tipo de lupa ('suprema', 'apelaciones', etc.)
            - tab_name: Nombre de la pestaña actual
    """
    controlador = obtener_controlador_lupa(config['tipo'], page)
    return controlador.manejar(config['tab_name'])

# Mapeo de pestañas a tipo de lupa
TIPO_LUPA_MAP = {
    "Corte Suprema": "suprema",
    "Corte Apelaciones": "apelaciones_principal",
    "Civil": "civil",
    "Cobranza": "cobranza"
}

#Navega por todas las pestañas en la sección Mis Causas
def navigate_mis_causas_tabs(page):
    print("\n--- Navegando por pestañas de Mis Causas ---")
    
    # Llevar un registro de las pestañas ya visitadas
    visited_tabs = set()
    
    for tab_name in MIS_CAUSAS_TABS:
        try:
            print(f"  Navegando a pestaña '{tab_name}'...")
            
            # si ya se visitó la pagina se evita hacerlo de nuevo
            if tab_name in visited_tabs:
                print(f"  Pestaña '{tab_name}' ya fue visitada. Continuando...")
                continue
            
            # Tratamiento especial para la pestaña "Corte Apelaciones" (se debe actualizar la pagina antes, si no, el modal de la causa queda inactivo)
            if tab_name == "Corte Apelaciones":
                print("  Implementando estrategia especial para Corte Apelaciones...")
                
                # Refrescar la página para asegurar un estado limpio
                print("  Refrescando la página...")
                page.reload()
                random_sleep(3, 5)
                
                # Volver a navegar a Mis Causas
                print("  Navegando de nuevo a 'Mis Causas'...")
                try:
                    # Intentar hacer clic mediante JavaScript
                    page.evaluate("misCausas();")
                    print("  Navegación a 'Mis Causas' mediante JS exitosa!")
                except Exception as js_error:
                    print(f"  Error al ejecutar JavaScript: {str(js_error)}")
                    
                    # Intento alternativo haciendo clic directamente en el elemento
                    try:
                        page.click("a:has-text('Mis Causas')")
                        print("  Navegación a 'Mis Causas' mediante clic directo exitosa!")
                    except Exception as click_error:
                        print(f"  Error al hacer clic directo: {str(click_error)}")
                        continue
                
                # Esperar a que cargue la página
                random_sleep(3, 5)
            
            # Antes de cambiar de pestaña, verificamos si hay modales abiertos y los cerramos
            try:
                any_modal_open = page.evaluate("""
                    () => {
                        return !!document.querySelector('.modal.in, .modal[style*="display: block"]') || 
                               !!document.querySelector('.modal-backdrop') ||
                               document.body.classList.contains('modal-open');
                    }
                """)
                
                if any_modal_open:
                    print("  Se detectaron modales abiertos. Intentando cerrarlos antes de cambiar de pestaña...")
                    page.evaluate("""
                        () => {
                            // Asegurar que no queden modales visibles
                            document.querySelectorAll('.modal.in, .modal[style*="display: block"]').forEach(modal => {
                                modal.style.display = 'none';
                                modal.classList.remove('in');
                            });
                            
                            // Asegurar que el body no tenga la clase modal-open
                            document.body.classList.remove('modal-open');
                            
                            // Eliminar todos los backdrops
                            document.querySelectorAll('.modal-backdrop').forEach(backdrop => {
                                if (backdrop.parentNode) {
                                    backdrop.parentNode.removeChild(backdrop);
                                }
                            });
                            
                            return true;
                        }
                    """)
                    # Esperar a que terminen de cerrarse los modales
                    random_sleep(2, 3)
            except Exception as modal_error:
                print(f"  Error al intentar cerrar modales antes del cambio de pestaña: {str(modal_error)}")
            
            # Pausa antes de cambiar de pestaña
            random_sleep(3, 5)
                
            # Intentar encontrar y hacer clic en la pestaña
            try:
                # Primero intentar con el texto exacto
                page.click(f"a:has-text('{tab_name}')")
            except:
                try:
                    # Si falla, intentar con una coincidencia más flexible
                    page.click(f"a:has-text('{tab_name}', 'i')")
                except:
                    print(f"  No se pudo encontrar la pestaña '{tab_name}'. Continuando...")
                    continue
            
            print(f"  Clic exitoso en pestaña '{tab_name}'")
            
            # Registrar que hemos visitado esta pestaña
            visited_tabs.add(tab_name)
            
            # Esperar a que cargue la pestaña
            random_sleep(2, 4)
            
            # Ejecutar la función de búsqueda si está definida para esta pestaña
            tipo_lupa = TIPO_LUPA_MAP.get(tab_name)
            if tipo_lupa:
                if not lupa(page, {'tipo': tipo_lupa, 'tab_name': tab_name}):
                    print(f"  Error al manejar la lupa de {tab_name}")
                    
                # Esperamos un tiempo adicional después de procesar las lupas
                random_sleep(3, 5)
                    
                # Verificar si quedaron modales abiertos
                try:
                    any_modal_open = page.evaluate("""
                        () => {
                            return !!document.querySelector('.modal.in, .modal[style*="display: block"]') || 
                                   !!document.querySelector('.modal-backdrop') ||
                                   document.body.classList.contains('modal-open');
                        }
                    """)
                    
                    if any_modal_open:
                        print("  ALERTA: Quedaron modales abiertos después de procesar lupas. Intentando cerrarlos...")
                        page.evaluate("""
                            () => {
                                // Asegurar que no queden modales visibles
                                document.querySelectorAll('.modal.in, .modal[style*="display: block"]').forEach(modal => {
                                    modal.style.display = 'none';
                                    modal.classList.remove('in');
                                });
                                
                                // Asegurar que el body no tenga la clase modal-open
                                document.body.classList.remove('modal-open');
                                
                                // Eliminar todos los backdrops
                                document.querySelectorAll('.modal-backdrop').forEach(backdrop => {
                                    if (backdrop.parentNode) {
                                        backdrop.parentNode.removeChild(backdrop);
                                    }
                                });
                                
                                return true;
                            }
                        """)
                        # Esperar a que terminen de cerrarse los modales
                        random_sleep(2, 3)
                except Exception as modal_check_error:
                    print(f"  Error al verificar modales abiertos: {str(modal_check_error)}")
                
            # Pausa después de procesar cada pestaña
            random_sleep(3, 5)
            
        except Exception as e:
            print(f"  Error navegando a pestaña '{tab_name}': {str(e)}")
            # Si ocurre un error, intentamos seguir con la siguiente pestaña
            continue    
    print("--- Finalizada navegación por pestañas de Mis Causas ---\n")


#Función principal del flujo PJUD
def automatizar_poder_judicial(page, username, password):
    try:
        print("\n=== INICIANDO AUTOMATIZACIÓN DEL PODER JUDICIAL ===\n")
        
        # Limpiar la lista global de movimientos
        MOVIMIENTOS_GLOBALES.clear()
        
        # Abrir la página principal
        print("Accediendo a la página principal de PJUD...")
        page.goto(BASE_URL_PJUD)
        
        # Esperar y hacer clic en "Todos los servicios"
        print("Buscando botón 'Todos los servicios'...")
        page.click("button:has-text('Todos los servicios')")
        
        # Esperar y hacer clic en "Clave Única"
        print("Buscando opción 'Clave Única'...")
        page.click("a:has-text('Clave Única')")
        
        # Llama a la función de login
        login_success = login(page, username, password)
    
        if login_success:
            print("Login completado con éxito")
            
            # Dar un tiempo para que la página principal se cargue completamente
            random_sleep(2, 4)
            
            # 1. Navegar a Mis Causas
            mis_causas_success = navigate_to_mis_causas(page)
            
            if mis_causas_success:
                # Navegar por las pestañas de Mis Causas
                navigate_mis_causas_tabs(page)
                
                print("\n=== RESUMEN DE MOVIMIENTOS ENCONTRADOS ===")
                for idx, movimiento in enumerate(MOVIMIENTOS_GLOBALES, 1):
                    print(f"\nMovimiento {idx}:")
                    print(f"  Folio: {movimiento.folio}")
                    print(f"  Instancia: {movimiento.seccion}")
                    print(f"  Caratulado: {movimiento.caratulado}")
                    print(f"  {movimiento.identificador_causa or 'No disponible'}")
                    print(f"  Fecha: {movimiento.fecha}")
                    print(f"  PDF: {'Sí' if movimiento.tiene_pdf() else 'No'}")
                    if movimiento.tiene_pdf():
                        if len(movimiento.pdf_paths) == 1:
                            print(f"  Ruta PDF: {movimiento.pdf_paths[0]}")
                        else:
                            print(f"  PDFs ({len(movimiento.pdf_paths)}):")
                            for i, pdf_path in enumerate(movimiento.pdf_paths, 1):
                                print(f"    {i}. {pdf_path}")
                print("\n===========================================\n")

                # Enviar correo solo en dos casos: si hay o no hay movimientos nuevos
                if MOVIMIENTOS_GLOBALES:
                    asunto = f"Nuevos movimientos en el Poder Judicial"
                    enviar_correo(MOVIMIENTOS_GLOBALES, asunto)
                else:
                    enviar_correo(asunto="No hay nuevos movimientos en el Poder Judicial")
                
                return True
            else:
                print("No se pudo completar el proceso de login")
                return False
                
    except Exception as e:
        print(f"Error en la automatización del Poder Judicial: {str(e)}")
        return False

def limpiar_identificador(texto):
    if not texto:
        return ""
    # Elimina prefijos como "Libro :", "RIT :", "ROL:" (con o sin espacios)
    return re.sub(r'^(Libro\s*:|RIT\s*:|ROL\s*:)\s*', '', texto, flags=re.IGNORECASE).strip()

#Cuerpo del correo electrónico
def construir_cuerpo_html(movimientos, imagenes_cid=None):
    # Si no hay movimientos nuevos
    if not movimientos:
        return """
            <html>
            <head>
                <style>
                    body { font-family: Arial, sans-serif; }
                </style>
            </head>
            <body>
                <p>Estimado,</p>
                <p>Junto con saludar y esperando que se encuentre muy bien, le informo que no se encontraron nuevos movimientos para reportar en el Poder Judicial.</p>
                <p>Saludos cordiales</p>
            </body>
            </html>
            """
    # Si hay movimientos nuevos
    else:
        html = """
        <html>
        <head>
            <style>
                body { font-family: Arial, sans-serif; }
                .container { max-width: 800px; margin: 0 auto; padding: 20px; }
                .movimiento { margin-bottom: 30px; }
                .movimiento h3 { color: #333; margin-top: 0; }
                .movimiento ul { list-style-type: none; padding-left: 0; }
                .movimiento li { margin-bottom: 10px; }
                .movimiento strong { color: #555; }
            </style>
        </head>
        <body>
            <div class="container">
                <p>Estimado,</p>
                <p>Junto con saludar y esperando que se encuentre muy bien, envío movimientos nuevos en el Poder Judicial y su PDF asociado.</p>
                <p>Detalle de documentos:</p>
        """

        for i, mov in enumerate(movimientos, 1):
            # Extrae el identificador limpio
            identificador_limpio = limpiar_identificador(mov.rol) or limpiar_identificador(mov.rit) or limpiar_identificador(mov.libro)
            if not identificador_limpio:
                identificador_limpio = f"{i}"
            html += f"""
                <div class="movimiento">
                    <h2 style="text-align: center;">{identificador_limpio}, {mov.caratulado}{', ' + mov.corte if mov.corte else (', ' + mov.tribunal if mov.tribunal else '')}:</h2>
            """
            
            # Insertar imágenes preview para todos los PDFs
            if imagenes_cid and mov.tiene_pdf():
                for pdf_path in mov.pdf_paths:
                    preview_path = pdf_path.replace('.pdf', '_preview.png')
                    if preview_path in imagenes_cid:
                        html += f'<div style="text-align: center;"><img src="cid:{imagenes_cid[preview_path]}" style="max-width:600px;display:block;margin:0 auto 10px auto;"></div>'
            
            html += f"""
                    <ul>
                        <li>Instancia: {mov.seccion}</li>
                        <li>{mov.identificador_causa or 'No disponible'}</li>"""
            # Agregar corte o tribunal antes de Caratulado
            if mov.corte:
                html += f"""
                        <li>Corte: {mov.corte}</li>"""
            elif mov.tribunal:
                html += f"""
                        <li>Tribunal: {mov.tribunal}</li>"""
            html += f"""
                        <li>Caratulado: {mov.caratulado}</li>"""

            if mov.historia_causa_cuaderno:
                # Aplicar formato en negrita y color a "Escritos por Resolver" si aparece en el texto
                historia_formateada = mov.historia_causa_cuaderno
                if "Escritos por Resolver" in historia_formateada:
                    historia_formateada = historia_formateada.replace("Escritos por Resolver", "<span style='font-weight: bold;padding: 2px 4px;'>Escritos por Resolver</span>")
                html += f"""
                        <li>Historia Causa Cuaderno: {historia_formateada}</li>"""

            html += f"""
                        <li>Fecha Trámite: {mov.fecha}</li>"""
            
            # Mostrar todos los documentos
            if mov.tiene_pdf():
                if len(mov.pdf_paths) == 1:
                    html += f"""
                        <li>Documento: {os.path.basename(mov.pdf_paths[0])}</li>"""
                else:
                    html += """
                        <li>Documentos:
                            <ul>"""
                    for i, pdf_path in enumerate(mov.pdf_paths, 1):
                        html += f"""
                                <li>{i}. {os.path.basename(pdf_path)}</li>"""
                    html += """
                            </ul>
                        </li>"""
            else:
                html += """
                        <li>Documento: No disponible</li>"""

            # Agregar sección de Apelaciones si existe
            if mov.archivos_apelaciones:
                html += """
                        <li><strong>Apelaciones:</strong>
                            <ul>
                                <li>Archivos
                                    <ul>"""
                for archivo in mov.archivos_apelaciones:
                    html += f"""
                                        <li>{os.path.basename(archivo)}</li>"""
                html += """
                                    </ul>
                                </li>
                            </ul>
                        </li>"""

            html += """
                    </ul>
                </div>"""

        html += """
            </div>
        </body>
        </html>
        """
    return html

#Envía un correo electrónico con archivos adjuntos
def enviar_correo(movimientos=None, asunto="Notificación de Sistema de Poder Judicial"):
    from email.mime.image import MIMEImage  # por si no está arriba

    try:
        # Verificar credenciales
        if not all([EMAIL_SENDER, EMAIL_PASSWORD, EMAIL_RECIPIENTS]):
            logging.error("Faltan credenciales de correo electrónico")
            return False

        msg = MIMEMultipart()
        msg['From'] = EMAIL_SENDER
        msg['To'] = ", ".join(EMAIL_RECIPIENTS)
        msg['Subject'] = asunto

        # Adjuntar imágenes preview como inline y PDFs/archivos como adjuntos
        imagenes_cid = {}
        if movimientos:
            for movimiento in movimientos:
                # Adjuntar imágenes preview como inline para todos los PDFs
                if movimiento.tiene_pdf():
                    for pdf_path in movimiento.pdf_paths:
                        preview_path = pdf_path.replace('.pdf', '_preview.png')
                        if os.path.exists(preview_path):
                            cid = str(uuid.uuid4())
                            imagenes_cid[preview_path] = cid
                            try:
                                with open(preview_path, 'rb') as img:
                                    img_part = MIMEImage(img.read(), _subtype="png")
                                    img_part.add_header('Content-ID', f'<{cid}>')
                                    img_part.add_header('Content-Disposition', 'inline', filename=os.path.basename(preview_path))
                                    msg.attach(img_part)
                            except Exception as e:
                                logging.error(f"Error adjuntando imagen inline {preview_path}: {str(e)}")
                
                # Adjuntar todos los PDFs si existen
                if movimiento.tiene_pdf():
                    for pdf_path in movimiento.pdf_paths:
                        try:
                            with open(pdf_path, 'rb') as f:
                                part = MIMEApplication(f.read(), Name=os.path.basename(pdf_path))
                                part['Content-Disposition'] = f'attachment; filename="{os.path.basename(pdf_path)}"'
                                msg.attach(part)
                        except Exception as e:
                            logging.error(f"Error adjuntando archivo {pdf_path}: {str(e)}")
                # Adjuntar archivos de apelaciones si existen
                if movimiento.archivos_apelaciones:
                    for archivo_apelacion in movimiento.archivos_apelaciones:
                        try:
                            with open(archivo_apelacion, 'rb') as f:
                                part = MIMEApplication(f.read(), Name=os.path.basename(archivo_apelacion))
                                part['Content-Disposition'] = f'attachment; filename="{os.path.basename(archivo_apelacion)}"'
                                msg.attach(part)
                        except Exception as e:
                            logging.error(f"Error adjuntando archivo de apelación {archivo_apelacion}: {str(e)}")

        # Construir cuerpo HTML con los movimientos y los cid de las imágenes
        html_cuerpo = construir_cuerpo_html(movimientos, imagenes_cid)
        if html_cuerpo:
            msg.attach(MIMEText(html_cuerpo, 'html'))

        # Enviar correo con reintentos
        max_intentos = 3
        for intento in range(max_intentos):
            try:
                with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
                    server.starttls()
                    server.login(EMAIL_SENDER, EMAIL_PASSWORD)
                    server.send_message(msg)
                logging.info("Correo enviado exitosamente")
                return True
            except Exception as e:
                if intento < max_intentos - 1:
                    logging.warning(f"Intento {intento + 1} fallido. Reintentando...")
                    time.sleep(5)
                else:
                    logging.error(f"Error enviando correo después de {max_intentos} intentos: {str(e)}")
                    return False

    except Exception as e:
        logging.error(f"Error general en envío de correo: {str(e)}")
        return False
    
#flujo principal del script
def main():
    # Verificar si es fin de semana
    #today = datetime.datetime.now()
    #is_weekend = today.weekday() >= 5  # 5 = sábado, 6 = domingo

    #if is_weekend:
    #    logging.info("Hoy es fin de semana. No se realizan tareas.")
    #    return

    # Obtiene las variables de entorno
    USERNAME = os.getenv("RUT")
    PASSWORD = os.getenv("CLAVE")
    
    # Verifica si se cargaron las variables de entorno
    if USERNAME and PASSWORD:
        print("Las claves se han cargado correctamente.")
    else:
        print("Faltan claves en el archivo .env.")
        return
        
    # Verifica las credenciales de correo
    if not all([EMAIL_SENDER, EMAIL_PASSWORD, EMAIL_RECIPIENTS]):
        print("ADVERTENCIA: Faltan credenciales de correo electrónico en el archivo .env")
        print("Se requiere configurar:")
        if not EMAIL_SENDER:
            print("- EMAIL_SENDER: Correo del remitente")
        if not EMAIL_PASSWORD:
            print("- EMAIL_PASSWORD: Contraseña del correo")
        if not EMAIL_RECIPIENTS:
            print("- EMAIL_RECIPIENTS: Lista de correos destinatarios separados por coma")
        print("\nEl script continuará pero no se enviarán correos electrónicos.")

    playwright = None
    browser = None
    try:
        print("Iniciando navegador...")
        playwright, browser, page = setup_browser()
        
        # Ejecutar la automatización de PJUD
        automatizar_poder_judicial(page, USERNAME, PASSWORD)
        
    except Exception as e:
        print(f"Error en la ejecución principal: {str(e)}")

    finally:
        if browser:
            print("Cerrando el navegador...")
            browser.close()
        if playwright:
            playwright.stop()

if __name__ == "__main__":
    main()
