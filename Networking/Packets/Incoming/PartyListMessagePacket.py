from Networking.Packets.Packet import Packet
from Data.PartyData import PartyData
from typing import List

#This is a list of all the current feteched parties

class PartyListMessagePacket(Packet):
    def __init__(self):
        self.type = "PARTYLISTMESSAGE"   # optional but consistent with your system
        self.count = 0
        self.parties = []

    def read(self, reader):
        # Java: count = buffer.readByte();
        self.count = reader.readByte()

        # Java: parties = new PartyData[buffer.readShort()];
        num_parties = reader.readShort()

        self.parties = []
        for _ in range(num_parties):
            party = PartyData()
            party.read(reader)
            self.parties.append(party)

    def write(self, writer):
        writer.writeByte(self.count)
        writer.writeShort(len(self.parties))
        for party in self.parties:
            party.write(writer)
