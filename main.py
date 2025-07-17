# main.py
import uvicorn

from server import app

if __name__ == "__main__":
    # host 0.0.0.0 se serve da altre macchine,
    # altrimenti 127.0.0.1 va bene.
    # Prova diverse porte se 8000 è occupata
    import socket
    
    def is_port_available(port):
        """Controlla se una porta è disponibile"""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return s.connect_ex(('127.0.0.1', port)) != 0
    
    port = 8000
    while not is_port_available(port) and port < 8010:
        port += 1
    
    if port >= 8010:
        print("⚠️  Nessuna porta disponibile tra 8000-8009")
        port = 8000  # usa 8000 e lascia che uvicorn mostri l'errore
    
    print(f"🚀 Avvio server su http://127.0.0.1:{port}")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")
