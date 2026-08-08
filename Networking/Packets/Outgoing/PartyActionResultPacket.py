from Networking.Packets.Packet import Packet

class PartyActionResultPacket(Packet):
    def __init__(self):
        self.type = "PARTYACTIONRESULT"
        self.player_id = 0

        #None(0),
        #Failed(1),
        #Kicked(2),
        #KickNotFound(3),
        #PromotedToLeader(4),
        #PromoteNotFound(5),
        #LeftParty(6);
        self.party_action_type = 0
    
    def read(self, reader):
        self.player_id = reader.readShort()
        self.party_action_type = reader.readByte()

    def write(self, writer):
        writer.writeShort(self.player_id)
        writer.writeByte(self.party_action_type)