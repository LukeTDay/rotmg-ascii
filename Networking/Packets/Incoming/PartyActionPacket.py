from Networking.Packets.Packet import Packet

class PartyActionPacket(Packet):
    def __init__(self):
        self.type = "PARTYACTION"
        self.player_id = 0

        #None(0),
        #Kick(1),
        #Disconnect(2),
        #PromoteToLeader(3),
        #Refresh(4),
        #GetPartyList(5),
        #LeaveParty(6),
        #TeleportTo(7);
        self.party_action_type = 0

    def read(self,reader):
        self.player_id = reader.readShort()
        self.party_action_type = reader.readByte()

    def write(self,writer):
        writer.writeShort(self.player_id)
        writer.writeByte(self.party_action_type)