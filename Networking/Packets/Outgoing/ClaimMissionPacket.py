from Networking.Packets.Packet import Packet

class ClaimMissionPacket(Packet):
    def __init__(self):
        self.type = "CLAIMMISSION"
        self.unknownInt = 0
        self.unknownInt2 = 0
        self.unknownByte = 0
        self.unknownShort = 0

    def read(self, reader):
        self.unknownInt = reader.readInt32()
        self.unknownInt2 = reader.readInt32()
        self.unknownByte = reader.readByte()
        self.unknownShort = reader.readShort()

    def write(self, writer):
        writer.writeInt32(self.unknownInt)
        writer.writeInt32(self.unknownInt2)
        writer.writeByte(self.unknownByte)
        writer.writeShort(self.unknownShort)
