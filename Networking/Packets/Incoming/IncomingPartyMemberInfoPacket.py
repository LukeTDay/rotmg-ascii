from Networking.Packets.Packet import Packet
from Data.PartyPlayerData import PartyPlayerData

from typing import List

from Networking.Reader import Reader
class IncomingPartyMemberInfoPacket(Packet):
    def __init__(self):
        self.type = "INCOMINGPARTYMEMBERINFO"
        self.party_id = 0
        self.unknown = 0
        self.max_size = 0
        self.party_player_data : List[PartyPlayerData] = []
        self.description = ""
    
    def read(self, reader: Reader):
        self.party_id = reader.readInt32()
        self.unknown = reader.readShort()
        self.max_size = reader.readByte()
        num_players = reader.readShort()
        self.party_player_data = []
        for i in range(num_players):
            party_player = PartyPlayerData()
            party_player.read(reader=reader)
            self.party_player_data.append(party_player)
        self.description = reader.readStr()

    def write(self, writer):
        writer.writeInt32(self.party_id)
        writer.writeShort(self.unknown)
        writer.writeByte(self.max_size)
        writer.writeShort(len(self.party_player_data))
        for i in range(len(self.party_player_data)):
            self.party_player_data[i].write(writer=writer)
        writer.writeStr(self.description)

