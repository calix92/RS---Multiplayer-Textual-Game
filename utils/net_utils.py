import socket
import os

def get_local_ip():
    """Tenta descobrir o IP local da interface principal."""
    # Se estivermos em Docker com network=host, o IP do host deve ser detetado normalmente
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Não precisa de estar realmente ligado, o 8.8.8.8 é apenas para o SO 
        # escolher a interface de rede correta (rota default)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    
    # Se o IP detetado for um IP interno do Docker (172.17.x.x) e não estivermos em modo host real,
    # pode haver problemas. Mas com network_mode: host, o IP deve ser o do Host físico.
    return ip
