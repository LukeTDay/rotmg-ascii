from Networking.Packets.Packet import Packet

class StasisPacket(Packet):
    def __init__(self):
        self.type = "STASIS"
        self.entityId = 0
        self.unknownBytes = b"\x00" * 12
        self.stasisDuration = 0.0

    def read(self, reader):
        self.entityId = reader.readInt32()
        self.unknownBytes = reader.readRawBytes(12)
        self.stasisDuration = reader.readFloat()

    def write(self, writer):
        writer.writeInt32(self.entityId)
        writer.writeRawBytes(self.unknownBytes)
        writer.writeFloat(self.stasisDuration)
