from Networking.Packets.Packet import Packet


class PartyMemberAddedPacket(Packet):
    def __init__(self):
        self.type = "PARTYMEMBERADDED"
        self.player_id = 0
        self.name = "" 
        self.class_id = 0
        self.skin_id = 0

    def read(self,reader):
        self.player_id = reader.readShort()
        self.name  = reader.readStr()
        self.class_id = reader.readShort()
        self.skin_id = reader.readShort()

    def write(self, writer):
        writer.writeShort(self.player_id)
        writer.writeStr(self.name)
        writer.writeShort(self.class_id)
        writer.writeShort(self.skin_id)