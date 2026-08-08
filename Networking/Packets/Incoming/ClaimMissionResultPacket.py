from Networking.Packets.Packet import Packet

class ClaimMissionResultPacket(Packet):
    def __init__(self):
        self.type = "CLAIMMISSIONRESULT"
        self.unknownByte = 0
        self.unknownByte2 = 0
        self.unknownShort = 0

    def write(self, writer):
        writer.writeByte(self.unknownByte)
        writer.writeByte(self.unknownByte2)
        writer.writeShort(self.unknownShort)

    def read(self, reader):
        self.unknownByte = reader.readByte()
        self.unknownByte2 = reader.readByte()
        self.unknownShort = reader.readShort()
