from Networking.Reader import Reader
from Networking.Writer import Writer

class Packet:
    send = True
    def __init__(self):
        pass

    def read(self, reader : Reader):
        pass

    def write(self, writer : Writer):
        pass

    def __str__(self):
        return str(self.__dict__)