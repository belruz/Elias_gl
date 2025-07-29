import requests
from datetime import datetime

def test_last_modified_headers():
    """Prueba si los servidores SII proporcionan Last-Modified"""
    
    # URLs de prueba basadas en tu script actual
    test_urls = [
        "https://www.sii.cl/normativa_legislacion/resoluciones/2025/reso1.pdf",
        "https://www.sii.cl/normativa_legislacion/resoluciones/2025/reso150.pdf",
        "https://www.sii.cl/normativa_legislacion/circulares/2025/circu1.pdf",
        "https://www.sii.cl/normativa_legislacion/circulares/2025/circu45.pdf",
    ]
    
    print("Verificando headers Last-Modified del servidor SII...\n")
    
    for url in test_urls:
        try:
            print(f"Probando: {url}")
            
            # Hacer petición HEAD (solo headers, no descarga el archivo)
            response = requests.head(url, timeout=10)
            
            print(f"Status Code: {response.status_code}")
            
            if response.status_code == 200:
                # Verificar si existe Last-Modified
                last_modified = response.headers.get('Last-Modified')
                
                if last_modified:
                    print(f"Last-Modified: {last_modified}")
                    
                    # Convertir a formato legible
                    try:
                        from email.utils import parsedate_to_datetime
                        dt = parsedate_to_datetime(last_modified)
                        print(f"Fecha parseada: {dt.strftime('%d/%m/%Y %H:%M:%S')}")
                    except Exception as e:
                        print(f"Error parseando fecha: {e}")
                else:
                    print(f"No hay header Last-Modified")
                
                # Mostrar otros headers útiles
                content_length = response.headers.get('Content-Length')
                content_type = response.headers.get('Content-Type')
                etag = response.headers.get('ETag')
                
                if content_length:
                    print(f"Content-Length: {content_length} bytes")
                if content_type:
                    print(f"Content-Type: {content_type}")
                if etag:
                    print(f"ETag: {etag}")
                    
            else:
                print(f"Archivo no encontrado (Status: {response.status_code})")
                
        except requests.exceptions.RequestException as e:
            print(f"Error de conexión: {e}")
        except Exception as e:
            print(f"Error inesperado: {e}")
            
        print("-" * 60)

if __name__ == "__main__":
    test_last_modified_headers()