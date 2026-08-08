from Networking.Packets.Packet import Packet

class ClaimRewardsInfoPromptPacket(Packet):
    def __init__(self):
        self.type = "CLAIMREWARDSINFOPROMPT"
        self.promptId = 0
        self.unknownByte = 0
        self.items = []

    def write(self, writer):
        writer.writeInt32(self.promptId)
        writer.writeByte(self.unknownByte)
        writer.writeShort(len(self.items))
        for item in self.items:
            writer.writeInt32(item)

    def read(self, reader):
        self.promptId = reader.readInt32()
        self.unknownByte = reader.readByte()
        count = reader.readShort()
        self.items = [reader.readInt32() for _ in range(count)]
