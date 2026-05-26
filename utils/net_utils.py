import socket

def get_local_ip():
    """Tenta descobrir o IP local da interface principal."""
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
    return ip
