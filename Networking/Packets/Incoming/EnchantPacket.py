from Networking.Packets.Packet import Packet

class EnchantPacket(Packet):
    def __init__(self):
        self.type = "ENCHANT"
        self.success = False

    def write(self, writer):
        writer.writeByte(1 if self.success else 0)

    def read(self, reader):
        self.success = reader.readByte() != 0
