from Networking.Packets.Packet import Packet

class ClaimRewardsInfoRequestPacket(Packet):
    def __init__(self):
        self.type = "CLAIMREWARDSINFOREQUEST"
        self.promptId = 0

    def read(self, reader):
        self.promptId = reader.readInt32()

    def write(self, writer):
        writer.writeInt32(self.promptId)
