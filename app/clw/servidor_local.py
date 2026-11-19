"""Servidor HTTP chiquito, solo en 127.0.0.1, para las pruebas (IA de mentiras, paginas de prueba).

No busca el nombre de la compu: el servidor normal de Python llama a socket.getfqdn(), y en macOS 15 esa busqueda
hace que salga encima de todo el aviso de "permitir encontrar dispositivos en redes locales" (tapa la pagina y los
clics de la prueba caen en el aviso)."""

import socketserver
from http.server import ThreadingHTTPServer


class ServidorLocal(ThreadingHTTPServer):
    daemon_threads = True

    def server_bind(self):
        socketserver.TCPServer.server_bind(self)
        self.server_name = "localhost"
        self.server_port = self.server_address[1]


def abrir(manejador):
    """Servidor en 127.0.0.1 con un puerto libre."""
    return ServidorLocal(("127.0.0.1", 0), manejador)
