from Networking.Packets.Packet import Packet

class ClaimDailyItemPacket(Packet):
    def __init__(self):
        self.type = "CLAIMDAILYITEM"
        self.flag = 0
        self.key = ""
        self.category = ""

    def write(self, writer):
        writer.writeByte(self.flag)
        writer.writeStr(self.key)
        writer.writeStr(self.category)

    def read(self, reader):
        self.flag = reader.readByte()
        self.key = reader.readStr()
        self.category = reader.readStr()
