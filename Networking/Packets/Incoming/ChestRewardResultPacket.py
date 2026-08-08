from Networking.Packets.Packet import Packet

class ChestRewardResultPacket(Packet):
    def __init__(self):
        self.type = "CHESTREWARDRESULT"
        self.unknownByte = 0
        self.unknownByte2 = 0
        self.itemType = 0

    def read(self, reader):
        self.unknownByte = reader.readByte()
        self.unknownByte2 = reader.readByte()
        self.itemType = reader.readInt32()

    def write(self, writer):
        writer.writeByte(self.unknownByte)
        writer.writeByte(self.unknownByte2)
        writer.writeInt32(self.itemType)
