from Networking.Reader import Reader
from Networking.Writer import Writer

class PartyPlayerData():
    def __init__(self) -> None:
        self.id = 0
        self.name = ""
        self.object_id = 0
        self.unknown = 0

    def read(self, reader : Reader):
        self.id = reader.readShort()
        self.name = reader.readStr()
        self.object_id = reader.readShort()
        self.unknown = reader.readShort()

    def write(self, writer : Writer):
        writer.writeShort(self.id)
        writer.writeStr(self.name)
        writer.writeShort(self.object_id)
        writer.writeShort(self.unknown)