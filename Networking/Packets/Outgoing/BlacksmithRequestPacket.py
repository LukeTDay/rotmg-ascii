from Networking.Packets.Packet import Packet
from Data.SlotObjectData import SlotObjectData

class BlacksmithRequestPacket(Packet):
    def __init__(self):
        self.type = "BLACKSMITHREQUEST"
        self.slots = []

    def read(self, reader):
        slotLen = reader.readByte()
        for i in range(slotLen):
            slot = SlotObjectData()
            slot.read(reader)
            self.slots.append(slot)

    def write(self, writer):
        writer.writeByte(len(self.slots))
        for slot in self.slots:
            slot.write(writer)
